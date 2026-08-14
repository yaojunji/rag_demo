"""问答路由：SSE 流式 RAG 问答 / 反馈 / 会话管理 / 历史消息。"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import client_ip, get_current_user, get_kb_or_404, kb_visible, rate_limit
from app.core.config import settings
from app.db.base import get_db
from app.models import ChatMessage, ChatSession, KnowledgeBase, MessageFeedback, User
from app.schemas import (
    ChatMessageOut,
    ChatRequest,
    ChatSessionOut,
    FeedbackCreate,
    FeedbackOut,
)
from app.services.audit import ACTION_CHAT, audit
from app.services.chat import answer_stream, load_history

router = APIRouter(prefix="/api/chat", tags=["问答"])


@router.post("/ask", summary="流式 RAG 问答（SSE，支持多知识库）")
async def ask(
    body: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    rate_limit(f"chat:{user.id}", settings.RATE_LIMIT_CHAT_PER_MIN, 60)
    kb = get_kb_or_404(db, body.kb_id, user)
    # 联合检索库（可选）：校验可见性
    extra_ids: list[int] = []
    for kid in body.kb_ids or []:
        if kid == body.kb_id:
            continue
        other = db.get(KnowledgeBase, kid)
        if not other or not kb_visible(other, user):
            raise HTTPException(status_code=403, detail=f"无权访问知识库 #{kid}")
        extra_ids.append(kid)
    history = load_history(db, body.session_id) if body.session_id else (body.history or [])

    async def gen():
        try:
            async for ev in answer_stream(
                db=db,
                user=user,
                kb_id=kb.id,
                kb_name=kb.name,
                message=body.message,
                history=history,
                top_k=body.top_k,
                temperature=body.temperature,
                session_id=body.session_id,
                kb_embed_model=kb.embed_model,
                extra_kb_ids=extra_ids or None,
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            audit(
                db, user, ACTION_CHAT, "chat", body.kb_id,
                f"问: {body.message[:80]}", client_ip(request),
            )

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ---------------- 回答反馈 ----------------
@router.post("/messages/{message_id}/feedback", response_model=FeedbackOut, summary="回答反馈（赞/踩，幂等）")
def submit_feedback(
    message_id: int,
    body: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    msg = db.get(ChatMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    session = db.get(ChatSession, msg.session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作该消息")
    fb = (
        db.query(MessageFeedback)
        .filter(MessageFeedback.message_id == message_id, MessageFeedback.user_id == user.id)
        .first()
    )
    if fb:
        fb.rating = body.rating
        fb.comment = body.comment
        fb.kb_id = session.kb_id
    else:
        fb = MessageFeedback(
            message_id=message_id,
            session_id=session.id,
            user_id=user.id,
            kb_id=session.kb_id,
            rating=body.rating,
            comment=body.comment,
        )
        db.add(fb)
    db.commit()
    db.refresh(fb)
    return FeedbackOut.model_validate(fb)


# ---------------- 会话管理 ----------------
@router.get("/sessions", response_model=list[ChatSessionOut], summary="我的会话列表")
def list_sessions(
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(100)
        .all()
    )
    return [ChatSessionOut.model_validate(s) for s in rows]


@router.patch("/sessions/{session_id}", response_model=ChatSessionOut, summary="重命名会话")
def rename_session(
    session_id: int,
    body: dict,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    s = db.get(ChatSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    title = (body.get("title") or "").strip()
    if not title or len(title) > 100:
        raise HTTPException(status_code=400, detail="标题不合法")
    s.title = title
    db.commit()
    db.refresh(s)
    return ChatSessionOut.model_validate(s)


@router.get("/sessions/{session_id}/export", summary="导出会话（markdown/json）")
def export_session(
    session_id: int,
    format: str = Query("markdown", pattern=r"^(markdown|json)$"),
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    s = db.get(ChatSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
        .all()
    )
    kb_name = db.get(KnowledgeBase, s.kb_id).name if s.kb_id and db.get(KnowledgeBase, s.kb_id) else "全部"
    if format == "json":
        payload = {
            "session_id": s.id,
            "title": s.title,
            "kb": kb_name,
            "exported_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "citations": m.citations,
                    "suggested": m.suggested,
                    "model": m.model,
                    "created_at": m.created_at.isoformat(),
                }
                for m in rows
            ],
        }
        return JSONResponse(
            content=payload,
            headers={"Content-Disposition": f'attachment; filename="session_{session_id}.json"'},
        )
    # Markdown 导出
    lines = [
        f"# {s.title}",
        "",
        f"> 知识库：{kb_name} ｜ 导出时间：{__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
        "",
        "---",
        "",
    ]
    for m in rows:
        if m.role == "user":
            lines += ["## 🙋 用户", "", m.content, ""]
        else:
            lines += ["## 🤖 AI", "", m.content, ""]
            if m.citations:
                lines += ["", "**引用来源：**", ""]
                for c in m.citations:
                    page = f"（第 {c.get('page')} 页）" if c.get("page") else ""
                    lines.append(f"- 《{c.get('doc_name', '?')}》{page}")
            if m.suggested:
                lines += ["", "**可以追问：**", ""]
                for q in m.suggested:
                    lines.append(f"- {q}")
            lines += ["", "---", ""]
    text = "\n".join(lines)
    from urllib.parse import quote

    from fastapi.responses import PlainTextResponse

    safe = s.title.replace("/", "_").replace("\\", "_")[:60]
    fname = f"session_{session_id}_{safe}.md"
    disposition = f"attachment; filename=\"session_{session_id}.md\"; filename*=UTF-8''{quote(fname)}"
    return PlainTextResponse(
        content=text,
        headers={"Content-Disposition": disposition},
    )


@router.delete("/sessions/{session_id}", summary="删除会话")
def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    s = db.get(ChatSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(s)
    db.commit()
    return {"detail": "会话已删除"}


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut], summary="会话消息")
def session_messages(
    session_id: int,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    s = db.get(ChatSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
        .all()
    )
    return [ChatMessageOut.model_validate(m) for m in rows]
