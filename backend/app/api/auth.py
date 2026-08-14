"""认证路由：登录 / 注册 / 当前用户 / 修改密码。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import client_ip, get_current_user, rate_limit
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import get_db
from app.models import Tenant, User
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenOut,
    UserOut,
)
from app.services.audit import ACTION_LOGIN, ACTION_REGISTER, audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=TokenOut, summary="登录")
def login(body: LoginRequest, request: Request, db: OrmSession = Depends(get_db)):
    rate_limit(
        f"login:{body.username}:{client_ip(request)}",
        settings.RATE_LIMIT_LOGIN,
        settings.RATE_LIMIT_LOGIN_WINDOW,
    )
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    user.last_login_at = __import__("datetime").datetime.utcnow()
    db.commit()
    audit(db, user, ACTION_LOGIN, "auth", user.id, f"登录成功 IP={client_ip(request)}", client_ip(request))
    token = create_access_token(user.id, user.username, user.role, user.tenant_id)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenOut, summary="自助注册")
def register(body: RegisterRequest, request: Request, db: OrmSession = Depends(get_db)):
    if not settings.REGISTRATION_ENABLED:
        raise HTTPException(status_code=403, detail="注册功能已关闭，请联系管理员开通账号")
    rate_limit(
        f"register:{client_ip(request)}",
        settings.RATE_LIMIT_REGISTER,
        settings.RATE_LIMIT_REGISTER_WINDOW,
    )
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    # 新用户默认挂到默认租户（若有），角色为配置的默认角色（默认只读）
    tenant = db.query(Tenant).filter(Tenant.name == "默认租户").first()
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.username,
        role=settings.REGISTRATION_DEFAULT_ROLE,
        tenant_id=tenant.id if tenant else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit(
        db, user, ACTION_REGISTER, "user", user.id,
        f"自助注册（默认角色={user.role}）IP={client_ip(request)}", client_ip(request),
    )
    logger.info("新用户注册: %s (role=%s)", user.username, user.role)
    token = create_access_token(user.id, user.username, user.role, user.tenant_id)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="当前用户信息")
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/change-password", summary="修改密码")
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"detail": "密码已更新"}
