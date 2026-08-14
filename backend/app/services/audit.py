"""审计服务：统一落库所有敏感操作。"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session as OrmSession

from app.models import AuditLog, User

logger = logging.getLogger(__name__)

ACTION_LOGIN = "login"
ACTION_LOGOUT = "logout"
ACTION_REGISTER = "user.register"
ACTION_KB_CREATE = "kb.create"
ACTION_KB_UPDATE = "kb.update"
ACTION_KB_DELETE = "kb.delete"
ACTION_DOC_UPLOAD = "doc.upload"
ACTION_DOC_REINDEX = "doc.reindex"
ACTION_DOC_DELETE = "doc.delete"
ACTION_CHAT = "chat.ask"
ACTION_USER_CREATE = "user.create"
ACTION_USER_UPDATE = "user.update"
ACTION_USER_DELETE = "user.delete"
ACTION_TENANT_CREATE = "tenant.create"
ACTION_TENANT_DELETE = "tenant.delete"


def audit(
    db: OrmSession,
    user: Optional[User],
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    detail: str = "",
    ip: str = "",
) -> None:
    try:
        db.add(
            AuditLog(
                user_id=user.id if user else None,
                username=user.username if user else "anonymous",
                tenant_id=user.tenant_id if user else None,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id),
                detail=detail[:2000],
                ip=ip[:64],
            )
        )
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("audit write failed: %s", e)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
