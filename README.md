# KnowHub（知枢）· 企业级 RAG 知识库 Agent

> 基于大模型的企业级检索增强生成（RAG）知识库平台：上传文档自动建立知识库，
> 通过**向量 + 关键词混合检索 + LLM 重排**精准召回，以**带引用的流式问答**回答员工问题，
> 并内置**多租户、RBAC 权限、操作审计、异步索引、模型自动降级**等企业级能力。

![Python](https://img.shields.io/badge/Python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green) ![Vue](https://img.shields.io/badge/Vue-3-42b883) ![AntDV](https://img.shields.io/badge/Ant%20Design%20Vue-4-1677ff) ![ChromaDB](https://img.shields.io/badge/ChromaDB-black)

---

## ✨ 核心能力

| 能力 | 说明 |
|---|---|
| 📚 多格式文档接入 | Markdown / TXT / HTML / **PDF（保留页码）** / Word / Excel / PPT |
| 🧠 智能切分 | Markdown 标题感知切块 + 定长重叠，知识库级参数可调 |
| 🔍 混合检索 | 语义向量（Chroma）+ 关键词 BM25（jieba + SQLite FTS5）+ RRF 融合 |
| 🎯 LLM 重排 | 大模型对候选片段二次排序，提升答案精度（可开关） |
| 💬 流式问答 | SSE 实时输出，回答逐句带引用 `[1][2]`，点击可看原文片段与页码 |
| 🔄 模型降级 | `qwen-max → glm-5 → qwen3-coder-plus → qwen-plus-0112` 主备自动切换 |
| 👥 多租户 + RBAC | 租户数据隔离（全局库所有租户共享）；管理员 / 编辑 / 只读三级权限 |
| 📝 用户注册 | 登录页自助注册（默认只读），权限由超级管理员在「系统管理 → 用户管理」中调整 |
| 📋 操作审计 | 登录、注册、上传、删除、问答全部留痕，管理端可查可筛 |
| ⚙️ 异步索引 | 上传即返回，后台解析→切分→向量化，前端实时进度，重启自动恢复 |
| 🔐 安全 | PBKDF2-SHA256 密码、JWT 过期、登录/注册/问答限流、上传校验 |

## 🚀 快速开始

### 方式一：本地运行（最快）

```bash
# 1. 后端
cd backend
python -m venv .venv
.venv\Scripts\activate              # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. 前端（新终端）
cd frontend
npm install
npm run dev                         # http://127.0.0.1:5173
```

> 或 `npm run build` 后直接访问 **http://127.0.0.1:8000**（后端自动托管前端产物）。

### 方式二：Docker

```bash
docker compose up -d --build
# 前端 http://127.0.0.1:8080 · API http://127.0.0.1:8000/api · Swagger http://127.0.0.1:8000/docs
```

### 默认账号

| 账号 | 密码 | 角色 |
|---|---|---|
| `admin` | `admin123456` | 超级管理员（**登录后请立即修改密码**） |

> 登录页提供「注册账号」入口：注册后默认为**只读**角色（可立即问答、查看全局知识库），
> 上传文档等管理权限需由超级管理员在「系统管理 → 用户管理 → 编辑」中分配（角色 / 租户 / 启停）。
> 企业如不需自助注册，可在 `.env` 设置 `REGISTRATION_ENABLED=false` 关闭。

## 🧪 3 分钟体验

```bash
# 1. 生成示例文档（员工手册 / 产品FAQ / 报销制度 / 客户数据）
.venv\Scripts\python backend\scripts\make_examples.py

# 2. 打开控制台 http://127.0.0.1:5173（或 :8000）
#    登录 → 知识库管理 → 新建知识库「公司制度」
#    → 上传 examples/ 下的文档 → 等待索引完成

# 3. 智能问答 → 选择知识库 → 提问：
#    "员工年假怎么算？"   "报销住宿标准是多少？"   "如何计费？"
#    AI 将引用《员工手册》《差旅报销管理制度》等原文并标注页码
```

## 📁 项目结构

```
demo-1/
├── backend/                  # FastAPI 后端
│   ├── app/
│   │   ├── core/             # 配置 / 安全（JWT、密码哈希）
│   │   ├── db/               # SQLAlchemy 引擎与模型
│   │   ├── models/           # Tenant/User/KB/Document/Chunk/会话/审计
│   │   ├── schemas/          # Pydantic 请求响应
│   │   ├── rag/              # ★ RAG 核心：解析/切分/向量库/检索/重排/编排
│   │   ├── services/         # 索引流水线 / 聊天 / 审计
│   │   ├── tasks/            # 异步任务管理
│   │   └── api/              # 认证/知识库/文档/问答/管理 路由
│   ├── tests/                # 单元 + API 集成测试（离线可跑）
│   ├── scripts/              # 示例数据生成
│   └── requirements.txt
├── frontend/                 # Vue 3 + TypeScript + Ant Design Vue 企业控制台
│   └── src/pages/            # 智能问答 / 知识库管理 / 系统管理
├── examples/                 # 示例文档
├── docker/                   # Dockerfile + nginx(SSE 配置)
├── docs/                     # 架构 / API / 部署文档
├── docker-compose.yml
└── .env                      # 模型与网关配置（已适配可用网关）
```

## 🧠 RAG 技术要点

- **解析**：`pypdf` 逐页提取（保留页码，回答可精确到页）；docx 含表格、xlsx 逐工作表
- **切分**：Markdown 优先按标题层级切片，再按字符数控制长度并保留重叠，兼顾语义完整与检索粒度
- **混合检索**：语义召回（Chroma cosine）+ 关键词召回（jieba 分词 → FTS5 BM25），**RRF 融合**避免单一检索失效
- **重排**：LLM 基于「问题-片段」相关性输出排序 JSON，取 Top-N 送入生成
- **引用**：系统提示词强制编号引用 `[n]`，回答落库时同步保存引用元数据，可审计、可溯源

## ✅ 测试

```bash
cd backend
.venv\Scripts\python -m pytest          # 无需网络（embedding 已 mock）
```

覆盖：密码/JWT、切分器、解析器、RRF 融合、认证流、注册、RBAC 隔离、全局库可见性、上传→索引→FTS/向量落库→删除清理。

## 📚 文档

- [架构设计](docs/architecture.md) — 系统架构图、数据流、模块说明、生产化路径
- [API 文档](docs/api.md) — 全部接口、SSE 事件格式、角色矩阵
- [部署指南](docs/deployment.md) — 本地 / Docker / 配置项 / 备份 / FAQ

## ⚠️ 生产环境检查清单

- [ ] 修改 `JWT_SECRET` 与默认管理员密码
- [ ] `LLM_API_KEY` 从密钥库注入（勿提交仓库）
- [ ] 切换 PostgreSQL，向量库按需迁移 Milvus/Qdrant
- [ ] 多实例部署时引入 Redis 限流与消息队列
- [ ] nginx 启用 HTTPS；审计日志对接 SIEM

---

**模型网关说明**：本项目通过 OpenAI 兼容协议对接大模型。`.env` 中默认网关为已验证可用的
阿里云百炼 DashScope 兼容模式（`qwen-max`/`glm-5` 等模型实测通过）；如贵司有自建网关
（vLLM / one-api / 私有化 OpenAI 兼容服务），只需修改 `LLM_API_URL` 一个变量即可切换。
