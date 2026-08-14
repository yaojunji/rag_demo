"""OpenAI 兼容接口：外部系统可用标准 OpenAI SDK 调用知识库 RAG 问答。

- POST /v1/chat/completions：自动 RAG 检索 + 生成，返回标准 OpenAI 格式，
  assistant message 附带 citations 扩展字段（引用列表，标准客户端会忽略）
- GET /v1/models：列出可用的对话模型

认证：Authorization: Bearer <API Token>（由管理员在系统管理创建）
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as OrmSession

from app.core.config import settings
from app.db.base import get_db
from app.models import ApiToken, KnowledgeBase, User
from app.rag.llm import chat_sync, llm_client
from app.rag.pipeline import (
    _audit_citations,
    _filter_by_marked,
    _finalize_citations,
    _format_context,
    build_messages,
)
from app.rag.retriever import retrieve

router = APIRouter(prefix="/v1", tags=["OpenAI 兼容接口"])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _authenticate(request: Request, db: OrmSession) -> tuple[ApiToken, User]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")
    token = auth[7:].strip()
    if len(token) < 16:
        raise HTTPException(status_code=401, detail="无效的 Token")
    record = db.query(ApiToken).filter(ApiToken.token_hash == _hash_token(token)).first()
    if not record or not record.is_active:
        raise HTTPException(status_code=401, detail="Token 无效或已停用")
    user = db.get(User, record.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="绑定用户不可用")
    record.last_used_at = __import__("datetime").datetime.utcnow()
    db.commit()
    return record, user


def _resolve_kbs(record: ApiToken, user: User, db: OrmSession) -> List[KnowledgeBase]:
    """解析 Token 允许检索的知识库（token 指定优先，否则该用户可见的全部库）。"""
    if record.kb_ids:
        return [k for k in (db.get(KnowledgeBase, kid) for kid in record.kb_ids) if k]
    from app.api.deps import kb_visible

    return [k for k in db.query(KnowledgeBase).order_by(KnowledgeBase.id).all() if kb_visible(k, user)]


@router.post("/chat/completions", summary="RAG 问答（OpenAI 兼容，支持流式）")
async def chat_completions(request: Request, db: OrmSession = Depends(get_db)):
    record, user = _authenticate(request, db)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="请求体必须是 JSON")

    stream = bool(body.get("stream"))
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    user_msgs = [m for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)]
    if not user_msgs:
        raise HTTPException(status_code=400, detail="需要至少一条 user 消息")
    query = user_msgs[-1]["content"][:4000]
    history = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in messages[:-1]
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
    ][-12:]

    model = body.get("model") or None
    kbs = _resolve_kbs(record, user, db)
    if not kbs:
        raise HTTPException(status_code=400, detail="该 Token 没有可访问的知识库")
    main_kb = kbs[0]
    extra_ids = [k.id for k in kbs[1:]]

    # 检索（与 Web 问答同一套 RAG 链路）
    qv = llm_client.embed([query], model=main_kb.embed_model or None)[0]
    try:
        result = retrieve(
            kb_id=main_kb.id,
            query=query,
            query_vector=qv,
            top_k=body.get("top_k", 8) if isinstance(body.get("top_k"), int) else 8,
            db=db,
            extra_kb_ids=extra_ids or None,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"检索失败: {e}")
    chunks = result["chunks"]
    messages_for_llm = build_messages(query, chunks, history, main_kb.name)

    def chunk_obj(delta: str, finish: str | None = None) -> str:
        import json as _json

        payload = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model or settings.llm_models[0],
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": delta} if delta else {},
                    "finish_reason": finish,
                }
            ],
        }
        return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"

    if stream:
        from fastapi.responses import StreamingResponse

        async def gen():
            try:
                async for delta, used_model in llm_client.astream_chat(
                    messages_for_llm,
                    temperature=body.get("temperature"),
                    max_tokens=body.get("max_tokens"),
                    model=model,
                ):
                    yield chunk_obj(delta)
                yield chunk_obj("", "stop")
            except Exception as e:  # noqa: BLE001
                yield f"data: {json.dumps({'error': {'message': str(e)}}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    try:
        answer, used_model = chat_sync(
            messages_for_llm,
            temperature=body.get("temperature"),
            max_tokens=body.get("max_tokens"),
            model=model,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"模型调用失败: {e}")

    # 引用：审计 + 正文标注过滤（与 Web 一致）
    _, citations = _format_context(chunks)
    indexed = [dict(c, _idx=i + 1) for i, c in enumerate(citations)]
    if settings.ENABLE_CITATION_AUDIT:
        indexed = _audit_citations(query, answer, indexed)
    final = _finalize_citations(_filter_by_marked(answer, indexed))

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": used_model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": answer,
                    "citations": final,  # 自定义扩展字段，标准客户端忽略
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@router.get("/models", summary="列出可用对话模型")
def list_models(request: Request, db: OrmSession = Depends(get_db)):
    _authenticate(request, db)
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "created": now, "owned_by": "knowhub"}
            for m in settings.llm_models
        ],
    }
