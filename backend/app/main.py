"""KnowHub(知枢) 应用入口。

启动流程：建表 → 初始化 FTS 索引 → 种子管理员 → 恢复中断任务。
开发模式下若存在前端构建产物则一并托管（生产请用 Docker/nginx）。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import PROJECT_ROOT, settings
from app.db.base import SessionLocal, init_db
from app.models import Document, Tenant, User
from app.core.security import hash_password

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("knowhub")
# 附加环形缓冲 handler（管理端日志页）
from app.core.logging_ring import ring_handler  # noqa: E402

logging.getLogger().addHandler(ring_handler)


def seed_admin() -> None:
    """首次启动创建默认租户与超级管理员。"""
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.role == "admin").first():
            tenant = db.query(Tenant).filter(Tenant.name == "默认租户").first()
            if not tenant:
                tenant = Tenant(name="默认租户", description="系统默认租户")
                db.add(tenant)
                db.flush()
            if not db.query(User).filter(User.username == settings.ADMIN_USERNAME).first():
                db.add(
                    User(
                        username=settings.ADMIN_USERNAME,
                        password_hash=hash_password(settings.ADMIN_PASSWORD),
                        display_name="超级管理员",
                        role="admin",
                        tenant_id=tenant.id,
                    )
                )
                logger.info("已创建超级管理员: %s", settings.ADMIN_USERNAME)
        db.commit()
    finally:
        db.close()


def recover_interrupted() -> None:
    """重启后将中断的索引任务标记为失败。"""
    db = SessionLocal()
    try:
        n = (
            db.query(Document)
            .filter(Document.status.in_(["pending", "processing"]))
            .update(
                {
                    Document.status: "failed",
                    Document.error: "服务重启，索引任务中断，请点击「重建索引」重试",
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if n:
            logger.warning("恢复 %s 个中断的索引任务", n)
    finally:
        db.close()


async def _trash_cleanup_loop() -> None:
    """后台任务：定期清理回收站中超过保留期的文档（防数据堆积）。"""
    import asyncio as _asyncio

    from datetime import datetime, timedelta

    from sqlalchemy import text

    while True:
        try:
            if settings.TRASH_RETENTION_DAYS > 0:
                cutoff = datetime.utcnow() - timedelta(days=settings.TRASH_RETENTION_DAYS)
                from app.db.base import SessionLocal
                from app.models import Document

                db = SessionLocal()
                try:
                    expired = (
                        db.query(Document)
                        .filter(Document.deleted_at.isnot(None), Document.deleted_at < cutoff)
                        .all()
                    )
                    for doc in expired:
                        from app.services.ingestion import delete_document_artifacts

                        delete_document_artifacts(doc.kb_id, doc.id)
                        db.delete(doc)
                    if expired:
                        db.commit()
                        logger.info("回收站自动清理 %s 个过期文档（>%s 天）", len(expired), settings.TRASH_RETENTION_DAYS)
                finally:
                    db.close()
        except Exception:  # noqa: BLE001
            logger.exception("trash cleanup loop error")
        await _asyncio.sleep(24 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from app.rag.retriever import init_fts

    init_fts()
    if settings.AUTO_SEED_ADMIN:
        seed_admin()
    recover_interrupted()
    task = __import__("asyncio").create_task(_trash_cleanup_loop())
    logger.info(
        "KnowHub 启动完成 | 网关=%s | 对话模型=%s | 向量模型=%s",
        settings.llm_base_url,
        settings.llm_models,
        settings.embed_models,
    )
    yield
    task.cancel()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="企业级 RAG 知识库 Agent：多租户文档知识库、混合检索、带引用流式问答、RBAC、审计。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"服务器内部错误: {exc}"})


@app.get("/api/health", tags=["系统"], summary="健康检查")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


# ---------------- 路由 ----------------
from app.api import admin, auth, chat, documents, kbs, notifications, openai_compat  # noqa: E402

app.include_router(auth.router)
app.include_router(kbs.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(openai_compat.router)

# ---------------- 前端静态托管（构建产物存在时）----------------
_frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if _frontend_dist.exists():
    _assets = _frontend_dist / "assets"
    if _assets.exists():
        # 静态资源优先（须在 catch-all 之前注册）
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 深链回退：非 API 路径一律返回 index.html。"""
        if full_path.startswith("api/") or full_path.startswith("assets/"):
            raise HTTPException(status_code=404)
        return FileResponse(str(_frontend_dist / "index.html"))

    logger.info("已托管前端构建产物: %s", _frontend_dist)
else:
    logger.info("未发现前端构建产物（frontend/dist），仅提供 API 服务")
