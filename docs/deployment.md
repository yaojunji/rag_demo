# 部署指南

## 方式一：本地开发运行（推荐先体验）

### 1. 后端

```bash
cd backend
python -m venv .venv                      # 已存在可跳过
.venv\Scripts\activate                    # Windows（Linux/macOS: source .venv/bin/activate）
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

首次启动自动完成：建表 → 初始化关键词索引 → 创建默认租户与管理员。

### 2. 前端（开发模式）

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173 （已配置 /api 代理到 8000）
```

### 3. 生产构建（后端直接托管）

```bash
cd frontend && npm run build
# 然后只需启动后端：访问 http://127.0.0.1:8000 即为完整应用
```

## 方式二：Docker Compose（推荐生产）

```bash
docker compose up -d --build
# 前端   http://127.0.0.1:8080
# API    http://127.0.0.1:8000/api
# Swagger http://127.0.0.1:8000/docs
```

数据持久化在 Docker volume `knowhub-data`（SQLite + Chroma + 上传文件）。

## 配置说明（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_API_KEY` | - | 网关 API Key（OpenAI 兼容） |
| `LLM_API_URL` | dashscope 兼容模式 | 网关地址，可写完整 chat URL 或 base |
| `LLM_MODEL1..5` | qwen-max, glm-5, … | 对话模型优先级列表，失败自动降级 |
| `EMBEDDING_MODEL` / `EMBEDDING_MODEL1` | qwen3.7-text-embedding / text-embedding-v3 | 向量模型优先级 |
| `JWT_SECRET` | dev 值 | **生产必须修改** |
| `ADMIN_USERNAME/PASSWORD` | admin/admin123456 | 首次启动的管理员，**请立即修改** |
| `CHUNK_SIZE/CHUNK_OVERLAP` | 800/120 | 默认切分参数 |
| `ENABLE_RERANK` / `ENABLE_HYBRID` | true/true | LLM 重排 / 混合检索开关 |
| `RETRIEVE_TOP_K` / `RERANK_TOP_K` | 12 / 6 | 召回与重排数量 |
| `DB_URL` | sqlite:///data/knowhub.db | 可切换 PostgreSQL（`postgresql+psycopg://…`） |
| `MAX_UPLOAD_MB` | 50 | 上传大小上限 |

## 升级 / 备份

- 备份：停服后打包 `data/` 目录（SQLite、Chroma、上传文件）即可完整迁移
- 数据库迁移：模型变更后用 Alembic 生成迁移（当前版本直接 `create_all` 建表）

## 常见问题

| 现象 | 处理 |
|---|---|
| API 调用失败（401 invalid api key） | 检查 `.env` 的 `LLM_API_KEY` 与网关是否匹配 |
| 上传后文档一直 pending | 服务重启会标记失败，点「重建索引」 |
| 问答无引用 | 知识库为空或检索无命中；确认 `ENABLE_RERANK` 下的模型可用 |
| SSE 前端不流式 | nginx 已配置 `proxy_buffering off`；本地开发用 Vite 代理 |
| 中文关键词检索无结果 | 依赖 jieba，确认 `chunk_fts` 表已建（日志可见） |
