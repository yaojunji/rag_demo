"""KnowHub 测试环境：先设置隔离存储再导入应用。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="knowhub_test_"))
os.environ["DB_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["VECTOR_DIR"] = str(_TMP / "vectors")
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["AUTO_SEED_ADMIN"] = "true"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123456"
os.environ["LLM_API_KEY"] = "test-key-not-used"
os.environ["ENABLE_RERANK"] = "false"
os.environ["ENABLE_CITATION_AUDIT"] = "false"
# 测试环境放宽限流
os.environ["RATE_LIMIT_LOGIN"] = "10000"
os.environ["RATE_LIMIT_REGISTER"] = "10000"

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# 导入前确保环境变量已生效（settings 为 lru_cache）
from app.core.config import get_settings  # noqa: E402

_settings = get_settings()
assert _settings.db_url.startswith("sqlite"), "测试必须使用独立数据库"


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP


@pytest.fixture()
def client():
    """应用测试客户端（含 lifespan 初始化）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123456"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
