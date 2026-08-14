"""混合检索器：向量（Chroma）+ 关键词（SQLite FTS5 + jieba）+ RRF 融合 + LLM 重排。

chunks 表（SQLAlchemy）是知识块的事实源；Chroma 与 FTS5 均为其索引，
检索命中后统一回表获取完整内容与来源信息。
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import List, Optional

from sqlalchemy import text

from app.core.config import settings
from app.db.base import engine
from app.models import Chunk
from app.rag.llm import chat_sync, llm_client
from app.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

_RRF_K = 60

# ---------- 关键词索引（SQLite FTS5 + jieba）----------


def init_fts() -> None:
    """建 FTS5 虚拟表（幂等）+ 清理孤儿索引行。"""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                    content,
                    kb_id UNINDEXED,
                    doc_id UNINDEXED
                )
                """
            )
        )
        # 清理孤儿行：FTS rowid 必须对应 chunks 表真实存在的块
        # （异常中断/旧版删除流程可能残留，而 SQLite rowid 可复用导致插入冲突）
        conn.execute(
            text("DELETE FROM chunk_fts WHERE rowid NOT IN (SELECT id FROM chunks)")
        )


def _segment(text: str) -> List[str]:
    import jieba

    return [t.strip() for t in jieba.cut(text) if t.strip()]


def index_chunks(kb_id: int, doc_id: int, chunk_rows: List[Chunk]) -> None:
    """为一个文档的全部块建立关键词索引（先清旧后插入）。"""
    ids = [r.id for r in chunk_rows]
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM chunk_fts WHERE kb_id = :kb AND doc_id = :doc"),
            {"kb": kb_id, "doc": doc_id},
        )
        # 防御 SQLite rowid 复用：精确清理目标 rowid（处理历史孤儿行）
        if ids:
            placeholders = ", ".join(f":rid{i}" for i in range(len(ids)))
            conn.execute(
                text(f"DELETE FROM chunk_fts WHERE rowid IN ({placeholders})"),
                {f"rid{i}": v for i, v in enumerate(ids)},
            )
        for row in chunk_rows:
            tokens = _segment(row.content)
            if not tokens:
                continue
            conn.execute(
                text(
                    "INSERT INTO chunk_fts(rowid, content, kb_id, doc_id) VALUES (:id, :content, :kb, :doc)"
                ),
                {"id": row.id, "content": " ".join(tokens), "kb": kb_id, "doc": doc_id},
            )


def delete_keyword_index(kb_id: int, doc_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM chunk_fts WHERE kb_id = :kb AND doc_id = :doc"),
            {"kb": kb_id, "doc": doc_id},
        )


# ---------- 检索来源 ----------


def _keyword_search(kb_id: int, query: str, top_k: int) -> List[dict]:
    """BM25 关键词检索（jieba 分词 + OR 组合，BM25 排序天然偏好多词命中）。"""
    tokens = _segment(query)
    if not tokens:
        return []
    # OR 组合：任一关键词命中即召回，避免 AND 组合在短查询时误伤
    match_expr = " OR ".join(f'"{t}"' for t in tokens[:16])
    sql = text(
        """
        SELECT rowid AS chunk_id, bm25(chunk_fts, 1.0, 1.0) AS rank
        FROM chunk_fts
        WHERE chunk_fts MATCH :q AND kb_id = :kb
        ORDER BY rank
        LIMIT :lim
        """
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {"q": match_expr, "kb": kb_id, "lim": top_k}).fetchall()
    except Exception as e:  # noqa: BLE001  FTS 语法异常时退化为空
        logger.warning("keyword search failed: %s", e)
        return []
    return [{"chunk_id": r.chunk_id, "score": -float(r.rank)} for r in rows]


def _vector_search(kb_id: int, query_vector: List[float], top_k: int, where: Optional[dict]) -> List[dict]:
    hits = vector_store.search(kb_id, query_vector, top_k=top_k, where=where)
    out = []
    for h in hits:
        meta = h["metadata"]
        cid = meta.get("chunk_id")
        if cid is None:
            continue
        out.append({"chunk_id": int(cid), "score": float(h["score"])})
    return out


def _load_chunks(kb_ids: List[int], ids: List[int], db) -> dict[int, dict]:
    """回表加载 chunk 完整信息（含来源文件名、所属知识库）。支持多库。"""
    if not ids:
        return {}
    rows = (
        db.query(Chunk)
        .filter(Chunk.id.in_(ids), Chunk.kb_id.in_(kb_ids))
        .all()
    )
    doc_ids = {r.doc_id for r in rows}
    doc_map = {}
    if doc_ids:
        from app.models import Document

        for d in db.query(Document).filter(Document.id.in_(doc_ids)).all():
            doc_map[d.id] = d.filename
    out = {}
    for r in rows:
        out[r.id] = {
            "chunk_id": r.id,
            "text": r.content,
            "doc_id": r.doc_id,
            "chunk_index": r.chunk_index,
            "page": r.page,
            "section": r.section,
            "filename": doc_map.get(r.doc_id, ""),
            "kb_id": r.kb_id,
        }
    return out


# ---------- 融合与重排 ----------


def _rrf_fuse(lists: List[List[dict]], top_k: int) -> List[dict]:
    """Reciprocal Rank Fusion：按排名倒数加权合并多个来源。"""
    scores: dict[int, float] = {}
    merged: dict[int, dict] = {}
    for ranked in lists:
        for rank, item in enumerate(ranked, start=1):
            cid = item["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
            if cid not in merged:
                merged[cid] = item
    ranked_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
    out = []
    for cid in ranked_ids:
        item = dict(merged[cid])
        item["score"] = round(scores[cid], 4)  # RRF 融合分
        out.append(item)
    return out


def _ensure_diversity(merged: List[dict], top_k: int) -> List[dict]:
    """来源多样性保底：每个文档至少保留一条最相关片段，再按分数填充剩余名额。

    解决"问技术栈只回答一篇论文"的问题：不同文档的代表片段不会被同文档的
    高分片段完全挤掉（详见重排 prompt 的第 6 条，这里做硬性兜底）。
    """
    if len(merged) <= 1:
        return merged
    seen: set = set()
    first: List[dict] = []
    rest: List[dict] = []
    for m in merged:
        did = m.get("doc_id")
        if did not in seen:
            seen.add(did)
            first.append(m)
        else:
            rest.append(m)
    out = list(first)
    for m in rest:
        if len(out) >= top_k:
            break
        out.append(m)
    return out


_RERANK_PROMPT = """你是一个严谨的文档检索相关性评估器。给定【问题】和若干【候选片段】，请：
1. 仅根据片段内容与问题的相关性进行排序；
2. 输出最相关的前 {top_n} 个片段的编号；
3. 涉及列举/统计类问题（如"有几个/哪些/多少"）时，与问题直接相关的片段一律保留，不得遗漏；
4. 多个片段内容高度相似（重复）时，优先保留信息最完整的；
5. **主体一致性检查（关键）**：若问题指向特定主体（如具体的人名、项目、公司），
   片段来源文档与主体不一致（例如问题问「姚俊吉」，片段来自他人/其他主题的文档），
   一律视为不相关并剔除，不得入选；
6. **多文档覆盖（关键）**：若问题**未指定具体主体/文档**（如"用了什么技术""包含哪些内容"
   "有哪些论文"），应覆盖多个不同来源文档的片段——每个相关文档至少保留一条最相关片段，
   避免只选单个文档的多个片段而遗漏其他文档；
7. 格式为严格 JSON：{{"ranked_ids": [编号, ...]}}，编号从 0 开始。只输出 JSON，不要任何解释。

【问题】
{query}

【候选片段】
{numbered}
"""


def _rerank(query: str, candidates: List[dict], top_n: int) -> List[dict]:
    """LLM 重排：模型挑选最相关片段并排序。"""
    if len(candidates) <= top_n:
        return candidates
    numbered = "\n\n".join(
        f"[{i}] (来源:{c.get('filename', '')}) {c['text'][:500]}" for i, c in enumerate(candidates)
    )
    prompt = _RERANK_PROMPT.format(query=query[:500], numbered=numbered, top_n=top_n)
    try:
        content, _model = chat_sync(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=128,
        )
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            logger.warning("rerank: 无 JSON 输出: %s", content[:100])
            return candidates[:top_n]
        ranked = json.loads(m.group(0)).get("ranked_ids", [])[:top_n]
        out = []
        for idx in ranked:
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                out.append(candidates[idx])
        return out or candidates[:top_n]
    except Exception as e:  # noqa: BLE001
        logger.warning("rerank failed, fallback: %s", e)
        return candidates[:top_n]


# ---------- 对外主入口 ----------


def retrieve(
    kb_id: int,
    query: str,
    query_vector: Optional[List[float]] = None,
    top_k: int = 0,
    where: Optional[dict] = None,
    db=None,
    extra_kb_ids: Optional[List[int]] = None,
    debug: bool = False,
    enable_hybrid: bool | None = None,
    enable_rerank: bool | None = None,
) -> dict:
    """完整检索：向量 + 关键词 → RRF 融合 → LLM 重排。

    支持多知识库联合检索（kb_id 为主库 + extra_kb_ids 联合库）。
    debug=True 时返回分步中间结果（向量命中/关键词命中/融合/重排），供检索调试台使用。

    返回 {"chunks": [...], "model": str, "timings_ms": {...}, ...}
    """
    kb_ids = [kb_id] + (extra_kb_ids or [])
    top_k = top_k or settings.RETRIEVE_TOP_K
    rerank_top = min(settings.RERANK_TOP_K, top_k)
    hybrid = settings.ENABLE_HYBRID if enable_hybrid is None else enable_hybrid
    rerank = settings.ENABLE_RERANK if enable_rerank is None else enable_rerank
    timings: dict[str, float] = {}

    # 多召回、多候选，避免汇总/列举类问题丢失细节块
    recall_k = max(top_k * 2, 16)
    fuse_k = max(top_k, 12)

    t0 = time.perf_counter()
    all_vec: List[dict] = []
    all_kw: List[dict] = []
    for kid in kb_ids:
        if query_vector:
            all_vec.extend(_vector_search(kid, query_vector, recall_k, where))
        if hybrid:
            all_kw.extend(_keyword_search(kid, query, recall_k))
    timings["vector_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    t0 = time.perf_counter()
    merged = _rrf_fuse([all_vec, all_kw], fuse_k)
    timings["fuse_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    fuse_scores = {m["chunk_id"]: m.get("score", 0.0) for m in merged}

    # 来源多样性保底：不同文档至少各保留一条（避免单文档垄断上下文）
    merged = _ensure_diversity(merged, fuse_k)

    # 回表补全内容
    if db is not None and merged:
        loaded = _load_chunks(kb_ids, [m["chunk_id"] for m in merged], db)
        merged = [loaded[m["chunk_id"]] for m in merged if m["chunk_id"] in loaded]
        for m in merged:
            src = fuse_scores.get(m["chunk_id"])
            if src is not None:
                m["score"] = src

    model = llm_client.active_chat_model
    t0 = time.perf_counter()
    if rerank and merged:
        merged = _rerank(query, merged, rerank_top)
    timings["rerank_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    out: dict = {"chunks": merged, "model": model, "timings_ms": timings}
    if debug and db is not None:
        out["debug"] = {
            "embed_model": llm_client.active_embed_model,
            "vector_hits": _hits_with_text(kb_ids, all_vec, db),
            "keyword_hits": _hits_with_text(kb_ids, all_kw, db),
            "fused_hits": _hits_with_text(kb_ids, [{"chunk_id": m["chunk_id"], "score": m.get("score", 0)} for m in merged], db),
            "reranked_hits": _hits_with_text(kb_ids, [{"chunk_id": m["chunk_id"], "score": m.get("score", 0)} for m in merged], db),
            "final_hits": _hits_with_text(kb_ids, [{"chunk_id": m["chunk_id"], "score": m.get("score", 0)} for m in merged], db),
        }
    return out


def _hits_with_text(kb_ids: List[int], hits: List[dict], db) -> List[dict]:
    """把命中列表补上 chunk 文本与来源信息（供调试台展示）。"""
    if not hits:
        return []
    loaded = _load_chunks(kb_ids, [h["chunk_id"] for h in hits[:12]], db)
    out = []
    for h in hits[:12]:
        c = loaded.get(h["chunk_id"])
        if not c:
            continue
        out.append(
            {
                "chunk_id": h["chunk_id"],
                "doc_id": c["doc_id"],
                "doc_name": c["filename"],
                "kb_id": c["kb_id"],
                "score": round(float(h.get("score", 0)), 4),
                "text": c["text"][:200],
            }
        )
    return out
