"""文档索引流水线：解析 → 切分 → 向量化 → 落库（chunks + Chroma + FTS）。

作为后台任务运行；删除文档 / 重建索引 / 删除知识库共用底层逻辑。
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import List

from app.core.config import settings
from app.db.base import SessionLocal
from app.models import Chunk, Document, KnowledgeBase
from app.rag.chunkers import chunk_document
from app.rag.llm import LLMError, llm_client
from app.rag.parsers import ParseError, SUPPORTED_TYPES, parse_file
from app.rag.retriever import delete_keyword_index, index_chunks
from app.rag.vector_store import vector_store

logger = logging.getLogger(__name__)


def notify(db, user_id: int, ntype: str, title: str, content: str = "") -> None:
    """站内通知（索引完成/失败等）。"""
    try:
        from app.models import Notification

        db.add(Notification(user_id=user_id, ntype=ntype, title=title[:200], content=content[:500]))
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("notify failed: %s", e)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


def _set_doc(db, doc_id: int, **fields) -> None:
    doc = db.get(Document, doc_id)
    if doc:
        for k, v in fields.items():
            setattr(doc, k, v)
        db.commit()


def _apply_file(file_path: Path, kb: KnowledgeBase, doc: Document) -> tuple[int, str]:
    """同步执行解析+切分+向量化+落库。

    返回 (chunk 数, 实际使用的向量模型)。失败抛出异常。
    """
    # 1) 解析
    pages = parse_file(file_path)
    full_text = "\n\n".join(t for t, _ in pages)
    is_md = file_path.suffix.lower() in (".md", ".markdown")
    base_chunks: List[dict] = []
    # 按页切分（保留 page 元数据）
    page_map: dict[int, int] = {}
    idx = 0
    for text, page in pages:
        for c in chunk_document(text, kb.chunk_size, kb.chunk_overlap, is_md):
            c["metadata"]["page"] = page
            base_chunks.append(c)
            page_map[idx] = page or 0
            idx += 1
    if not base_chunks:
        raise ParseError("文档解析后没有可用文本")

    # 2) 向量化（指定模型失败自动降级到配置中的其它模型）
    vectors = llm_client.embed([c["text"] for c in base_chunks], model=kb.embed_model or None)
    if len(vectors) != len(base_chunks):
        raise LLMError(f"向量数量不匹配: {len(vectors)} != {len(base_chunks)}")
    used_embed_model = llm_client.active_embed_model

    # 2.1) 敏感信息检测（合规告警）
    from app.rag.sensitive import detect_sensitive_join

    sensitive_flags = detect_sensitive_join(full_text)

    # 3) 落库：chunks 表（事实源）
    # 注意：FTS 清理必须在 chunks 写事务提交之后执行，否则同线程内
    # 连接自持写锁导致 SQLite database is locked（单任务自锁死）。
    db = SessionLocal()
    try:
        old_ids = [r.id for r in db.query(Chunk).filter(Chunk.doc_id == doc.id).all()]
        if old_ids:
            db.query(Chunk).filter(Chunk.id.in_(old_ids)).delete(synchronize_session=False)
        chunk_rows = []
        for i, c in enumerate(base_chunks):
            row = Chunk(
                kb_id=kb.id,
                doc_id=doc.id,
                chunk_index=i,
                content=c["text"],
                page=c["metadata"].get("page"),
                section=c["metadata"].get("section"),
            )
            db.add(row)
            chunk_rows.append(row)
        db.flush()
        chunk_ids = [r.id for r in chunk_rows]
        db.commit()
    finally:
        db.close()

    # 3.1) FTS 旧索引清理（chunks 事务已提交，无锁冲突）
    if old_ids:
        delete_keyword_index(kb.id, doc.id)

    # 4) 落库：Chroma 向量
    chunk_dicts = [
        {
            "chunk_id": cid,
            "text": base_chunks[i]["text"],
            "chunk_index": i,
            "page": base_chunks[i]["metadata"].get("page"),
            "section": base_chunks[i]["metadata"].get("section"),
        }
        for i, cid in enumerate(chunk_ids)
    ]
    vector_store.upsert_chunks(
        kb.id,
        doc.id,
        chunk_dicts,
        vectors,
        base_metadata={"filename": doc.filename, "file_type": doc.file_type},
    )
    # 5) 落库：FTS 关键词索引
    db = SessionLocal()
    try:
        rows = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
        index_chunks(kb.id, doc.id, rows)
    finally:
        db.close()
    return len(chunk_ids), used_embed_model, sensitive_flags


async def ingest_document(doc_id: int) -> None:
    """后台任务：完整索引一个文档。"""
    logger.info("ingest start doc=%s", doc_id)
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        if not doc:
            return
        kb = db.get(KnowledgeBase, doc.kb_id)
        if not kb:
            return
        _set_doc(db, doc_id, status="processing", progress=5, error="")
        file_path = Path(doc.file_path)
        if not file_path.exists():
            _set_doc(db, doc_id, status="failed", error="文件丢失，请重新上传")
            notify(db, doc.created_by, "doc_failed", f"文档「{doc.filename}」索引失败", "原始文件丢失，请重新上传")
            return
        _set_doc(db, doc_id, progress=20)
        chunk_count, used_model, sensitive_flags = await asyncio.to_thread(_apply_file, file_path, kb, doc)
        _set_doc(db, doc_id, status="ready", progress=100, chunk_count=chunk_count, error="", sensitive_flags=sensitive_flags)
        # 更新 KB 统计与向量模型（保证后续检索与库内向量一致）
        kb.embed_model = used_model
        kb.doc_count = db.query(Document).filter(Document.kb_id == kb.id, Document.status == "ready").count()
        kb.chunk_count = (
            db.query(Chunk).filter(Chunk.kb_id == kb.id).count()
        )
        kb.updated_at = __import__("datetime").datetime.utcnow()
        db.commit()
        logger.info("ingest done doc=%s chunks=%s embed_model=%s", doc_id, chunk_count, used_model)
        notify(db, doc.created_by, "doc_indexed", f"文档「{doc.filename}」索引完成", f"共 {chunk_count} 个分块")
    except Exception as e:  # noqa: BLE001
        logger.exception("ingest failed doc=%s", doc_id)
        try:
            _set_doc(db, doc_id, status="failed", error=str(e)[:1000])
            notify(db, doc.created_by, "doc_failed", f"文档「{doc.filename}」索引失败", str(e)[:300])
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def delete_document_artifacts(kb_id: int, doc_id: int, remove_file: bool = True) -> None:
    """删除一个文档的全部索引（chunks/FTS/Chroma）。

    remove_file=True 时同时删除原始文件（彻底删除用）；
    软删除（回收站）传 remove_file=False 保留文件以便恢复。
    """
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        if remove_file and doc and doc.file_path:
            p = Path(doc.file_path)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        old = db.query(Chunk).filter(Chunk.doc_id == doc_id).all()
        if old:
            db.query(Chunk).filter(Chunk.id.in_([r.id for r in old])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    delete_keyword_index(kb_id, doc_id)
    vector_store.delete_document(kb_id, doc_id)


def delete_kb_artifacts(kb_id: int) -> None:
    """删除知识库的全部索引数据。"""
    db = SessionLocal()
    try:
        rows = db.query(Document).filter(Document.kb_id == kb_id).all()
        for doc in rows:
            if doc.file_path:
                p = Path(doc.file_path)
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
        db.query(Chunk).filter(Chunk.kb_id == kb_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    delete_keyword_index(kb_id, 0)  # kb_id 维度清理（doc 参数忽略）
    # FTS 按 kb 清理
    from sqlalchemy import text
    from app.db.base import engine

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM chunk_fts WHERE kb_id = :kb"), {"kb": kb_id})
    vector_store.delete_kb(kb_id)


SUPPORTED_TYPES_EXT = sorted(SUPPORTED_TYPES)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def check_file(path: Path) -> None:
    ext = path.suffix.lower().lstrip(".")
    if ext not in SUPPORTED_TYPES:
        raise ParseError(f"不支持的文件类型 .{ext}，支持: {', '.join(SUPPORTED_TYPES_EXT)}")
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        raise ParseError("文件超过 50MB 上限")


def import_kb_from_json(payload: dict, user_id: int) -> KnowledgeBase:
    """从导出 JSON 恢复知识库：重建元数据、文档、分块与全部索引。

    向量需重新计算（导出不含向量），embedding 模型取配置默认。
    返回新建的 KnowledgeBase。
    """
    kb_info = payload.get("knowledge_base") or {}
    base_name = (kb_info.get("name") or "导入知识库").strip()[:100]
    db = SessionLocal()
    try:
        kb = KnowledgeBase(
            name=f"{base_name}（导入）",
            description=(kb_info.get("description") or "")[:2000],
            tenant_id=None,
            embed_model=settings.EMBEDDING_MODEL,
            chunk_size=int(kb_info.get("chunk_size") or settings.CHUNK_SIZE),
            chunk_overlap=int(kb_info.get("chunk_overlap") or settings.CHUNK_OVERLAP),
            created_by=user_id,
        )
        db.add(kb)
        db.flush()

        all_chunks = payload.get("chunks") or []
        total_chunks = 0
        # 收集 (doc, chunk_rows) 供提交后统一建 FTS
        pending_fts: list[tuple[int, list]] = []
        for d in payload.get("documents") or []:
            doc_chunks = [c for c in all_chunks if c.get("doc_id") == d.get("id")]
            texts = [(c.get("content") or "").strip() for c in doc_chunks]
            texts = [t for t in texts if t]
            if not texts:
                continue
            doc = Document(
                kb_id=kb.id,
                filename=(d.get("filename") or "imported")[:255],
                file_path="",
                file_type=(d.get("file_type") or "txt"),
                file_size=int(d.get("file_size") or 0),
                status="ready",
                created_by=user_id,
            )
            db.add(doc)
            db.flush()
            # 向量化（同步；大库导入耗时由调用方提示）
            vectors = llm_client.embed(texts, model=kb.embed_model or None)
            chunk_rows = []
            for i, (c, text) in enumerate(zip(doc_chunks, texts)):
                row = Chunk(
                    kb_id=kb.id,
                    doc_id=doc.id,
                    chunk_index=int(c.get("chunk_index") or i),
                    content=text,
                    page=c.get("page"),
                    section=c.get("section"),
                )
                db.add(row)
                chunk_rows.append(row)
            db.flush()
            chunk_ids = [r.id for r in chunk_rows]
            # Chroma（独立存储，无 SQLite 锁冲突）
            chunk_dicts = [
                {
                    "chunk_id": cid,
                    "text": texts[i],
                    "chunk_index": i,
                    "page": chunk_rows[i].page,
                    "section": chunk_rows[i].section,
                }
                for i, cid in enumerate(chunk_ids)
            ]
            vector_store.upsert_chunks(
                kb.id, doc.id, chunk_dicts, vectors,
                base_metadata={"filename": doc.filename, "file_type": doc.file_type},
            )
            doc.chunk_count = len(chunk_ids)
            total_chunks += len(chunk_ids)
            pending_fts.append((doc.id, chunk_rows))

        kb.doc_count = db.query(Document).filter(Document.kb_id == kb.id, Document.status == "ready").count()
        kb.chunk_count = total_chunks
        db.commit()
        # FTS 索引必须在 SQLite 写事务提交后执行（否则同线程连接自持锁）
        for doc_id, chunk_rows in pending_fts:
            index_chunks(kb.id, doc_id, chunk_rows)
        db.refresh(kb)
        return kb
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
