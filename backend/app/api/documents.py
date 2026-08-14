"""文档路由：上传 / 列表 / 回收站 / 批量操作 / 重建索引 / 分块查看 / 下载 / 导出。"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import client_ip, get_current_user, get_kb_or_404, require_roles
from app.core.config import settings
from app.db.base import get_db
from app.models import Document, User
from app.rag.parsers import SUPPORTED_TYPES
from app.schemas import ChunkOut, DocumentOut, TaskOut
from app.services.audit import ACTION_DOC_DELETE, ACTION_DOC_REINDEX, ACTION_DOC_UPLOAD, audit
from app.services.ingestion import (
    check_file,
    delete_document_artifacts,
    ingest_document,
)
from app.tasks.manager import task_manager

router = APIRouter(prefix="/api/kbs/{kb_id}/documents", tags=["文档"])

# 上传并发上限（防止恶意并发）
_UPLOADING: set[int] = set()


# ---------------- ZIP 批量导入 ----------------
@router.post("/upload-zip", summary="上传 ZIP 批量导入文档")
async def upload_zip(
    kb_id: int,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    import io
    import zipfile

    kb = get_kb_or_404(db, kb_id, user)
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"ZIP 超过 {settings.MAX_UPLOAD_MB}MB 上限")
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="不是有效的 ZIP 文件")

    uploaded: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    import hashlib

    for info in zf.infolist():
        if info.is_dir():
            continue
        name = Path(info.filename).name
        if not name or name.startswith(".") or name == "Thumbs.db":
            continue
        ext = Path(name).suffix.lower().lstrip(".")
        if ext not in SUPPORTED_TYPES:
            skipped.append(name)
            continue
        raw = zf.read(info)
        if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            failed.append(f"{name}(超限)")
            continue
        if not raw:
            skipped.append(name)
            continue
        try:
            kb_dir = settings.upload_dir / str(kb_id)
            kb_dir.mkdir(parents=True, exist_ok=True)
            stored = kb_dir / f"{uuid.uuid4().hex}_{name}"
            stored.write_bytes(raw)
            content_hash = hashlib.sha256(raw).hexdigest()
            dup = (
                db.query(Document)
                .filter(
                    Document.kb_id == kb_id,
                    Document.file_hash == content_hash,
                    Document.status != "failed",
                    Document.deleted_at.is_(None),
                )
                .first()
            )
            if dup:
                stored.unlink(missing_ok=True)
                skipped.append(f"{name}(重复)")
                continue
            doc = Document(
                kb_id=kb_id,
                filename=name,
                file_path=str(stored),
                file_type=ext,
                file_size=len(raw),
                file_hash=content_hash,
                status="pending",
                created_by=user.id,
            )
            db.add(doc)
            db.flush()
            await task_manager.submit(doc.id, kb_id, ingest_document(doc.id))
            uploaded.append(name)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{name}({e})")
    db.commit()
    audit(db, user, "doc.upload_zip", "document", kb_id, f"ZIP 导入 {len(uploaded)} 个文档", client_ip(request))
    return {
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "detail": f"导入完成：成功 {len(uploaded)}，跳过 {len(skipped)}，失败 {len(failed)}",
    }


@router.post("/upload", response_model=DocumentOut, summary="上传并异步索引文档")
async def upload_document(    kb_id: int,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    kb = get_kb_or_404(db, kb_id, user)
    # 知识库配额检查
    if settings.KB_MAX_DOCS > 0:
        cur = db.query(Document).filter(Document.kb_id == kb_id, Document.status != "failed").count()
        if cur >= settings.KB_MAX_DOCS:
            raise HTTPException(
                status_code=400,
                detail=f"知识库文档数已达上限（{settings.KB_MAX_DOCS} 个），请先清理或联系管理员调整",
            )
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型 .{ext}，支持: {', '.join(sorted(SUPPORTED_TYPES))}")

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件超过 {settings.MAX_UPLOAD_MB}MB 上限")
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 重复上传检测：同一知识库内内容相同（sha256）且不在回收站的文档拒绝
    import hashlib

    content_hash = hashlib.sha256(content).hexdigest()
    dup = (
        db.query(Document)
        .filter(
            Document.kb_id == kb_id,
            Document.file_hash == content_hash,
            Document.status != "failed",
            Document.deleted_at.is_(None),
        )
        .first()
    )
    if dup:
        raise HTTPException(
            status_code=400,
            detail=f"库中已存在内容相同的文档「{dup.filename}」，请勿重复上传",
        )

    safe_name = Path(file.filename or "unnamed").name
    kb_dir = settings.upload_dir / str(kb_id)
    kb_dir.mkdir(parents=True, exist_ok=True)
    stored = kb_dir / f"{uuid.uuid4().hex}_{safe_name}"
    stored.write_bytes(content)

    doc = Document(
        kb_id=kb_id,
        filename=safe_name,
        file_path=str(stored),
        file_type=ext,
        file_size=len(content),
        file_hash=content_hash,
        status="pending",
        created_by=user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    await task_manager.submit(doc.id, kb_id, ingest_document(doc.id))
    audit(db, user, ACTION_DOC_UPLOAD, "document", doc.id, f"上传文档「{safe_name}」({len(content)}B)", client_ip(request))
    return DocumentOut.model_validate(doc)


@router.get("", response_model=list[DocumentOut], summary="文档列表")
def list_documents(
    kb_id: int,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    q = db.query(Document).filter(Document.kb_id == kb_id, Document.deleted_at.is_(None))
    if status:
        q = q.filter(Document.status == status)
    return [DocumentOut.model_validate(d) for d in q.order_by(Document.id.desc()).all()]


@router.get("/trash", response_model=list[DocumentOut], summary="回收站：已删除文档")
def list_trash(
    kb_id: int,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    rows = (
        db.query(Document)
        .filter(Document.kb_id == kb_id, Document.deleted_at.isnot(None))
        .order_by(Document.deleted_at.desc())
        .all()
    )
    return [DocumentOut.model_validate(d) for d in rows]


@router.delete("/{doc_id}", summary="删除文档（进回收站，可恢复）")
def delete_document(
    kb_id: int,
    doc_id: int,
    request: Request,
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.deleted_at is not None:
        raise HTTPException(status_code=400, detail="文档已在回收站")
    # 软删除：移除索引但保留原始文件与记录（可恢复）
    delete_document_artifacts(kb_id, doc_id, remove_file=False)
    doc.status = "deleted"
    doc.deleted_at = __import__("datetime").datetime.utcnow()
    doc.chunk_count = 0
    db.commit()
    audit(db, user, ACTION_DOC_DELETE, "document", doc_id, f"删除文档「{doc.filename}」（回收站）", client_ip(request))
    return {"detail": "文档已移入回收站"}


@router.post("/{doc_id}/restore", response_model=TaskOut, summary="从回收站恢复并重建索引")
async def restore_document(
    kb_id: int,
    doc_id: int,
    request: Request,
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.deleted_at is None:
        raise HTTPException(status_code=400, detail="文档不在回收站")
    if not Path(doc.file_path).exists():
        raise HTTPException(status_code=400, detail="原始文件已丢失，无法恢复")
    doc.deleted_at = None
    doc.status = "pending"
    doc.error = ""
    db.commit()
    await task_manager.submit(doc.id, kb_id, ingest_document(doc.id))
    audit(db, user, "doc.restore", "document", doc_id, f"恢复文档「{doc.filename}」", client_ip(request))
    return TaskOut(doc_id=doc_id, status="pending", progress=0, error="")


@router.post("/{doc_id}/purge", summary="彻底删除（不可恢复）")
def purge_document(
    kb_id: int,
    doc_id: int,
    request: Request,
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    delete_document_artifacts(kb_id, doc_id)
    db.delete(doc)
    db.commit()
    audit(db, user, "doc.purge", "document", doc_id, f"彻底删除「{doc.filename}」", client_ip(request))
    return {"detail": "文档已彻底删除"}


@router.post("/{doc_id}/replace", response_model=DocumentOut, summary="更新文档版本（同名替换，保留问答引用）")
async def replace_document(
    kb_id: int,
    doc_id: int,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    """用新文件替换已有文档：移除旧索引、覆盖文件、重新索引。"""
    get_kb_or_404(db, kb_id, user)
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.deleted_at is not None:
        raise HTTPException(status_code=400, detail="文档在回收站中，请先恢复")
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型 .{ext}")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件超过 {settings.MAX_UPLOAD_MB}MB 上限")

    import hashlib

    # 先移除旧索引（保留旧文件直到新文件写入成功）
    delete_document_artifacts(kb_id, doc_id, remove_file=False)
    old_path = Path(doc.file_path) if doc.file_path else None
    old_suffix = old_path.suffix.lower().lstrip(".") if old_path else ""
    if old_path and old_suffix == ext and old_path.exists():
        # 扩展名一致：覆盖原文件
        old_path.write_bytes(content)
        stored = old_path
    else:
        # 扩展名变化（如 pdf→md）：用新路径存储，避免解析器按旧扩展名处理
        safe_name = Path(file.filename or doc.filename).name
        kb_dir = settings.upload_dir / str(kb_id)
        kb_dir.mkdir(parents=True, exist_ok=True)
        stored = kb_dir / f"{uuid.uuid4().hex}_{safe_name}"
        stored.write_bytes(content)
        if old_path and old_path.exists():
            try:
                old_path.unlink()
            except OSError:
                pass
        doc.file_path = str(stored)
    doc.filename = Path(file.filename or doc.filename).name[:255]
    doc.file_type = ext
    doc.file_size = len(content)
    doc.file_hash = hashlib.sha256(content).hexdigest()
    doc.status = "pending"
    doc.error = ""
    doc.sensitive_flags = ""
    doc.chunk_count = 0
    db.commit()
    await task_manager.submit(doc.id, kb_id, ingest_document(doc.id))
    audit(db, user, "doc.replace", "document", doc_id, f"更新文档版本「{doc.filename}」", client_ip(request))
    return DocumentOut.model_validate(doc)


# ---------------- 批量操作 ----------------
class BatchDocsRequest(BaseModel):
    action: str = Field(pattern=r"^(delete|reindex)$")
    ids: List[int] = Field(min_length=1, max_length=200)


@router.post("/batch", summary="批量操作：delete（进回收站）/ reindex（重建）")
async def batch_documents(
    kb_id: int,
    body: BatchDocsRequest,
    request: Request,
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    docs = (
        db.query(Document)
        .filter(Document.kb_id == kb_id, Document.id.in_(body.ids), Document.deleted_at.is_(None))
        .all()
    )
    if not docs:
        raise HTTPException(status_code=404, detail="未找到有效文档")
    done = 0
    for doc in docs:
        if body.action == "delete":
            delete_document_artifacts(kb_id, doc.id, remove_file=False)
            doc.status = "deleted"
            doc.deleted_at = __import__("datetime").datetime.utcnow()
            doc.chunk_count = 0
            done += 1
        else:  # reindex
            if Path(doc.file_path).exists():
                doc.status = "pending"
                doc.error = ""
                done += 1
    db.commit()
    if body.action == "reindex":
        for doc in docs:
            if doc.status == "pending":
                await task_manager.submit(doc.id, kb_id, ingest_document(doc.id))
    audit(
        db, user,
        "doc.batch." + body.action, "document", ",".join(str(d.id) for d in docs),
        f"批量{body.action} {len(docs)} 个文档", client_ip(request),
    )
    return {"detail": f"已对 {done} 个文档执行 {body.action}"}


@router.post("/{doc_id}/reindex", response_model=TaskOut, summary="重建索引")
async def reindex_document(
    kb_id: int,
    doc_id: int,
    request: Request,
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not Path(doc.file_path).exists():
        raise HTTPException(status_code=400, detail="原始文件丢失，无法重建")
    await task_manager.submit(doc.id, kb_id, ingest_document(doc.id))
    audit(db, user, ACTION_DOC_REINDEX, "document", doc_id, f"重建索引「{doc.filename}」", client_ip(request))
    return TaskOut(doc_id=doc_id, status="processing", progress=0, error="")


@router.get("/{doc_id}/chunks", response_model=list[ChunkOut], summary="查看文档分块")
def document_chunks(
    kb_id: int,
    doc_id: int,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    from app.models import Chunk

    rows = (
        db.query(Chunk)
        .filter(Chunk.doc_id == doc_id)
        .order_by(Chunk.chunk_index)
        .limit(500)
        .all()
    )
    return [
        ChunkOut(
            doc_id=doc_id,
            chunk_index=r.chunk_index,
            content=r.content,
            metadata={"page": r.page, "section": r.section},
        )
        for r in rows
    ]


@router.get("/{doc_id}/download", summary="下载原始文件")
def download_document(
    kb_id: int,
    doc_id: int,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    p = Path(doc.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="文件丢失")
    return FileResponse(str(p), filename=doc.filename)


@router.get("/{doc_id}/status", response_model=TaskOut, summary="索引任务状态")
def doc_status(
    kb_id: int,
    doc_id: int,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    get_kb_or_404(db, kb_id, user)
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    return TaskOut(doc_id=doc_id, status=doc.status, progress=doc.progress, error=doc.error)


@router.get("/export", summary="导出知识库备份（JSON）")
def export_kb(
    kb_id: int,
    request: Request,
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    """导出知识库全部文档与分块（含元数据），用于备份/迁移。"""
    kb = get_kb_or_404(db, kb_id, user)
    from app.models import Chunk

    docs = db.query(Document).filter(Document.kb_id == kb_id).order_by(Document.id).all()
    chunks = db.query(Chunk).filter(Chunk.kb_id == kb_id).order_by(Chunk.id).all()
    payload = {
        "exported_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "version": 1,
        "knowledge_base": {
            "id": kb.id,
            "name": kb.name,
            "description": kb.description,
            "embed_model": kb.embed_model,
            "chunk_size": kb.chunk_size,
            "chunk_overlap": kb.chunk_overlap,
            "doc_count": kb.doc_count,
            "chunk_count": kb.chunk_count,
        },
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "file_type": d.file_type,
                "file_size": d.file_size,
                "status": d.status,
                "chunk_count": d.chunk_count,
                "sensitive_flags": d.sensitive_flags,
                "created_at": d.created_at.isoformat(),
            }
            for d in docs
        ],
        "chunks": [
            {
                "id": c.id,
                "doc_id": c.doc_id,
                "chunk_index": c.chunk_index,
                "page": c.page,
                "section": c.section,
                "content": c.content,
            }
            for c in chunks
        ],
    }
    import json
    from urllib.parse import quote

    from fastapi.responses import JSONResponse

    audit(db, user, "kb.export", "kb", kb.id, f"导出知识库「{kb.name}」", client_ip(request))
    safe = kb.name.replace("/", "_").replace("\\", "_")
    fname = f"kb_{kb.id}_{safe}.json"
    # HTTP 头只允许 ASCII：中文文件名用 RFC 5987 filename* 编码
    disposition = f"attachment; filename=\"kb_{kb.id}.json\"; filename*=UTF-8''{quote(fname)}"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": disposition},
    )
