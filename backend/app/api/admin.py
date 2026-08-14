"""管理路由（仅 admin）：用户 / 租户 / 审计日志 / 系统统计 / 运行配置。"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session as OrmSession

from app.tasks.manager import task_manager
from app.services.ingestion import ingest_document

logger = logging.getLogger(__name__)

from app.api.deps import client_ip, require_admin
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import engine, get_db
from app.models import ApiToken, AuditLog, ChatMessage, Chunk, Document, KnowledgeBase, MessageFeedback, Tenant, User
from app.schemas import (
    AuditOut,
    DashboardOut,
    FeedbackOut,
    FeedbackStats,
    Page,
    RAGConfigOut,
    RagDebugOut,
    RagDebugRequest,
    SystemStats,
    TenantCreate,
    TenantOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.audit import (
    ACTION_TENANT_CREATE,
    ACTION_TENANT_DELETE,
    ACTION_USER_CREATE,
    ACTION_USER_DELETE,
    ACTION_USER_UPDATE,
    audit,
)
from app.rag.llm import llm_client
from app.rag.vector_store import vector_store

router = APIRouter(prefix="/api/admin", tags=["系统管理"])


# ---------------- 用户 ----------------
@router.get("/users", response_model=list[UserOut], summary="用户列表")
def list_users(
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    return [UserOut.model_validate(u) for u in db.query(User).order_by(User.id).all()]


@router.post("/users", response_model=UserOut, summary="创建用户")
def create_user(
    body: UserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if body.tenant_id:
        if not db.get(Tenant, body.tenant_id):
            raise HTTPException(status_code=400, detail="租户不存在")
    u = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
        tenant_id=body.tenant_id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    audit(db, admin, ACTION_USER_CREATE, "user", u.id, f"创建用户「{u.username}」角色={u.role}", client_ip(request))
    return UserOut.model_validate(u)


@router.put("/users/{user_id}", response_model=UserOut, summary="更新用户")
def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.id == admin.id and body.is_active is False:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    data = body.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        u.password_hash = hash_password(data.pop("password"))
    for k, v in data.items():
        if v is not None:
            setattr(u, k, v)
    db.commit()
    db.refresh(u)
    audit(db, admin, ACTION_USER_UPDATE, "user", u.id, f"更新用户「{u.username}」", client_ip(request))
    return UserOut.model_validate(u)


@router.delete("/users/{user_id}", summary="删除用户")
def delete_user(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    name = u.username
    db.delete(u)
    db.commit()
    audit(db, admin, ACTION_USER_DELETE, "user", user_id, f"删除用户「{name}」", client_ip(request))
    return {"detail": "用户已删除"}


# ---------------- 租户 ----------------
@router.get("/tenants", response_model=list[TenantOut], summary="租户列表")
def list_tenants(
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    return [TenantOut.model_validate(t) for t in db.query(Tenant).order_by(Tenant.id).all()]


@router.post("/tenants", response_model=TenantOut, summary="创建租户")
def create_tenant(
    body: TenantCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    if db.query(Tenant).filter(Tenant.name == body.name).first():
        raise HTTPException(status_code=400, detail="租户名已存在")
    t = Tenant(name=body.name, description=body.description)
    db.add(t)
    db.commit()
    db.refresh(t)
    audit(db, admin, ACTION_TENANT_CREATE, "tenant", t.id, f"创建租户「{t.name}」", client_ip(request))
    return TenantOut.model_validate(t)


@router.delete("/tenants/{tenant_id}", summary="删除租户（需先清空其用户与知识库）")
def delete_tenant(
    tenant_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="租户不存在")
    n_users = db.query(User).filter(User.tenant_id == tenant_id).count()
    n_kbs = db.query(KnowledgeBase).filter(KnowledgeBase.tenant_id == tenant_id).count()
    if n_users or n_kbs:
        raise HTTPException(status_code=400, detail=f"租户下仍有 {n_users} 个用户、{n_kbs} 个知识库，请先清理")
    db.delete(t)
    db.commit()
    audit(db, admin, ACTION_TENANT_DELETE, "tenant", tenant_id, f"删除租户「{t.name}」", client_ip(request))
    return {"detail": "租户已删除"}


# ---------------- 审计 ----------------
@router.get("/audit-logs", response_model=Page, summary="审计日志（分页）")
def list_audit(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = None,
    username: str | None = None,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if username:
        q = q.filter(AuditLog.username.like(f"%{username}%"))
    total = q.count()
    rows = q.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return Page(
        total=total,
        page=page,
        page_size=page_size,
        items=[AuditOut.model_validate(r).model_dump() for r in rows],
    )


# ---------------- 回答反馈管理 ----------------
@router.get("/feedback", response_model=Page, summary="反馈列表（分页）")
def list_feedback(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    rating: str | None = None,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    q = db.query(MessageFeedback)
    if rating:
        q = q.filter(MessageFeedback.rating == rating)
    total = q.count()
    rows = q.order_by(MessageFeedback.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    # 附上消息内容与提问
    items = []
    msg_cache: dict[int, ChatMessage] = {}
    for fb in rows:
        msg = msg_cache.get(fb.message_id) or db.get(ChatMessage, fb.message_id)
        if msg:
            msg_cache[fb.message_id] = msg
        items.append(
            {
                **FeedbackOut.model_validate(fb).model_dump(),
                "answer": (msg.content[:200] if msg else ""),
            }
        )
    return Page(total=total, page=page, page_size=page_size, items=items)


@router.get("/feedback/stats", response_model=FeedbackStats, summary="反馈统计")
def feedback_stats(
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    up = db.query(func.count(MessageFeedback.id)).filter(MessageFeedback.rating == "up").scalar() or 0
    down = db.query(func.count(MessageFeedback.id)).filter(MessageFeedback.rating == "down").scalar() or 0
    total = up + down
    by_kb = []
    for kb_id, cnt in (
        db.query(MessageFeedback.kb_id, func.count(MessageFeedback.id))
        .group_by(MessageFeedback.kb_id)
        .all()
    ):
        name = db.get(KnowledgeBase, kb_id).name if kb_id and db.get(KnowledgeBase, kb_id) else "未知"
        by_kb.append({"kb_id": kb_id, "kb_name": name, "count": cnt})
    by_user = []
    for user_id, cnt in (
        db.query(MessageFeedback.user_id, func.count(MessageFeedback.id))
        .group_by(MessageFeedback.user_id)
        .order_by(func.count(MessageFeedback.id).desc())
        .limit(8)
        .all()
    ):
        u = db.get(User, user_id)
        by_user.append({"user_id": user_id, "username": u.username if u else "?", "count": cnt})
    return FeedbackStats(
        up=up,
        down=down,
        total=total,
        up_rate=round(up / total * 100, 1) if total else 0.0,
        by_kb=by_kb,
        by_user=by_user,
    )


# ---------------- RAG 检索调试 ----------------
@router.post("/rag-debug", response_model=RagDebugOut, summary="检索链路调试（分步可视化）")
def rag_debug(
    body: RagDebugRequest,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    kb = db.get(KnowledgeBase, body.kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    from app.rag.llm import llm_client
    from app.rag.retriever import retrieve

    qv = llm_client.embed([body.query], model=kb.embed_model or None)[0]
    result = retrieve(
        kb_id=body.kb_id,
        query=body.query,
        query_vector=qv,
        top_k=body.top_k,
        db=db,
        debug=True,
    )
    debug = result.get("debug", {})
    return RagDebugOut(
        query=body.query,
        embed_model=debug.get("embed_model", ""),
        timings_ms=result["timings_ms"],
        vector_hits=debug.get("vector_hits", []),
        keyword_hits=debug.get("keyword_hits", []),
        fused_hits=debug.get("fused_hits", []),
        reranked_hits=debug.get("reranked_hits", []),
        final_hits=debug.get("final_hits", []),
    )


# ---------------- 仪表盘 ----------------
@router.get("/dashboard", response_model=DashboardOut, summary="仪表盘统计")
def dashboard(
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    from datetime import datetime, timedelta

    today = datetime.utcnow().date()
    days = 14
    start = today - timedelta(days=days - 1)

    def trend(model, col, start_dt):
        rows = (
            db.query(func.date(col), func.count(model.id))
            .filter(col >= start_dt)
            .group_by(func.date(col))
            .all()
        )
        m = {str(k): v for k, v in rows}
        return [{"date": str(start + timedelta(days=i)), "count": m.get(str(start + timedelta(days=i)), 0)} for i in range(days)]

    chat_trend = trend(ChatMessage, ChatMessage.created_at, start)
    doc_trend = trend(Document, Document.created_at, start)

    kb_stats = []
    for kb in db.query(KnowledgeBase).order_by(KnowledgeBase.chunk_count.desc()).limit(10).all():
        kb_stats.append(
            {
                "kb_id": kb.id,
                "kb_name": kb.name,
                "docs": kb.doc_count,
                "chunks": kb.chunk_count,
            }
        )

    top_questions = []
    for row in (
        db.query(ChatMessage.content, func.count(ChatMessage.id))
        .filter(ChatMessage.role == "user")
        .group_by(ChatMessage.content)
        .order_by(func.count(ChatMessage.id).desc())
        .limit(10)
        .all()
    ):
        top_questions.append({"question": row[0][:60], "count": row[1]})

    # 汇总统计
    def c(model):
        return db.query(func.count(model.id)).scalar() or 0

    totals = SystemStats(
        tenants=c(Tenant),
        users=c(User),
        knowledge_bases=c(KnowledgeBase),
        documents=c(Document),
        chunks=c(Chunk),
        chat_messages=c(ChatMessage),
        audit_logs=c(AuditLog),
        llm_model=llm_client.active_chat_model,
        embed_model=llm_client.active_embed_model,
        gateway=llm_client.gateway,
        vector_store=str(vector_store.stats()),
        version=settings.APP_VERSION,
    )

    up = db.query(func.count(MessageFeedback.id)).filter(MessageFeedback.rating == "up").scalar() or 0
    down = db.query(func.count(MessageFeedback.id)).filter(MessageFeedback.rating == "down").scalar() or 0
    fb = FeedbackStats(
        up=up,
        down=down,
        total=up + down,
        up_rate=round(up / (up + down) * 100, 1) if (up + down) else 0.0,
        by_kb=[],
        by_user=[],
    )
    return DashboardOut(
        totals=totals,
        chat_trend=chat_trend,
        doc_trend=doc_trend,
        kb_stats=kb_stats,
        feedback=fb,
        top_questions=top_questions,
    )


# ---------------- 内容检索（全文视图） ----------------
@router.get("/chunks/search", response_model=Page, summary="跨库内容检索（FTS）")
def search_chunks(
    q: str = Query("", max_length=200),
    kb_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    from sqlalchemy import text

    from app.rag.retriever import _segment

    if not q.strip():
        # 无关键词：按库浏览最新块
        query = db.query(Chunk)
        if kb_id:
            query = query.filter(Chunk.kb_id == kb_id)
        rows = (
            query.order_by(Chunk.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        total = (
            db.query(func.count(Chunk.id)).filter(Chunk.kb_id == kb_id).scalar()
            if kb_id
            else db.query(func.count(Chunk.id)).scalar()
        )
    else:
        tokens = _segment(q.strip())
        match_expr = " OR ".join(f'"{t}"' for t in tokens[:12])
        sql = text(
            """
            SELECT rowid AS chunk_id
            FROM chunk_fts
            WHERE chunk_fts MATCH :q {kb_filter}
            ORDER BY bm25(chunk_fts, 1.0, 1.0)
            LIMIT :lim OFFSET :off
            """
        )
        kb_filter = "AND kb_id = :kb" if kb_id else ""
        sql = text(str(sql).replace("{kb_filter}", kb_filter))
        params: dict = {"q": match_expr, "lim": page_size, "off": (page - 1) * page_size}
        if kb_id:
            params["kb"] = kb_id
        with engine.connect() as conn:
            hit_rows = conn.execute(sql, params).fetchall()
        total_sql = text(
            "SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH :q" + (" AND kb_id = :kb" if kb_id else "")
        )
        tparams: dict = {"q": match_expr}
        if kb_id:
            tparams["kb"] = kb_id
        with engine.connect() as conn:
            total = conn.execute(total_sql, tparams).scalar() or 0
        ids = [r.chunk_id for r in hit_rows]
        rows = db.query(Chunk).filter(Chunk.id.in_(ids)).all() if ids else []
        rows.sort(key=lambda c: ids.index(c.id))

    kb_names = {k.id: k.name for k in db.query(KnowledgeBase).all()}
    doc_names = {d.id: d.filename for d in db.query(Document).filter(Document.id.in_([r.doc_id for r in rows])).all()} if rows else {}
    items = []
    for r in rows:
        items.append(
            {
                "chunk_id": r.id,
                "kb_id": r.kb_id,
                "kb_name": kb_names.get(r.kb_id, "?"),
                "doc_id": r.doc_id,
                "doc_name": doc_names.get(r.doc_id, "?"),
                "chunk_index": r.chunk_index,
                "page": r.page,
                "section": r.section,
                "content": r.content,
            }
        )
    return Page(total=total or 0, page=page, page_size=page_size, items=items)


# ---------------- 模型自检 ----------------
@router.post("/model-check", summary="模型连通性自检（chat + embedding）")
def model_check(
    admin: User = Depends(require_admin),
):
    import time as _time

    from app.rag.llm import llm_client

    chat_results = []
    for m in settings.llm_models:
        t0 = _time.perf_counter()
        try:
            llm_client._sync().chat.completions.create(
                model=m,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                timeout=30,
            )
            chat_results.append({"model": m, "ok": True, "latency_ms": round((_time.perf_counter() - t0) * 1000), "error": ""})
        except Exception as e:  # noqa: BLE001
            chat_results.append({"model": m, "ok": False, "latency_ms": round((_time.perf_counter() - t0) * 1000), "error": str(e)[:200]})

    embed_results = []
    for m in settings.embed_models:
        t0 = _time.perf_counter()
        try:
            llm_client.embed(["连通性测试"], model=m)
            embed_results.append({"model": m, "ok": True, "latency_ms": round((_time.perf_counter() - t0) * 1000), "error": ""})
        except Exception as e:  # noqa: BLE001
            embed_results.append({"model": m, "ok": False, "latency_ms": round((_time.perf_counter() - t0) * 1000), "error": str(e)[:200]})

    return {
        "checked_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "gateway": settings.llm_base_url,
        "chat_models": chat_results,
        "embed_models": embed_results,
    }


# ---------------- API Token 管理（对外集成） ----------------
@router.get("/api-tokens", summary="API Token 列表")
def list_api_tokens(
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    rows = db.query(ApiToken).order_by(ApiToken.id.desc()).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "user_id": t.user_id,
            "username": (db.get(User, t.user_id).username if db.get(User, t.user_id) else "?"),
            "kb_ids": t.kb_ids or [],
            "is_active": t.is_active,
            "created_at": t.created_at,
            "last_used_at": t.last_used_at,
        }
        for t in rows
    ]


@router.post("/api-tokens", summary="创建 API Token（明文仅返回一次）")
def create_api_token(
    body: dict,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    name = (body.get("name") or "").strip()
    if not name or len(name) > 128:
        raise HTTPException(status_code=400, detail="名称必填且不超过 128 字")
    user_id = body.get("user_id") or admin.id
    if not db.get(User, user_id):
        raise HTTPException(status_code=400, detail="绑定的用户不存在")
    kb_ids = body.get("kb_ids") or []
    if not isinstance(kb_ids, list):
        raise HTTPException(status_code=400, detail="kb_ids 必须是数组")
    import secrets

    from app.models import ApiToken

    plain = "kh-" + secrets.token_urlsafe(32)
    t = ApiToken(
        name=name,
        token_hash=__import__("hashlib").sha256(plain.encode()).hexdigest(),
        user_id=user_id,
        kb_ids=kb_ids or None,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    audit(db, admin, "api_token.create", "api_token", t.id, f"创建 API Token「{name}」", client_ip(request))
    return {
        "id": t.id,
        "name": t.name,
        "token": plain,  # 仅此一次可见
        "is_active": t.is_active,
    }


@router.delete("/api-tokens/{token_id}", summary="删除 API Token")
def delete_api_token(
    token_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    t = db.get(ApiToken, token_id)
    if not t:
        raise HTTPException(status_code=404, detail="Token 不存在")
    name = t.name
    db.delete(t)
    db.commit()
    audit(db, admin, "api_token.delete", "api_token", token_id, f"删除 API Token「{name}」", client_ip(request))
    return {"detail": "已删除"}


@router.post("/api-tokens/{token_id}/toggle", summary="启停 API Token")
def toggle_api_token(
    token_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    t = db.get(ApiToken, token_id)
    if not t:
        raise HTTPException(status_code=404, detail="Token 不存在")
    t.is_active = not t.is_active
    db.commit()
    audit(db, admin, "api_token.toggle", "api_token", token_id, f"{'启用' if t.is_active else '停用'} Token「{t.name}」", client_ip(request))
    return {"id": t.id, "is_active": t.is_active}


# ---------------- 知识库导入（备份恢复） ----------------
@router.post("/kb-import", summary="导入知识库备份（JSON，恢复索引）")
async def import_kb(
    request: Request,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    from app.services.ingestion import import_kb_from_json

    try:
        content = await file.read()
        payload = json.loads(content.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"无效的备份文件: {e}")
    if not isinstance(payload, dict) or "knowledge_base" not in payload:
        raise HTTPException(status_code=400, detail="备份文件格式不正确（缺少 knowledge_base）")
    try:
        kb = import_kb_from_json(payload, admin.id)
    except Exception as e:  # noqa: BLE001
        logger.exception("kb import failed")
        raise HTTPException(status_code=400, detail=f"导入失败: {e}")
    audit(db, admin, "kb.import", "kb", kb.id, f"导入知识库「{kb.name}」({kb.doc_count} 文档 / {kb.chunk_count} 分块)", client_ip(request))
    return {"kb_id": kb.id, "name": kb.name, "doc_count": kb.doc_count, "chunk_count": kb.chunk_count}


# ---------------- 系统日志 ----------------
@router.get("/logs", summary="最近运行日志")
def system_logs(
    level: str = Query("INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    limit: int = Query(200, ge=1, le=1000),
    admin: User = Depends(require_admin),
):
    from app.core.logging_ring import ring_handler

    return {"items": ring_handler.snapshot(level=level, limit=limit)}


# ---------------- 知识库克隆 ----------------
@router.post("/kb-clone", summary="克隆知识库（配置 + 文档，重建索引）")
async def clone_kb(
    body: dict,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    import shutil

    source_id = body.get("source_kb_id")
    name = (body.get("name") or "").strip()
    src = db.get(KnowledgeBase, source_id) if source_id else None
    if not src:
        raise HTTPException(status_code=404, detail="源知识库不存在")
    if not name:
        name = src.name + "（克隆）"

    import json as _json

    kb = KnowledgeBase(
        name=name[:128],
        description=src.description,
        tenant_id=src.tenant_id,
        embed_model=src.embed_model,
        chunk_size=src.chunk_size,
        chunk_overlap=src.chunk_overlap,
        welcome_questions=src.welcome_questions or "[]",
        created_by=admin.id,
    )
    db.add(kb)
    db.flush()
    # 复制文档（文件复制到新库目录 + 重新索引）
    src_docs = db.query(Document).filter(Document.kb_id == src.id, Document.deleted_at.is_(None)).all()
    copied = 0
    for d in src_docs:
        p = Path(d.file_path)
        if not p.exists():
            continue
        kb_dir = settings.upload_dir / str(kb.id)
        kb_dir.mkdir(parents=True, exist_ok=True)
        new_path = kb_dir / f"{uuid.uuid4().hex}_{d.filename}"
        try:
            shutil.copy2(p, new_path)
        except OSError:
            continue
        new_doc = Document(
            kb_id=kb.id,
            filename=d.filename,
            file_path=str(new_path),
            file_type=d.file_type,
            file_size=d.file_size,
            file_hash=d.file_hash,
            status="pending",
            created_by=admin.id,
        )
        db.add(new_doc)
        db.flush()
        await task_manager.submit(new_doc.id, kb.id, ingest_document(new_doc.id))
        copied += 1
    db.commit()
    audit(db, admin, "kb.clone", "kb", kb.id, f"克隆知识库「{src.name}」→「{kb.name}」（{copied} 个文档）", client_ip(request))
    return {"kb_id": kb.id, "name": kb.name, "documents": copied}


# ---------------- 系统 ----------------
@router.get("/stats", response_model=SystemStats, summary="系统统计")
def stats(
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    def c(model):
        return db.query(func.count(model.id)).scalar() or 0

    return SystemStats(
        tenants=c(Tenant),
        users=c(User),
        knowledge_bases=c(KnowledgeBase),
        documents=c(Document),
        chunks=c(Chunk),
        chat_messages=c(ChatMessage),
        audit_logs=c(AuditLog),
        llm_model=llm_client.active_chat_model,
        embed_model=llm_client.active_embed_model,
        gateway=llm_client.gateway,
        vector_store=str(vector_store.stats()),
        version=settings.APP_VERSION,
    )


@router.get("/config", response_model=RAGConfigOut, summary="运行配置（RAG 参数）")
def rag_config(
    admin: User = Depends(require_admin),
):
    return RAGConfigOut(
        llm_models=settings.llm_models,
        embed_models=settings.embed_models,
        gateway=settings.llm_base_url,
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        retrieve_top_k=settings.RETRIEVE_TOP_K,
        rerank_top_k=settings.RERANK_TOP_K,
        enable_rerank=settings.ENABLE_RERANK,
        enable_hybrid=settings.ENABLE_HYBRID,
        max_upload_mb=settings.MAX_UPLOAD_MB,
        default_llm_model=settings.llm_models[0] if settings.llm_models else "",
        default_embed_model=settings.embed_models[0] if settings.embed_models else "",
    )
