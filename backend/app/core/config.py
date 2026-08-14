"""全局配置：从项目根目录 .env 加载（pydantic-settings）。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 应用 ----------
    APP_NAME: str = "KnowHub 知枢 · 企业级 RAG 知识库 Agent"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    # 允许跨域的前端地址（逗号分隔）
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000"

    # ---------- LLM 网关（OpenAI 兼容）----------
    LLM_API_KEY: str = ""
    # 支持两种写法：完整 chat 地址 或 网关 base（/v1）
    LLM_API_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    LLM_MODEL1: str = "qwen-max"
    LLM_MODEL2: str = "glm-5"
    LLM_MODEL3: str = ""
    LLM_MODEL4: str = "qwen3-coder-plus"
    LLM_MODEL5: str = "qwen-plus-0112"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 2048
    LLM_TIMEOUT: float = 120.0
    LLM_RETRIES: int = 2

    # ---------- Embedding ----------
    EMBEDDING_MODEL: str = "qwen3.7-text-embedding"
    EMBEDDING_MODEL1: str = "text-embedding-v3"
    EMBEDDING_BATCH_SIZE: int = 16

    # ---------- 存储路径 ----------
    DATA_DIR: str = str(PROJECT_ROOT / "data")
    UPLOAD_DIR: str = ""          # 默认 DATA_DIR/uploads
    VECTOR_DIR: str = ""          # 默认 DATA_DIR/vector_store
    DB_URL: str = ""              # 默认 sqlite:///DATA_DIR/knowhub.db

    # ---------- 认证 ----------
    JWT_SECRET: str = "knowhub-dev-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 720
    # 首次启动自动创建的超级管理员
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123456"
    # 自助注册（企业可关闭；注册用户默认只读角色，权限由管理员调整）
    REGISTRATION_ENABLED: bool = True
    REGISTRATION_DEFAULT_ROLE: str = "viewer"

    # ---------- RAG 参数 ----------
    CHUNK_SIZE: int = 800        # 默认切块大小（字符）
    CHUNK_OVERLAP: int = 120     # 默认重叠
    RETRIEVE_TOP_K: int = 12     # 混合检索候选数（融合）
    RERANK_TOP_K: int = 8        # 重排后送入 LLM 的块数
    ENABLE_RERANK: bool = True   # 是否启用 LLM 重排
    ENABLE_HYBRID: bool = True   # 是否启用 向量+关键词 混合检索
    # 生成后引用审计：LLM 校验回答实际依据的片段，剔除无关引用（增加约1-2s延迟）
    ENABLE_CITATION_AUDIT: bool = True
    # 回答脱敏：AI 回答中的手机号/身份证/银行卡/邮箱/IP/密钥自动打码（合规）
    ENABLE_ANSWER_MASKING: bool = True
    # 追问建议：回答后由 LLM 生成 3 个相关问题（增加约1-2s延迟）
    ENABLE_SUGGESTIONS: bool = True
    # 查询改写：多轮对话中的指代问题（"它/这个/上面"）结合历史改写后再检索
    ENABLE_QUERY_REWRITE: bool = True
    MAX_UPLOAD_MB: int = 50
    # 每个知识库的文档数上限（0 = 不限制）
    KB_MAX_DOCS: int = 0
    # 回收站自动清理：保留天数（0 = 不自动清理）
    TRASH_RETENTION_DAYS: int = 30

    # ---------- 限流 ----------
    RATE_LIMIT_CHAT_PER_MIN: int = 30
    RATE_LIMIT_LOGIN: int = 10
    RATE_LIMIT_LOGIN_WINDOW: int = 300
    RATE_LIMIT_REGISTER: int = 5
    RATE_LIMIT_REGISTER_WINDOW: int = 300

    # ---------- 初始化 ----------
    AUTO_SEED_ADMIN: bool = True

    # ---------- 派生属性 ----------
    @property
    def llm_models(self) -> List[str]:
        """按优先级排列的可用对话模型（跳过空值）。"""
        out = []
        for name in ("LLM_MODEL1", "LLM_MODEL2", "LLM_MODEL3", "LLM_MODEL4", "LLM_MODEL5"):
            v = getattr(self, name, "")
            if v and v.strip() and v.strip() not in out:
                out.append(v.strip())
        return out

    @property
    def embed_models(self) -> List[str]:
        out = []
        for name in ("EMBEDDING_MODEL", "EMBEDDING_MODEL1"):
            v = getattr(self, name, "")
            if v and v.strip() and v.strip() not in out:
                out.append(v.strip())
        return out

    @property
    def llm_base_url(self) -> str:
        """从配置的 URL 推导 OpenAI SDK base_url。"""
        url = self.LLM_API_URL.strip().rstrip("/")
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        return url

    @property
    def upload_dir(self) -> Path:
        d = Path(self.UPLOAD_DIR) if self.UPLOAD_DIR else Path(self.DATA_DIR) / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def vector_dir(self) -> Path:
        d = Path(self.VECTOR_DIR) if self.VECTOR_DIR else Path(self.DATA_DIR) / "vector_store"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def db_url(self) -> str:
        if self.DB_URL:
            return self.DB_URL
        Path(self.DATA_DIR).mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(Path(self.DATA_DIR) / 'knowhub.db').as_posix()}"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
