"""知识库路由：创建 / 列表 / 详情 / 更新 / 删除。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import client_ip, get_current_user, get_kb_or_404, require_roles
from app.core.config import settings
from app.db.base import get_db
from app.models import KnowledgeBase, User
from app.schemas import KBCreate, KBOut, KBUpdate
from app.services.audit import ACTION_KB_CREATE, ACTION_KB_DELETE, ACTION_KB_UPDATE, audit
from app.services.ingestion import delete_kb_artifacts

router = APIRouter(prefix="/api/kbs", tags=["知识库"])


def _to_out(kb: KnowledgeBase) -> KBOut:
    return KBOut.model_validate(kb)


@router.post("", response_model=KBOut, summary="创建知识库")
def create_kb(
    body: KBCreate,
    request: Request,
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    kb = KnowledgeBase(
        name=body.name,
        description=body.description,
        tenant_id=user.tenant_id if user.role != "admin" else None,
        embed_model=body.embed_model or settings.EMBEDDING_MODEL,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        welcome_questions=json.dumps(body.welcome_questions, ensure_ascii=False),
        created_by=user.id,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    audit(db, user, ACTION_KB_CREATE, "kb", kb.id, f"创建知识库「{kb.name}」", client_ip(request))
    return _to_out(kb)


@router.get("", response_model=list[KBOut], summary="知识库列表")
def list_kbs(
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    q = db.query(KnowledgeBase)
    if user.role != "admin":
        # 全局库（tenant_id 为空）对所有租户可见 + 本租户库
        q = q.filter(
            or_(KnowledgeBase.tenant_id.is_(None), KnowledgeBase.tenant_id == user.tenant_id)
        )
    return [_to_out(kb) for kb in q.order_by(KnowledgeBase.id.desc()).all()]


@router.get("/{kb_id}", response_model=KBOut, summary="知识库详情")
def get_kb(
    kb_id: int,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    return _to_out(get_kb_or_404(db, kb_id, user))


@router.put("/{kb_id}", response_model=KBOut, summary="更新知识库")
def update_kb(
    kb_id: int,
    body: KBUpdate,
    request: Request,
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    kb = get_kb_or_404(db, kb_id, user)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None:
            continue
        if k == "welcome_questions":
            kb.welcome_questions = json.dumps(v, ensure_ascii=False)
        else:
            setattr(kb, k, v)
    db.commit()
    db.refresh(kb)
    audit(db, user, ACTION_KB_UPDATE, "kb", kb.id, f"更新知识库「{kb.name}」", client_ip(request))
    return _to_out(kb)


@router.delete("/{kb_id}", summary="删除知识库（含全部索引）")
def delete_kb(
    kb_id: int,
    request: Request,
    user: User = Depends(require_roles("admin", "editor")),
    db: OrmSession = Depends(get_db),
):
    kb = get_kb_or_404(db, kb_id, user)
    name = kb.name
    delete_kb_artifacts(kb_id)
    db.delete(kb)
    db.commit()
    audit(db, user, ACTION_KB_DELETE, "kb", kb_id, f"删除知识库「{name}」", client_ip(request))
    return {"detail": "知识库已删除"}
