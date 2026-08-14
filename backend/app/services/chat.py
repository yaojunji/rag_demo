"""聊天服务：会话/消息持久化 + 流式 RAG 回答。"""
from __future__ import annotations

import json
import time
from typing import AsyncIterator, Optional

from sqlalchemy.orm import Session as OrmSession

from app.models import ChatMessage, ChatSession, User
from app.rag.pipeline import stream_answer


def get_or_create_session(
    db: OrmSession,
    user: User,
    kb_id: int,
    session_id: Optional[int] = None,
) -> ChatSession:
    if session_id:
        s = db.get(ChatSession, session_id)
        if s and s.user_id == user.id:
            s.kb_id = kb_id
            db.commit()
            return s
    s = ChatSession(user_id=user.id, kb_id=kb_id)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def load_history(db: OrmSession, session_id: int, limit: int = 12) -> list[dict]:
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit * 2)
        .all()
    )
    out = []
    for m in reversed(msgs):
        out.append({"role": m.role, "content": m.content})
    return out


def save_message(
    db: OrmSession,
    session_id: int,
    role: str,
    content: str,
    citations: Optional[list] = None,
    model: str = "",
    latency_ms: int = 0,
    suggested: Optional[list] = None,
) -> ChatMessage:
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        citations=citations,
        suggested=suggested,
        model=model,
        latency_ms=latency_ms,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


async def answer_stream(
    db: OrmSession,
    user: User,
    kb_id: int,
    kb_name: str,
    message: str,
    history: list[dict],
    top_k: int = 8,
    temperature: Optional[float] = None,
    session_id: Optional[int] = None,
    kb_embed_model: Optional[str] = None,
    extra_kb_ids: Optional[list[int]] = None,
) -> AsyncIterator[dict]:
    """持久化问答的流式生成器；产出 pipeline 事件并在 done 时保存消息。"""
    session = get_or_create_session(db, user, kb_id, session_id)
    if len(message) > 60:
        session.title = message[:60] + "…"
    else:
        session.title = message
    db.commit()
    save_message(db, session.id, "user", message)

    start = time.perf_counter()
    full = ""
    model_name = ""
    citations: Optional[list] = None
    timings: Optional[dict] = None
    displayed = ""
    suggested: list[str] = []

    async for ev in stream_answer(
        query=message,
        kb_id=kb_id,
        kb_name=kb_name,
        history=history,
        top_k=top_k,
        temperature=temperature,
        db=db,
        kb_embed_model=kb_embed_model,
        extra_kb_ids=extra_kb_ids,
    ):
        if ev["type"] == "meta":
            citations = ev.get("citations") or []
            timings = ev.get("timings_ms")
            yield ev
        elif ev["type"] == "delta":
            full += ev["content"]
            model_name = ev.get("model", model_name)
            yield ev
        elif ev["type"] == "audit":
            # 引用审计结果：替换展示用引用
            citations = ev.get("citations") or citations or []
            yield ev
        elif ev["type"] == "masked":
            # 脱敏完成：后续展示/落库用脱敏版
            displayed = ev.get("content") or displayed
            yield ev
        elif ev["type"] == "suggest":
            suggested = ev.get("questions") or []
            yield ev
        elif ev["type"] == "done":
            latency = int((time.perf_counter() - start) * 1000)
            # 落库审计后的引用与脱敏内容（ev.citations 为审计结果）
            final_cites = ev.get("citations") or citations or []
            final_content = ev.get("content") or displayed or full
            msg = save_message(
                db,
                session.id,
                "assistant",
                final_content,
                citations=final_cites,
                suggested=ev.get("suggested") or suggested or None,
                model=model_name,
                latency_ms=latency,
            )
            yield {
                "type": "done",
                "session_id": session.id,
                "message_id": msg.id,
                "latency_ms": latency,
                "timings_ms": timings,
            }
        else:
            yield ev
