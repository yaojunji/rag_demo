"""SQLAlchemy 引擎与会话（同步 + SQLite/PostgreSQL 可切换）。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.db_url
    if url.startswith("sqlite"):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
        )
        # WAL 模式：读写并发友好；busy_timeout 30s 兜底锁等待
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """建表（幂等）+ 轻量列迁移。"""
    import app.models  # noqa: F401  确保模型全部注册

    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def _migrate_columns() -> None:
    """SQLite 追加新列（create_all 不会给已有表加列）。"""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("documents")}
    if "file_hash" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE documents ADD COLUMN file_hash VARCHAR(64) DEFAULT ''"))
        import logging

        logging.getLogger(__name__).info("migrated: documents.file_hash")
    if "sensitive_flags" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE documents ADD COLUMN sensitive_flags VARCHAR(255) DEFAULT ''"))
        import logging

        logging.getLogger(__name__).info("migrated: documents.sensitive_flags")
    kb_cols = {c["name"] for c in insp.get_columns("knowledge_bases")}
    if "welcome_questions" not in kb_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN welcome_questions TEXT DEFAULT '[]'"))
        import logging

        logging.getLogger(__name__).info("migrated: knowledge_bases.welcome_questions")
    doc_cols = {c["name"] for c in insp.get_columns("documents")}
    if "deleted_at" not in doc_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE documents ADD COLUMN deleted_at DATETIME"))
        import logging

        logging.getLogger(__name__).info("migrated: documents.deleted_at")
    msg_cols = {c["name"] for c in insp.get_columns("chat_messages")}
    if "suggested" not in msg_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN suggested TEXT"))
        import logging

        logging.getLogger(__name__).info("migrated: chat_messages.suggested")


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务作用域：正常提交，异常回滚。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db():
    """FastAPI 依赖：请求级会话。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
