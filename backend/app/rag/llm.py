"""LLM 客户端：OpenAI 兼容网关封装。

- 对话：同步 chat() 与异步流式 astream_chat()，按配置的模型列表自动降级
- 向量化：embed()，批量 + 模型降级
- 所有调用带超时与重试
"""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator, List, Optional

from openai import AsyncOpenAI, OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMClient:
    """OpenAI 兼容网关客户端（线程内懒加载同步/异步实例）。"""

    def __init__(self) -> None:
        self._client: Optional[OpenAI] = None
        self._aclient: Optional[AsyncOpenAI] = None
        self._chat_model: Optional[str] = None
        self._embed_model: Optional[str] = None
        self._gateway = settings.llm_base_url

    # ---------------- 内部 ----------------
    def _sync(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=self._gateway,
                timeout=settings.LLM_TIMEOUT,
                max_retries=settings.LLM_RETRIES,
            )
        return self._client

    def _async(self) -> AsyncOpenAI:
        if self._aclient is None:
            self._aclient = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=self._gateway,
                timeout=settings.LLM_TIMEOUT,
                max_retries=settings.LLM_RETRIES,
            )
        return self._aclient

    # ---------------- 对话 ----------------
    def chat(
        self,
        messages: List[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> tuple[str, str]:
        """返回 (content, 实际使用的模型)。主模型失败自动降级。"""
        models = [model] if model else settings.llm_models
        errors: list[str] = []
        for m in models:
            try:
                resp = self._sync().chat.completions.create(
                    model=m,
                    messages=messages,
                    temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
                    max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
                    timeout=timeout or settings.LLM_TIMEOUT,
                )
                self._chat_model = m
                return resp.choices[0].message.content or "", m
            except Exception as e:  # noqa: BLE001
                errors.append(f"{m}: {e}")
                logger.warning("chat model %s failed: %s", m, e)
        raise LLMError("所有对话模型均失败: " + " | ".join(errors))

    async def astream_chat(
        self,
        messages: List[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[tuple[str, str]]:
        """流式对话：产出 (增量文本, 模型名)，首个 chunk 携带模型名。"""
        models = [model] if model else settings.llm_models
        errors: list[str] = []
        for m in models:
            try:
                stream = await self._async().chat.completions.create(
                    model=m,
                    messages=messages,
                    temperature=temperature if temperature is not None else settings.LLM_TEMPERATURE,
                    max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
                    stream=True,
                )
                self._chat_model = m
                yielded = False
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        delta = chunk.choices[0].delta.content
                        if not yielded:
                            yield delta, m
                            yielded = True
                        else:
                            yield delta, m
                if not yielded:
                    yield "", m
                return
            except Exception as e:  # noqa: BLE001
                errors.append(f"{m}: {e}")
                logger.warning("stream chat model %s failed: %s", m, e)
        raise LLMError("所有对话模型均失败: " + " | ".join(errors))

    # ---------------- 向量化 ----------------
    def embed(self, texts: List[str], model: Optional[str] = None) -> list[list[float]]:
        """批量向量化。

        模型顺序：指定模型优先，失败后自动降级到配置中的其它向量模型（去重）。
        调用成功后记录 active_embed_model，供上层同步 KB 实际模型。
        """
        models = [model] if model else settings.embed_models
        # 指定模型失败后追加其余配置模型兜底
        ordered = []
        for m in models:
            if m and m not in ordered:
                ordered.append(m)
        for m in settings.embed_models:
            if m and m not in ordered:
                ordered.append(m)
        if not texts:
            return []
        errors: list[str] = []
        for m in ordered:
            try:
                vectors: list[list[float]] = []
                for i in range(0, len(texts), settings.EMBEDDING_BATCH_SIZE):
                    batch = texts[i : i + settings.EMBEDDING_BATCH_SIZE]
                    resp = self._sync().embeddings.create(model=m, input=batch)
                    vectors.extend([d.embedding for d in resp.data])
                self._embed_model = m
                return vectors
            except Exception as e:  # noqa: BLE001
                errors.append(f"{m}: {e}")
                logger.warning("embed model %s failed: %s", m, e)
        raise LLMError("所有向量化模型均失败: " + " | ".join(errors))

    # ---------------- 状态 ----------------
    @property
    def gateway(self) -> str:
        return self._gateway

    @property
    def active_chat_model(self) -> str:
        return self._chat_model or (settings.llm_models[0] if settings.llm_models else "unknown")

    @property
    def active_embed_model(self) -> str:
        return self._embed_model or (settings.embed_models[0] if settings.embed_models else "unknown")

    def timed(self, fn, *a, **kw):
        start = time.perf_counter()
        out = fn(*a, **kw)
        return out, (time.perf_counter() - start) * 1000


llm_client = LLMClient()


def _as_messages(history: list[dict]) -> List[dict]:
    """规范化消息列表，丢弃非法角色。"""
    out: List[dict] = []
    for h in history:
        role = h.get("role")
        content = h.get("content")
        if role in ("system", "user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    return out[-20:]  # 控制上下文长度


# 供外部使用的便捷函数
def chat_sync(messages: List[dict], **kw) -> tuple[str, str]:
    return llm_client.chat(messages, **kw)


def embed_texts(texts: List[str], model: Optional[str] = None) -> list[list[float]]:
    return llm_client.embed(texts, model=model)
