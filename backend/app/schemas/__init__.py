"""Pydantic 请求/响应模型。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------- 通用 ----------------
class Message(BaseModel):
    detail: str


class Page(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[Any]


# ---------------- 认证 ----------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=64)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: str
    tenant_id: Optional[int] = None
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=64)
    role: str = Field(default="viewer", pattern=r"^(admin|editor|viewer)$")
    tenant_id: Optional[int] = None


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=64)
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)
    role: Optional[str] = Field(default=None, pattern=r"^(admin|editor|viewer)$")
    is_active: Optional[bool] = None


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6, max_length=128)


# ---------------- 租户 ----------------
class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    created_at: datetime


# ---------------- 知识库 ----------------
class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    embed_model: str = ""
    chunk_size: int = Field(default=800, ge=100, le=4000)
    chunk_overlap: int = Field(default=120, ge=0, le=1000)
    welcome_questions: List[str] = Field(default_factory=list, max_length=8)


class KBUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = None
    embed_model: Optional[str] = None
    chunk_size: Optional[int] = Field(default=None, ge=100, le=4000)
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=1000)
    welcome_questions: Optional[List[str]] = Field(default=None, max_length=8)


class KBOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    tenant_id: Optional[int]
    embed_model: str
    chunk_size: int
    chunk_overlap: int
    doc_count: int
    chunk_count: int
    welcome_questions: List[str] = []
    created_at: datetime
    updated_at: datetime

    @field_validator("welcome_questions", mode="before")
    @classmethod
    def _parse_welcome(cls, v):
        """DB 存 JSON 字符串，自动解析为数组。"""
        if isinstance(v, str):
            try:
                return json.loads(v) if v else []
            except Exception:  # noqa: BLE001
                return []
        return v or []


# ---------------- 文档 ----------------
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kb_id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    progress: int
    error: str
    chunk_count: int
    sensitive_flags: str = ""
    created_by: int
    created_at: datetime
    updated_at: datetime


class ChunkOut(BaseModel):
    doc_id: int
    chunk_index: int
    content: str
    metadata: dict


# ---------------- 问答 ----------------
class ChatRequest(BaseModel):
    kb_id: int
    message: str = Field(min_length=1, max_length=8000)
    session_id: Optional[int] = None
    history: List[dict] = Field(default_factory=list)  # [{role, content}]
    top_k: int = Field(default=8, ge=1, le=20)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    # 联合检索的其他知识库（可选）：一次提问跨多个库
    kb_ids: Optional[List[int]] = None


class Citation(BaseModel):
    doc_id: int
    doc_name: str
    chunk_index: int
    score: float
    snippet: str
    page: Optional[int] = None
    kb_id: Optional[int] = None


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    kb_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int
    role: str
    content: str
    citations: Optional[List[Citation]]
    model: str
    latency_ms: int
    created_at: datetime


# ---------------- 回答反馈 ----------------
class FeedbackCreate(BaseModel):
    rating: str = Field(pattern=r"^(up|down)$")
    comment: str = Field(default="", max_length=500)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    message_id: int
    session_id: int
    user_id: int
    kb_id: Optional[int]
    rating: str
    comment: str
    created_at: datetime


class FeedbackStats(BaseModel):
    up: int
    down: int
    total: int
    up_rate: float
    by_kb: List[dict]
    by_user: List[dict]


# ---------------- 检索调试 ----------------
class RagDebugRequest(BaseModel):
    kb_id: int
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)


class DebugHit(BaseModel):
    chunk_id: int
    doc_id: Optional[int] = None
    doc_name: str = ""
    score: float
    text: str = ""


class RagDebugOut(BaseModel):
    query: str
    embed_model: str
    timings_ms: dict
    vector_hits: List[DebugHit]
    keyword_hits: List[DebugHit]
    fused_hits: List[DebugHit]
    reranked_hits: List[DebugHit]
    final_hits: List[DebugHit]


# ---------------- 仪表盘 ----------------
class DashboardPoint(BaseModel):
    date: str
    count: int


class DashboardOut(BaseModel):
    totals: SystemStats
    chat_trend: List[DashboardPoint]
    doc_trend: List[DashboardPoint]
    kb_stats: List[dict]
    feedback: FeedbackStats
    top_questions: List[dict]


# ---------------- 审计 ----------------
class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: Optional[int]
    username: str
    tenant_id: Optional[int]
    action: str
    resource_type: str
    resource_id: str
    detail: str
    ip: str
    created_at: datetime


# ---------------- 系统 ----------------
class SystemStats(BaseModel):
    tenants: int
    users: int
    knowledge_bases: int
    documents: int
    chunks: int
    chat_messages: int
    audit_logs: int
    llm_model: str
    embed_model: str
    gateway: str
    vector_store: str
    version: str


class TaskOut(BaseModel):
    doc_id: int
    status: str
    progress: int
    error: str


class RAGConfigOut(BaseModel):
    llm_models: List[str]
    embed_models: List[str]
    gateway: str
    chunk_size: int
    chunk_overlap: int
    retrieve_top_k: int
    rerank_top_k: int
    enable_rerank: bool
    enable_hybrid: bool
    max_upload_mb: int
    default_llm_model: str
    default_embed_model: str
