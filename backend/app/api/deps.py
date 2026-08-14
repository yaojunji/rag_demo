"""API 依赖：当前用户 / 角色权限 / 知识库作用域 / 限流。"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, List, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as OrmSession

from app.core.config import settings
from app.core.security import decode_token
from app.db.base import get_db
from app.models import KnowledgeBase, User

# ---------- 限流（内存令牌桶）----------
_buckets: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int, window: float = 60.0) -> None:
    now = time.monotonic()
    q = _buckets[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail=f"请求过于频繁，请稍后再试（{limit} 次/{int(window)}秒）")
    q.append(now)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


# ---------- 认证 ----------
def get_current_user(
    request: Request,
    db: OrmSession = Depends(get_db),
) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或令牌缺失")
    payload = decode_token(auth[7:].strip())
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")
    return user


def require_roles(*roles: str) -> Callable:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"需要角色: {'/'.join(roles)}")
        return user

    return checker


def require_admin(user: User = Depends(require_roles("admin"))) -> User:
    return user


# ---------- 知识库作用域 ----------
def kb_visible(kb: KnowledgeBase, user: User) -> bool:
    """可见性：管理员可见全部；全局库（tenant_id 为空）所有租户可见；其余仅本租户。"""
    if user.role == "admin":
        return True
    if kb.tenant_id is None:
        return True
    return kb.tenant_id == user.tenant_id


def get_kb_or_404(db: OrmSession, kb_id: int, user: User) -> KnowledgeBase:
    kb = db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not kb_visible(kb, user):
        raise HTTPException(status_code=403, detail="无权访问该知识库")
    return kb


def kb_scope(user: User) -> Optional[dict]:
    """非管理员只能访问本租户或全局资源。"""
    if user.role == "admin":
        return None
    return {"tenant_id": user.tenant_id}
