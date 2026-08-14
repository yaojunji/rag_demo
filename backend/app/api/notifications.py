"""站内通知：索引完成/失败、系统消息。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import Notification, User

router = APIRouter(prefix="/api/notifications", tags=["通知"])


@router.get("", summary="我的通知列表")
def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    rows = q.order_by(Notification.id.desc()).limit(min(limit, 100)).all()
    return [
        {
            "id": n.id,
            "ntype": n.ntype,
            "title": n.title,
            "content": n.content,
            "is_read": n.is_read,
            "created_at": n.created_at,
        }
        for n in rows
    ]


@router.get("/unread-count", summary="未读数")
def unread_count(
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    from sqlalchemy import func

    cnt = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .scalar()
        or 0
    )
    return {"count": cnt}


@router.post("/{notification_id}/read", summary="标记已读")
def mark_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="通知不存在")
    n.is_read = True
    db.commit()
    return {"detail": "ok"}


@router.post("/read-all", summary="全部已读")
def mark_all_read(
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read.is_(False)).update(
        {Notification.is_read: True}, synchronize_session=False
    )
    db.commit()
    return {"detail": "ok"}
