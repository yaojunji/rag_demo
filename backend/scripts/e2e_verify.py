"""端到端验证：登录 → 建库 → 上传 4 类示例文档 → 等待索引 → 流式问答（真实模型）。

用法: python scripts/e2e_verify.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api"
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def p(title: str, obj) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:2000])


def main() -> None:
    c = httpx.Client(timeout=120, base_url=BASE)

    # 1) 登录
    r = c.post("/auth/login", json={"username": "admin", "password": "admin123456"})
    r.raise_for_status()
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    p("登录", {"user": r.json()["user"]["username"], "role": r.json()["user"]["role"]})

    # 2) 建知识库
    r = c.post("/kbs", json={"name": "公司制度知识库", "description": "端到端验证", "chunk_size": 500, "chunk_overlap": 60}, headers=h)
    r.raise_for_status()
    kb = r.json()
    p("创建知识库", kb)
    kb_id = kb["id"]

    try:
        # 3) 上传全部示例文档
        for f in sorted(EXAMPLES.iterdir()):
            if not f.is_file():
                continue
            with f.open("rb") as fp:
                r = c.post(
                    f"/kbs/{kb_id}/documents/upload",
                    headers=h,
                    files={"file": (f.name, fp, "application/octet-stream")},
                )
            r.raise_for_status()
            doc = r.json()
            print(f"上传: {f.name} -> doc#{doc['id']} status={doc['status']}")

        # 4) 轮询索引完成
        for _ in range(120):
            r = c.get(f"/kbs/{kb_id}/documents", headers=h)
            docs = r.json()
            if all(d["status"] == "ready" for d in docs):
                break
            time.sleep(2)
        p("索引结果", [{"file": d["filename"], "status": d["status"], "chunks": d["chunk_count"], "err": d["error"]} for d in docs])
        assert all(d["status"] == "ready" for d in docs), "索引未完成"

        # 5) 分块验证
        doc0 = docs[0]
        r = c.get(f"/kbs/{kb_id}/documents/{doc0['id']}/chunks", headers=h)
        p("分块预览(前2块)", r.json()[:2])

        # 6) 流式问答（真实模型 + 引用）
        questions = [
            "员工年假怎么计算？",
            "住宿报销标准是多少？",
            "星辰云平台如何计费？",
        ]
        for q in questions:
            print(f"\n\n>>>> 问题: {q}")
            with c.stream("POST", "/chat/ask", json={"kb_id": kb_id, "message": q, "top_k": 8}, headers=h) as resp:
                resp.raise_for_status()
                answer = ""
                meta = None
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    ev = json.loads(line[6:])
                    if ev["type"] == "meta":
                        meta = ev
                    elif ev["type"] == "delta":
                        answer += ev["content"]
                    elif ev["type"] == "done":
                        print(f"  [done] session={ev['session_id']} 耗时={ev['latency_ms']}ms")
                    elif ev["type"] == "error":
                        print(f"  [error] {ev['message']}")
            p("回答", answer)
            if meta:
                p("引用", meta.get("citations", [])[:5])
            assert answer.strip(), f"问题「{q}」没有得到回答"
            assert meta and meta.get("citations"), f"问题「{q}」没有引用"

        # 7) 会话与消息落库验证
        r = c.get("/chat/sessions", headers=h)
        sid = r.json()[0]["id"]
        r = c.get(f"/chat/sessions/{sid}/messages", headers=h)
        msgs = r.json()
        p("会话消息", {"session": sid, "消息数": len(msgs), "最后一条模型": msgs[-1]["model"], "引用数": len(msgs[-1]["citations"] or [])})

        # 8) 审计日志
        r = c.get("/admin/audit-logs", params={"page_size": 10}, headers=h)
        p("审计日志(最新10条)", [{"t": i["action"], "u": i["username"], "d": i["detail"][:40]} for i in r.json()["items"]])

        # 9) 系统统计
        r = c.get("/admin/stats", headers=h)
        st = r.json()
        p("系统统计", {"知识库": st["knowledge_bases"], "文档": st["documents"], "分块": st["chunks"], "问答消息": st["chat_messages"], "模型": f"{st['llm_model']} / {st['embed_model']}"})

        print("\n\n✅ 端到端验证全部通过")
    finally:
        # 清理
        r = c.delete(f"/kbs/{kb_id}", headers=h)
        print(f"\n清理知识库: {r.status_code} {r.json()}")


if __name__ == "__main__":
    sys.exit(main())
