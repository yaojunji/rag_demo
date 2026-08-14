"""端到端 API 测试：认证 / 知识库 / 文档上传索引（离线 mock 向量化）/ 分块查看。"""
from __future__ import annotations

import time

import pytest


def _mock_embed(monkeypatch):
    """用确定性伪向量替换真实 embedding，保证离线可测。"""
    import numpy as np

    from app.rag import llm as llm_mod

    def fake_embed(texts, model=None):
        rng = np.random.default_rng(42)
        return [rng.random(64).tolist() for _ in texts]

    monkeypatch.setattr(llm_mod.llm_client, "embed", fake_embed)
    # 索引任务引用的是同一个单例
    from app.services import ingestion

    monkeypatch.setattr(ingestion.llm_client, "embed", fake_embed)
    return fake_embed


class TestAuth:
    def test_login_ok(self, client):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123456"})
        assert r.status_code == 200
        data = r.json()
        assert data["access_token"]
        assert data["user"]["role"] == "admin"

    def test_login_wrong(self, client):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
        assert r.status_code == 401

    def test_me(self, client, auth_headers):
        r = client.get("/api/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["username"] == "admin"

    def test_no_token(self, client):
        assert client.get("/api/kbs").status_code == 401

    def test_register(self, client):
        r = client.post(
            "/api/auth/register",
            json={"username": "newbie", "password": "pass123456", "display_name": "新人"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["role"] == "viewer"  # 默认只读
        # 重复注册
        r = client.post("/api/auth/register", json={"username": "newbie", "password": "pass123456"})
        assert r.status_code == 400
        # 新用户可登录并访问全局知识库
        h = {"Authorization": f"Bearer {data['access_token']}"}
        assert client.get("/api/auth/me", headers=h).json()["username"] == "newbie"
        # 注册被审计
        admin = client.post("/api/auth/login", json={"username": "admin", "password": "admin123456"})
        ah = {"Authorization": f"Bearer {admin.json()['access_token']}"}
        logs = client.get("/api/admin/audit-logs", params={"action": "user.register"}, headers=ah).json()
        assert any(i["username"] == "newbie" for i in logs["items"])
        # 清理
        uid = [u for u in client.get("/api/admin/users", headers=ah).json() if u["username"] == "newbie"][0]["id"]
        client.delete(f"/api/admin/users/{uid}", headers=ah)

    def test_global_kb_visible_to_tenant_user(self, client, auth_headers):
        """管理员建的全局库应对所有租户用户可见。"""
        h = auth_headers
        kb = client.post("/api/kbs", json={"name": "全局共享库"}, headers=h).json()
        # 注册用户（挂默认租户）应能看见全局库
        r = client.post("/api/auth/register", json={"username": "glob_user", "password": "pass123456"})
        vh = {"Authorization": f"Bearer {r.json()['access_token']}"}
        kbs = client.get("/api/kbs", headers=vh).json()
        assert any(x["id"] == kb["id"] for x in kbs)
        assert client.get(f"/api/kbs/{kb['id']}", headers=vh).status_code == 200
        # 清理
        client.delete(f"/api/kbs/{kb['id']}", headers=h)
        uid = [u for u in client.get("/api/admin/users", headers=h).json() if u["username"] == "glob_user"][0]["id"]
        client.delete(f"/api/admin/users/{uid}", headers=h)


class TestKB:
    def test_crud(self, client, auth_headers):
        h = auth_headers
        r = client.post("/api/kbs", json={"name": "测试知识库", "description": "自动化测试"}, headers=h)
        assert r.status_code == 200, r.text
        kb = r.json()
        assert kb["chunk_size"] == 800
        kb_id = kb["id"]

        r = client.get("/api/kbs", headers=h)
        assert any(x["id"] == kb_id for x in r.json())

        r = client.put(f"/api/kbs/{kb_id}", json={"name": "改名知识库"}, headers=h)
        assert r.json()["name"] == "改名知识库"

        r = client.delete(f"/api/kbs/{kb_id}", headers=h)
        assert r.status_code == 200

    def test_tenant_isolation(self, client, auth_headers):
        h = auth_headers
        # 建两个租户 + 各自用户
        ta = client.post("/api/admin/tenants", json={"name": "租户A"}, headers=h).json()
        tb = client.post("/api/admin/tenants", json={"name": "租户B"}, headers=h).json()
        ua = client.post(
            "/api/admin/users",
            json={"username": "user_a", "password": "pass123456", "role": "editor", "tenant_id": ta["id"]},
            headers=h,
        ).json()
        ub = client.post(
            "/api/admin/users",
            json={"username": "user_b", "password": "pass123456", "role": "editor", "tenant_id": tb["id"]},
            headers=h,
        ).json()
        ha = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'user_a', 'password': 'pass123456'}).json()['access_token']}"}
        hb = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'user_b', 'password': 'pass123456'}).json()['access_token']}"}
        # A 租户用户建库 → 归属租户 A
        kb = client.post("/api/kbs", json={"name": "A租户专属库"}, headers=ha)
        assert kb.status_code == 200, kb.text
        kb_id = kb.json()["id"]
        assert kb.json()["tenant_id"] == ta["id"]
        # B 租户用户不可访问，A 租户用户可访问
        assert client.get(f"/api/kbs/{kb_id}", headers=hb).status_code == 403
        assert client.get(f"/api/kbs/{kb_id}", headers=ha).status_code == 200
        # A 的列表只含自己的库
        assert [x["id"] for x in client.get("/api/kbs", headers=ha).json()] == [kb_id]
        # 清理
        client.delete(f"/api/kbs/{kb_id}", headers=ha)
        client.delete(f"/api/admin/users/{ua['id']}", headers=h)
        client.delete(f"/api/admin/users/{ub['id']}", headers=h)
        client.delete(f"/api/admin/tenants/{ta['id']}", headers=h)
        client.delete(f"/api/admin/tenants/{tb['id']}", headers=h)


class TestIngestion:
    def test_upload_index_and_query_chunks(self, client, auth_headers, monkeypatch):
        _mock_embed(monkeypatch)
        h = auth_headers
        kb = client.post("/api/kbs", json={"name": "索引测试库", "chunk_size": 300, "chunk_overlap": 40}, headers=h)
        kb_id = kb.json()["id"]
        content = ("# 员工手册\n\n" + "公司要求所有员工按时打卡上班。\n" * 20).encode("utf-8")
        r = client.post(
            f"/api/kbs/{kb_id}/documents/upload",
            headers=h,
            files={"file": ("员工手册.md", content, "text/markdown")},
        )
        assert r.status_code == 200, r.text
        doc = r.json()
        doc_id = doc["id"]

        # 轮询索引完成
        for _ in range(30):
            st = client.get(f"/api/kbs/{kb_id}/documents/{doc_id}/status", headers=h).json()
            if st["status"] == "ready":
                break
            time.sleep(0.2)
        assert st["status"] == "ready", st

        # 分块可查
        chunks = client.get(f"/api/kbs/{kb_id}/documents/{doc_id}/chunks", headers=h)
        assert chunks.status_code == 200
        assert len(chunks.json()) > 0
        assert any("员工手册" in c["content"] for c in chunks.json())

        # 关键词索引已建（FTS）
        from app.rag.retriever import _keyword_search

        hits = _keyword_search(kb_id, "打卡上班", 5)
        assert hits, "FTS 关键词索引未命中"

        # 向量索引已建
        from app.rag.vector_store import vector_store

        assert vector_store.count(kb_id) > 0

        # 重复内容上传检测
        r = client.post(
            f"/api/kbs/{kb_id}/documents/upload",
            headers=h,
            files={"file": ("员工手册-副本.md", content, "text/markdown")},
        )
        assert r.status_code == 400
        assert "重复" in r.json()["detail"]

        # 删除文档后索引清理
        client.delete(f"/api/kbs/{kb_id}/documents/{doc_id}", headers=h)
        assert vector_store.count(kb_id) == 0
        client.delete(f"/api/kbs/{kb_id}", headers=h)


class TestAdmin:
    def test_stats(self, client, auth_headers):
        r = client.get("/api/admin/stats", headers=auth_headers)
        assert r.status_code == 200
        assert "users" in r.json()

    def test_audit_logs(self, client, auth_headers):
        r = client.get("/api/admin/audit-logs", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_user_crud(self, client, auth_headers):
        h = auth_headers
        r = client.post(
            "/api/admin/users",
            json={"username": "editor1", "password": "editor123456", "role": "editor", "display_name": "编辑一号"},
            headers=h,
        )
        assert r.status_code == 200
        uid = r.json()["id"]
        r = client.put(f"/api/admin/users/{uid}", json={"display_name": "编辑二号"}, headers=h)
        assert r.json()["display_name"] == "编辑二号"
        r = client.post("/api/auth/login", json={"username": "editor1", "password": "editor123456"})
        assert r.status_code == 200
        assert client.delete(f"/api/admin/users/{uid}", headers=h).status_code == 200

    def test_role_forbidden(self, client, auth_headers):
        h = auth_headers
        client.post(
            "/api/admin/users",
            json={"username": "viewer2", "password": "viewer123456", "role": "viewer"},
            headers=h,
        )
        login = client.post("/api/auth/login", json={"username": "viewer2", "password": "viewer123456"})
        vh = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/admin/users", headers=vh).status_code == 403
        assert client.post("/api/kbs", json={"name": "x"}, headers=vh).status_code == 403
