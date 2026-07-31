# IntelliKB 架构概览

> 基于 RAG + Agent 的企业级智能知识库平台 — 架构总览

---

## 1. 技术栈一览

| 层级            | 技术                    |     版本      | 用途                    |
| --------------- | ----------------------- | :-----------: | ----------------------- |
| **后端语言**    | Python 3.11             |     ≥3.11     | 核心开发语言            |
| **Web 框架**    | FastAPI                 |    ≥0.115     | REST API + SSE 流式     |
| **ASGI 服务器** | Uvicorn                 |     ≥0.34     | 异步 WSGI/ASGI          |
| **ORM**         | SQLAlchemy 2.0 (async)  |     ≥2.0      | 异步数据库映射 + 迁移   |
| **数据库驱动**  | aiomysql + pymysql      |       —       | 异步 MySQL 适配         |
| **数据库**      | MySQL 8.0               |      8.0      | 业务数据持久化          |
| **缓存/消息**   | Redis 7                 |      7.x      | 缓存 + Pub/Sub 进度推送 |
| **向量存储**    | Chroma                  |     ≥0.6      | 文档向量化存储与检索    |
| **Embedding**   | bge-small-zh            |       —       | 中文文本向量化          |
| **Reranker**    | Cross-encoder           |       —       | 检索结果重排序          |
| **Agent 框架**  | LangGraph               | ≥0.2.0,<0.3.0 | Agent ReAct 循环        |
| **LLM 推理**    | Ollama (qwen2.5:7b)     |       —       | 文本生成                |
| **前端框架**    | Vue 3 + TypeScript      |      3.5      | SPA 前端                |
| **状态管理**    | Pinia                   |      4.x      | 前端状态管理            |
| **UI 库**       | Element Plus            |      2.x      | 企业级 UI 组件          |
| **构建工具**    | Vite                    |      8.x      | 前端构建                |
| **容器化**      | Docker + docker-compose |       —       | 开发/生产部署           |

---

## 2. 后端分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HTTP Request / SSE                          │
│   JWT Bearer │ X-API-Key │ Cookie (EventSource)                    │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                      Middleware 层                                   │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐              │
│  │  CORS    │ │ Trace ID │ │ Rate      │ │ Exception│              │
│  │  (allow) │ │ (Context)│ │ Limit     │ │ Handler  │              │
│  └──────────┘ └──────────┘ └───────────┘ └──────────┘              │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                      API 路由层 (app/api/v1/)                        │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │  Auth    │ │  KB      │ │ Document │ │  QA/RAG  │ │  Agent   │  │
│  │ /auth/*  │ │ /kb/*    │ │ /doc/*   │ │ /qa/*    │ │ /agent/* │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ Convers. │ │ Health   │ │ Members  │ │ Admin    │               │
│  │ /conv/*  │ │ /health  │ │ /members │ │ /admin/* │               │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
│  ┌──────────┐                                                        │
│  │ Eval     │                                                        │
│  │ /eval/*  │                                                        │
│  └──────────┘                                                        │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                      服务层 (app/services/) — 22 个业务服务           │
│                                                                     │
│   详见下方「服务层清单」，按领域分组列出全部服务。                   │
└───────────────────────────┬─────────────────────────────────────────┘

### 服务层清单

| 领域 | 服务 | 职责 |
|------|------|------|
| 认证/用户 | AuthService | 注册/登录/JWT/API Key |
| 知识库 | KBService / KBMemberCache | KB CRUD / 成员权限缓存 |
| 文档 | DocService / EmbeddingService | 解析/分块/向量化 |
| 检索 | HybridSearchService / VectorStore / BM25Service | 混合检索 |
| 精排 | RerankService | Cross-encoder 三层精排 |
| 问答 | RAGService / QueryRewriteService / RAGCacheService | RAG 问答/查询改写/缓存 |
| Agent | AgentService / CheckpointCleanupService | LangGraph 对话 / checkpoint 清理 |
| 对话 | ConversationService | 会话/消息持久化 |
| 进度 | ProgressPubSub / ProgressManager | Redis Pub/Sub SSE 进度 |
| 评测 | EvalService / CitationParser | 评测/引用解析 |
| 管理 | AuditService / ConfigCacheService / QuotaService | 审计/配置/配额 |
| 成本 | (内嵌于 Agent/RAGService) | Redis 日/月 token 限额 |

┌───────────────────────────▼─────────────────────────────────────────┐
│                     Repository 层 (app/repositories/)                │
│                                                                     │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐           │
│  │  UserRepo  │ │  KBRepo   │ │  DocRepo  │ │  ConvRepo  │           │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘           │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐                         │
│  │  MsgRepo   │ │  Member   │ │  ChunkRepo│                         │
│  │            │ │  Repo     │ │           │                         │
│  └───────────┘ └───────────┘ └───────────┘                         │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                     模型层 (app/models/)                             │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐           │
│  │ sys_user │ │ sys_kb   │ │ sys_doc  │ │ sys_convers. │           │
│  ├──────────┤ ├──────────┤ ├──────────┤ ├──────────────┤           │
│  │ id       │ │ id       │ │ id       │ │ id           │           │
│  │ username │ │ name     │ │ kb_id    │ │ kb_id        │           │
│  │ password │ │ owner_id │ │ filename  │ │ user_id      │           │
│  │ api_key  │ │ ...      │ │ status   │ │ title        │           │
│  │ ...      │ │          │ │ file_type│ │ message_count│           │
│  └──────────┘ └──────────┘ └──────────┘ │ deleted_at   │           │
│  ┌──────────┐ ┌──────────┐              └──────────────┘           │
│  │ sys_msg  │ │ sys_kb_  │              ┌──────────────┐           │
│  ├──────────┤ │ member   │              │ sys_chunk    │           │
│  │ id       │ ├──────────┤              ├──────────────┤           │
│  │ conv_id  │ │ id       │              │ id           │           │
│  │ role     │ │ kb_id    │              │ doc_id       │           │
│  │ content  │ │ user_id  │              │ content      │           │
│  │ metadata │ │ role     │              │ embedding    │           │
│  │ token_cnt│ │ ...      │              │ ...          │           │
│  └──────────┘ └──────────┘              └──────────────┘           │
└─────────────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│                     基础设施层                                       │
│                                                                     │
│  ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────┐           │
│  │  MySQL 8.0 │ │  Redis 7   │ │  Chroma  │ │  Ollama  │           │
│  │  持久化存储  │ │ 缓存/PubSub│ │  向量存储  │ │  LLM 推理 │           │
│  └────────────┘ └────────────┘ └──────────┘ └──────────┘           │
└─────────────────────────────────────────────────────────────────────┘
```

### 层间调用规则

| 调用方向             | 规则                               | 禁止                                |
| -------------------- | ---------------------------------- | ----------------------------------- |
| API → Service        | API 路由层调用 Service 服务        | API 直接调用 Repository 或 Model    |
| Service → Repository | Service 通过 Repository 访问数据库 | Service 直接操作 SQLAlchemy Session |
| Service → Service    | 同级 Service 允许互相调用          | 循环依赖                            |
| Repository → Model   | Repository 操作 ORM Model          | Repository 调用其他 Repository      |
| API → Middleware     | 请求经中间件处理后到达路由         | 路由层手动调用中间件                |

---

## 3. 数据模型 ER 图

```
┌─────────────────────┐       ┌───────────────────────┐
│      sys_user       │       │       sys_kb          │
├─────────────────────┤       ├───────────────────────┤
│ id (PK)            │◄──────│ owner_id (FK)         │
│ username            │       │ id (PK)               │
│ password_hash       │       │ name                  │
│ api_key_hash        │       │ description           │
│ is_active           │       │ creator_id            │
│ created_at          │       │ is_public             │
│ updated_at          │       │ ...                   │
└─────────────────────┘       └───────────┬───────────┘
                                          │
       ┌──────────────────────────────────┤
       │                                  │
       ▼                                  ▼
┌──────────────────┐          ┌───────────────────────┐
│  sys_kb_member   │          │     sys_document      │
├──────────────────┤          ├───────────────────────┤
│ id (PK)          │          │ id (PK)               │
│ kb_id (FK)       │─────────│ kb_id (FK)            │
│ user_id (FK)     │          │ filename              │
│ role (str)       │          │ file_type             │
│ ...              │          │ file_size             │
└──────────────────┘          │ status                │
                              │ ...                   │
                              └───────────┬───────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │      sys_chunk        │
                              ├───────────────────────┤
                              │ id (PK)               │
                              │ doc_id (FK)           │
                              │ chunk_index           │
                              │ content (Text)        │
                              │ embedding (BLOB)      │
                              │ metadata (JSON)       │
                              └───────────────────────┘

┌─────────────────────┐       ┌───────────────────────┐
│  sys_conversation   │       │     sys_message       │
├─────────────────────┤       ├───────────────────────┤
│ id (PK)            │───────│ conversation_id (FK)  │
│ kb_id (FK)         │       │ id (PK)               │
│ user_id (FK)       │       │ role                  │
│ title               │       │ content (Text)        │
│ message_count       │       │ metadata_json (Text)  │
│ created_at          │       │ token_count           │
│ updated_at          │       │ tool_call_id          │
│ deleted_at          │       │ created_at            │
└─────────────────────┘       │ updated_at            │
                              └───────────────────────┘
```

### 索引策略

| 表                 | 索引                    | 用途                      |
| ------------------ | ----------------------- | ------------------------- |
| `sys_conversation` | `(kb_id, user_id)`      | 按知识库+用户查询对话列表 |
| `sys_conversation` | `(user_id)`             | 按用户查询所有对话        |
| `sys_message`      | `(conversation_id, id)` | 游标分页查询消息          |
| `sys_message`      | `(conversation_id)`     | 按对话查询消息            |
| `sys_kb_member`    | `(kb_id, user_id)`      | 权限校验                  |
| `sys_chunk`        | `(doc_id, chunk_index)` | 按文档查询分块            |

### 实体关系说明

- **User → KB**: 一对多。一个用户可创建多个知识库。
- **KB → Document**: 一对多。一个知识库包含多个文档。
- **Document → Chunk**: 一对多。一个文档被切分为多个分块。
- **KB → KBMember**: 一对多。一个知识库有多个成员。
- **User → KBMember**: 一对多。一个用户是多个知识库的成员。
- **Conversation → Message**: 一对多。一个对话包含多条消息。
- **User → Conversation**: 一对多。一个用户发起多个对话。
- **KB → Conversation**: 一对多。一个知识库包含多个对话。

---

## 4. 文档处理管线

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  上传     │    │  解析     │    │  分块     │    │  索引     │    │  完成     │
│ Upload   │───→│ Parsing  │───→│ Chunking │───→│ Indexing │───→│ Done     │
│          │    │          │    │          │    │          │    │          │
│ POST /   │    │ PDF/DOCX │    │ 按段落/  │    │ Chroma   │    │ SSE推送  │
│ documents│    │ MD/TXT   │    │ 固定大小  │    │向量化存储 │    │完成事件   │
│ /upload  │    │ 文本提取  │    │ 分块策略  │    │          │    │          │
└────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘
     │               │               │               │               │
     └───────────────┴───────────────┴───────────────┴───────────────┘
                              │
                     ProgressPubSubManager
                     ┌──────────────────┐
                     │  Redis Pub/Sub   │
                     │ doc:progress:{id} │
                     │  + key 轮询      │
                     └────────┬─────────┘
                              │
                     ┌────────▼─────────┐
                     │   SSE 端点       │
                     │  GET /documents/ │
                     │  {id}/progress   │
                     │  -pubsub         │
                     └──────────────────┘
```

### 解析状态机

```
                  ┌──────────┐
                  │  pending │  ← 上传完成
                  └────┬─────┘
                       │
                  ┌────▼─────┐
            ┌─────│ parsing   │──────┐ error
            │     └────┬─────┘      │
            │          │            ▼
            │     ┌────▼─────┐  ┌──────┐
            │     │ chunking │  │error │
            │     └────┬─────┘  └──────┘
            │          │
            │     ┌────▼─────┐
            │     │ indexing │
            │     └────┬─────┘
            │          │
            │     ┌────▼─────┐
            └─────│   done   │
                  └──────────┘
```

---

## 5. RAG 检索管线

```
                   用户问题
                       │
                       ▼
              ┌─────────────────┐
              │  Query Rewrite  │  ← Phase 2: 查询重写/扩展
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │  混合检索(并行)  │
              │                 │
     ┌────────┴────────┐  ┌────┴────────────┐
     │   BM25 关键词    │  │  向量语义检索     │
     │   (数据库全文    │  │  (Chroma   │
     │    索引)         │  │   cosine sim)   │
     └────────┬────────┘  └────┬────────────┘
              │                 │
              └──────┬──────────┘
                     │
              ┌──────▼──────────┐
              │  Cross-encoder   │  ← 重排序: 精排 Top-K
              │  Reranker        │
              └──────┬──────────┘
                     │
              ┌──────▼──────────┐
              │   RAG Cache      │  ← Redis 缓存 (key=hash(query))
              │  (命中直接返回)   │
              └──────┬──────────┘
                     │
              ┌──────▼──────────┐
              │  LLM 生成回答    │  ← Ollama qwen2.5:7b
              │  基于检索结果    │     + 引用来源
              └──────┬──────────┘
                     │
              ┌──────▼──────────┐
              │   Stream / 返回  │
              │  完整回答+来源    │
              └─────────────────┘
```

### 检索策略对比

| 策略     | 召回方式            | 优势             | 适用场景           |
| -------- | ------------------- | ---------------- | ------------------ |
| BM25     | 关键词匹配          | 精确匹配，零延迟 | 专有名词、代码片段 |
| 向量检索 | 语义相似度          | 语义理解，容错强 | 同义词、长句查询   |
| 混合检索 | BM25 + 向量加权融合 | 两者兼得         | 通用检索           |
| Rerank   | Cross-encoder 精排  | 精度最高         | 最终 Top-K 排序    |

---

## 6. Agent 对话架构

### 6.1 当前架构（Phase 5-6 ReAct + Token 流式）

```
                     ┌─────────────────────────┐
                     │   POST /agent/chat       │
                     │   POST /agent/chat-stream│
                     └───────────┬─────────────┘
                                 │
                     ┌───────────▼─────────────┐
                     │    AgentService          │
                     │  ┌───────────────────┐  │
                     │  │ 1. 校验 KB 访问    │  │
                     │  │ 2. 创建/获取对话   │  │
                     │  │ 3. 装载历史+截断   │  │
                     │  │ 4. 运行 LangGraph  │  │
                     │  │ 5. 持久化消息      │  │
                     │  └───────────────────┘  │
                     └───────────┬─────────────┘
                                 │
                     ┌───────────▼─────────────┐
                     │    LangGraph StateGraph  │
                     │                         │
                     │  ┌───────────────────┐  │
                     │  │  call_tool         │  │
                     │  │  ────────────────  │  │
                     │  │  retrieve_knowledge│  │
                     │  │  → sources + log   │  │
                     │  └────────┬──────────┘  │
                     │           │             │
                     │  ┌────────▼──────────┐  │
                     │  │  call_model        │  │
                     │  │  ────────────────  │  │
                     │  │  LLM 生成回答      │  │
                     │  │  (tool result 注入)│  │
                     │  └────────┬──────────┘  │
                     │           │             │
                     │       ┌────▼────┐       │
                     │       │   END   │       │
                     │       └─────────┘       │
                     └─────────────────────────┘
```

### 6.2 未来架构（Phase 4 完整 ReAct）

```
                     ┌─────────────────────────┐
                     │  LangGraph ReAct Graph   │
                     │                         │
                     │  ┌───────────────────┐  │
                     │  │  call_model        │  │
                     │  │  LLM + tools schema│  │
                     │  └────────┬──────────┘  │
                     │           │             │
                     │  ┌────────▼──────────┐  │
                     │  │  should_continue   │  │
                     │  │  (条件边)          │  │
                     │  └──┬───────────┬────┘  │
                     │     │           │       │
                     │  "tools"    "end"       │
                     │     │           │       │
                     │  ┌──▼──────┐  ┌──▼────┐ │
                     │  │call_tool│  │ END   │ │
                     │  │执行工具  │  └───────┘ │
                     │  └──┬──────┘            │
                     │     │                   │
                     │     └──→ call_model (循  │
                     │          环)             │
                     └─────────────────────────┘
```

### 6.3 对话上下文管理

```
DB (MySQL)                    Runtime (Python)                    LLM (Ollama)
─────────                     ───────────────                    ────────────
                                          System Prompt
                                          ┌─────────────────┐
 Conversation 1                           │ 你是一个知识库助手... │
  ├─ Message 1 (user)                     ├─────────────────┤
  ├─ Message 2 (assistant) ──loading──→   │ 历史对话(滑动窗口)  │
  ├─ Message 3 (user)                     │ 保留最近 20 轮     │
  ├─ Message 4 (assistant)               │ (40条) / 8192 tok │
  └─ Message 5 (user)  ← 新问题          ├─────────────────┤
                                          │ RAG 检索结果       │
                                          │ [来源1] [来源2]   │
                                          ├─────────────────┤
                                          │ 当前问题          │
                                          └───────┬─────────┘
                                                  │
                                          ┌───────▼─────────┐
                                          │  LLM Response    │
                                          └─────────────────┘
                                                  │
                                          ┌───────▼─────────┐
                                          │ 持久化到 DB      │
                                          │ Message 6 (user) │
                                          │ Message 7 (asst) │
                                          └─────────────────┘
```

---

## 7. SSE 事件架构

```
┌──────────┐            ┌──────────┐            ┌──────────┐            ┌──────────┐
│  前端     │            │  Uvicorn  │            │  Redis   │            │  Worker  │
│  Browser  │            │  Worker  │            │          │            │  (解析)   │
└─────┬─────┘            └─────┬─────┘            └────┬─────┘            └────┬─────┘
      │                        │                       │                       │
      │  GET /documents/       │                       │                       │
      │  {id}/progress-pubsub  │                       │                       │
      │───────────────────────►│                       │                       │
      │                        │                       │                       │
      │                        │  SUBSCRIBE            │                       │
      │                        │  doc:progress:{id}    │                       │
      │                        │──────────────────────►│                       │
      │                        │                       │                       │
      │                        │  ← SSE 连接建立        │                       │
      │◄───────────────────────┤                       │                       │
      │                        │                       │                       │
      │  ← POST /documents/    │                       │                       │
      │    upload (另一请求)     │                       │                       │
      │◄───────────────────────┤                       │                       │
      │                        │                       │                       │
      │                        │  上传成功 → 调度解析    │                       │
      │                        │──────────────────────────────────────────────►│
      │                        │                       │                       │
      │                        │                       │  PUBLISH(parsing)     │
      │                        │                       │◄──────────────────────┤
      │                        │  ← RECEIVE(parsing)   │                       │
      │  event: progress       │◄──────────────────────┤                       │
      │  {stage: "parsing"}   │                       │                       │
      │◄───────────────────────┤                       │                       │
      │                        │                       │  PUBLISH(chunking)    │
      │                        │                       │◄──────────────────────┤
      │  event: progress       │  ← RECEIVE(chunking)  │                       │
      │  {stage: "chunking"}  │◄──────────────────────┤                       │
      │◄───────────────────────┤                       │                       │
      │                        │                       │  PUBLISH(indexing)    │
      │                        │                       │◄──────────────────────┤
      │  event: progress       │  ← RECEIVE(indexing)  │                       │
      │  {stage: "indexing"}  │◄──────────────────────┤                       │
      │◄───────────────────────┤                       │                       │
      │                        │                       │  PUBLISH(done)        │
      │                        │                       │◄──────────────────────┤
      │  event: complete       │  ← RECEIVE(done)      │                       │
      │  {stage: "done"}      │◄──────────────────────┤                       │
      │◄───────────────────────┤                       │                       │
      │                        │                       │                       │
      │  ← UNSUBSCRIBE         │                       │                       │
      │    + pubsub.close()    │                       │                       │
      │◄───────────────────────┤                       │                       │
```

### 后端依赖注入与工具闭包

```
┌─────────────────────────────────────────────────────────────────────┐
│                      AgentService 实例                              │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  self.db: AsyncSession       ← 构造时注入                     │   │
│  │  self.kb_id / self.user_id   ← chat() 时设置                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                           │                                        │
│                           ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  _build_tools() — 闭包注入                                   │   │
│  │                                                             │   │
│  │  def create_retrieve_knowledge_tool(db, kb_id, user_id):   │   │
│  │      @tool                                                   │   │
│  │      async def retrieve_knowledge(question, top_k=5):       │   │
│  │          # db, kb_id, user_id 来自闭包，不在 State 中        │   │
│  │          results = await HybridSearchService.search(        │   │
│  │              db, kb_id, question, user, top_k               │   │
│  │          )                                                   │   │
│  │          return [r.model_dump(mode="json") for r in results] │   │
│  │      return retrieve_knowledge                               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                           │                                        │
│                           ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  LangGraph StateGraph                                       │   │
│  │  AgentState: {messages, kb_id, user_id, sources,            │   │
│  │               tool_calls_log}  ← 不放 db session             │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. 认证体系

```
┌─────────────────────────────────────────────────────────────────────┐
│                        认证方式                                      │
│                                                                     │
│  ┌─────────────────────┐   ┌───────────────────┐                   │
│  │   JWT Bearer Token  │   │   X-API-Key       │                   │
│  │   Authorization:    │   │   X-API-Key:       │                   │
│  │   Bearer eyJ...     │   │   sk-intellikb-... │                   │
│  └─────────┬───────────┘   └─────────┬─────────┘                   │
│            │                         │                             │
│            ▼                         ▼                             │
│  ┌───────────────────────────────────────────────┐                 │
│  │  depends/auth.py → get_current_user()          │                 │
│  │  - 先尝试 JWT (access_token)                    │                 │
│  │  - 再尝试 API Key (bcrypt 验证)                 │                 │
│  │  - SSE 端点: get_current_user_cookie()          │                 │
│  │    (从 Cookie: access_token 读取)               │                 │
│  └───────────────────────────────────────────────┘                 │
│                                                                     │
│  ┌─────────────────────┐   ┌───────────────────┐                   │
│  │   Access Token      │   │   Refresh Token   │                   │
│  │   30分钟有效期       │   │   7天有效期         │                   │
│  │   JWT + jti         │   │   单次使用         │                   │
│  └─────────────────────┘   └───────────────────┘                   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Blacklist 机制: Redis SET jti → exp_timestamp              │   │
│  │  - 登出时加入黑名单                                           │   │
│  │  - Refresh 时: 传 current_access_token → 撤销单点;           │   │
│  │             不传 → 批量撤销该用户所有 access                   │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 9. 会话与序列图

### Agent 流式对话时序

```
Browser                      FastAPI                      AgentService              LangGraph           Ollama
  │                            │                            │                        │                    │
  │  POST /agent/chat-stream   │                            │                        │                    │
  │  {kb_id, question, ...}   │                            │                        │                    │
  │──────────────────────────►│                            │                        │                    │
  │                            │  chat_stream()            │                        │                    │
  │                            │──────────────────────────►│                        │                    │
  │                            │                            │  1. 校验 KB 权限       │                    │
  │                            │                            │  2. 创建/获取对话      │                    │
  │                            │                            │  3. 装载历史+截断      │                    │
  │                            │                            │  4. 构造初始 State     │                    │
  │                            │                            │                        │                    │
  │                            │   event: thought          │  5. astream()          │                    │
  │◄───────────────────────────┤   "正在检索..."            │───────────────────────►│                    │
  │                            │                            │                        │                    │
  │                            │                            │    call_tool node      │                    │
  │                            │                            │    retrieve_knowledge   │                    │
  │                            │                            │◄───────────────────────┤                    │
  │                            │                            │──────────────────────────────────────────────►│
  │                            │                            │                        │                    │
  │   event: tool_call         │                            │                        │                    │
  │◄───────────────────────────┤                            │                        │                    │
  │   event: tool_result       │                            │                        │                    │
  │◄───────────────────────────┤                            │                        │                    │
  │   event: sources           │                            │                        │                    │
  │◄───────────────────────────┤                            │                        │                    │
  │                            │                            │    call_model node     │                    │
  │                            │                            │───────────────────────►│───────────────────►│
  │                            │                            │◄───────────────────────│◄───────────────────│
  │   data: "回答内容..."       │                            │                        │                    │
  │◄───────────────────────────┤                            │                        │                    │
  │                            │                            │  6. 持久化 user+assist  │                    │
  │   event: done              │                            │                        │                    │
  │◄───────────────────────────┤                            │                        │                    │
```

---

## 10. 目录结构

```
IntelliKB/
├── app/                          # 后端 FastAPI 应用
│   ├── main.py                   # FastAPI 入口 + lifespan
│   ├── config.py                 # Pydantic Settings
│   ├── core/                     # 核心基础设施 (DB/Redis/JWT/中间件/日志)
│   ├── models/                   # SQLAlchemy ORM 模型 (12 张表)
│   ├── schemas/                  # Pydantic 请求/响应
│   ├── repositories/             # 数据访问层
│   ├── services/                 # 业务逻辑层 (22 个服务)
│   ├── agent/                    # LangGraph Agent (graph + tools)
│   ├── api/v1/                   # REST API 路由 (9 个模块)
│   │   ├── auth.py / knowledge_bases.py / documents.py / qa.py / agent_chat.py
│   │   ├── conversations.py / members.py / admin.py / eval.py / health.py
│   └── depends/                  # FastAPI 依赖注入
├── frontend/                     # Vue 3 SPA 前端
│   └── src/
│       ├── api/                  # API 封装 (10 个模块)
│       ├── components/           # UI 组件 (11 个 .vue)
│       ├── views/                # 页面 (12 个 .vue，含 admin)
│       ├── store/                # Pinia 状态管理
│       ├── router/               # Vue Router
│       ├── types/                # TypeScript 类型
│       └── utils/                # Axios 封装 / 工具函数
├── alembic/                      # 数据库迁移 (10 个版本)
├── docs/                         # 文档 (25+ 篇)
├── scripts/                      # 工具脚本 (init / download_reranker 等)
├── tests/                        # 单元 + 集成测试 (111 用例)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

> 注：完整文件列表请直接查看源码；本结构图只展示高层组织。

---

## 附录: 关键决策记录

|   ADR   | 决策                                           | 文件                                                   |
| :-----: | ---------------------------------------------- | ------------------------------------------------------ |
| ADR-001 | API Key 验证性能技术债                         | [docs/adr/001-tech-debt.md](docs/adr/001-tech-debt.md) |
|   D1    | Agent 框架选择 LangGraph 0.2.x                 | [docs/phase3-plan.md](#d1-agent-框架)                  |
|   D2    | 对话存储用 Conversation + Message 两张表       | [docs/phase3-plan.md](#d2-对话存储)                    |
|   D3    | 工具集从 2 个简化为 1 个（retrieve_knowledge） | [本文 6.1](#61-当前架构phase-3-简化版)                 |
|   D4    | SSE 多 Worker 用 Redis Pub/Sub                 | [docs/phase3-plan.md](#d4-sse-多-worker-升级)          |
|   D5    | 多轮上下文滑动窗口 20 轮 / 8192 tokens         | [docs/phase3-plan.md](#d5-多轮上下文窗口)              |
