# API 接口文档

基础路径：`/api`；除 `login` 外均需 `Authorization: Bearer <token>`。
交互式文档（Swagger）：启动后访问 `http://127.0.0.1:8000/docs`。

## 认证

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 登录，返回 `{access_token, user}` |
| GET | `/api/auth/me` | 当前用户信息 |
| POST | `/api/auth/change-password` | 修改密码 `{old_password, new_password}` |

## 知识库（KB）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/kbs` | admin/editor | 创建 `{name, description?, chunk_size?, chunk_overlap?}` |
| GET | `/api/kbs` | 全部 | 列表（租户隔离） |
| GET | `/api/kbs/{id}` | 全部 | 详情 |
| PUT | `/api/kbs/{id}` | admin/editor | 更新 |
| DELETE | `/api/kbs/{id}` | admin/editor | 删除（含全部索引） |

## 文档

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/kbs/{kid}/documents/upload` | admin/editor | multipart 上传，返回 doc 记录（异步索引） |
| GET | `/api/kbs/{kid}/documents` | 全部 | 文档列表（可 `?status=ready` 过滤） |
| GET | `/api/kbs/{kid}/documents/{id}/status` | 全部 | 索引任务状态/进度 |
| POST | `/api/kbs/{kid}/documents/{id}/reindex` | admin/editor | 重建索引 |
| DELETE | `/api/kbs/{kid}/documents/{id}` | admin/editor | 删除文档及索引 |
| GET | `/api/kbs/{kid}/documents/{id}/chunks` | 全部 | 分块预览 |
| GET | `/api/kbs/{kid}/documents/{id}/download` | 全部 | 下载原始文件 |

## 问答（SSE 流式）

```
POST /api/chat/ask
Content-Type: application/json
Authorization: Bearer <token>

{ "kb_id": 1, "message": "年假几天？", "session_id": null,
  "history": [], "top_k": 8, "temperature": null }
```

响应为 `text/event-stream`，事件（`data: {json}\n\n`）：

| type | 字段 | 说明 |
|---|---|---|
| `meta` | model, timings_ms, citations, chunk_count | 检索完成，先于文本输出 |
| `delta` | content, model | 生成增量文本 |
| `done` | session_id, latency_ms, timings_ms | 回答结束（含持久化后的会话 id） |
| `error` | message | 失败信息 |

会话管理：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/chat/sessions` | 我的会话列表 |
| GET | `/api/chat/sessions/{id}/messages` | 会话消息（含引用） |
| DELETE | `/api/chat/sessions/{id}` | 删除会话 |

## 系统管理（仅 admin）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/admin/users` | 用户列表 / 创建 |
| PUT/DELETE | `/api/admin/users/{id}` | 更新（改密/角色/禁用）/ 删除 |
| GET/POST | `/api/admin/tenants` | 租户列表 / 创建 |
| DELETE | `/api/admin/tenants/{id}` | 删除租户（须先清空用户与知识库） |
| GET | `/api/admin/audit-logs` | 审计日志 `?page=&page_size=&action=&username=` |
| GET | `/api/admin/stats` | 系统统计 |
| GET | `/api/admin/config` | RAG 运行配置 |

## 角色矩阵

| 操作 | admin | editor | viewer |
|---|---|---|---|
| 问答（含历史） | ✅ | ✅ | ✅ |
| 查看知识库/文档/分块 | ✅ | ✅ | ✅ |
| 创建/编辑/删除知识库 | ✅ | ✅ | ❌ |
| 上传/删除/重建文档 | ✅ | ✅ | ❌ |
| 用户/租户/审计/统计 | ✅ | ❌ | ❌ |

## 错误码约定

- `401` 未认证/令牌过期；`403` 权限不足；`404` 资源不存在
- `400` 参数/业务错误；`429` 触发限流；`500` 服务器内部错误
