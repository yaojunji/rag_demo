# KnowHub（知枢）· 企业级 RAG 知识库 Agent

基于大模型的检索增强生成（RAG）知识库问答平台：上传文档自动建立知识库，通过**向量 + 关键词混合检索 + LLM 重排**精准召回，以**带引用溯源（文档/页码）的流式问答**回答用户问题，内置多租户、RBAC 权限、操作审计、异步索引等企业级能力。

## 技术栈

- **后端**：Python 3.11 · FastAPI · SQLAlchemy · ChromaDB · SQLite FTS5 · jieba · OpenAI SDK
- **前端**：Vue 3 · TypeScript · Ant Design Vue · Pinia · ECharts · Vite
- **部署**：Docker Compose（FastAPI + nginx/SSE 反代）

## 核心功能

- 📚 多格式文档接入：PDF（保留页码）/ Word / Excel / PPT / Markdown / TXT / HTML
- 🔍 混合检索：语义向量（ChromaDB）+ 关键词 BM25（jieba + FTS5）+ RRF 融合 + LLM 重排
- 💬 流式问答：SSE 实时输出，回答带引用标注 `[1][2]`，可溯源到文档与页码；含引用审计、回答脱敏、追问建议、查询改写
- 👥 多租户 + RBAC：租户数据隔离；admin / editor / viewer 三级角色；自助注册
- 🔌 对外集成：OpenAI 兼容接口 `/v1/chat/completions`（支持流式），外部系统零改造接入
- 🗑 文档管理：回收站、批量操作、版本替换、ZIP 批量导入、知识库导出/导入/克隆
- 📊 企业级能力：操作审计、站内通知、数据仪表盘、检索调试台、模型自检、限流、敏感信息检测与脱敏

## 快速开始

### 方式一：本地运行

```bash
# 1. 后端
cd backend
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
# 复制 .env.example 为 .env 并填入 LLM_API_KEY
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. 前端（新终端）
cd frontend
npm install
npm run dev                     # http://127.0.0.1:5173（/api 已代理到 8000）
```

> 或 `npm run build` 后直接访问 http://127.0.0.1:8000（后端自动托管前端产物）。

### 方式二：Docker

```bash
docker compose up -d --build
# 前端 http://127.0.0.1:8080 · API http://127.0.0.1:8000/api
```

### 默认账号

| 账号 | 密码 | 角色 |
|---|---|---|
| `admin` | `admin123456` | 超级管理员 |

## 测试

```bash
cd backend
.venv\Scripts\python -m pytest    # 27 项离线测试（无需网络，embedding 已 mock）
```

## 配置

所有配置在 `.env`（参考 `.env.example`）：LLM 网关（OpenAI 兼容，可切换任意供应商）、模型列表与降级、RAG 参数、JWT 密钥、限流、回收站保留天数等。
