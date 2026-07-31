# IntelliKB Phase 2 —— 异步处理 + 混合检索 + 流式生成 实施计划

## 修订历史

| 版本 | 日期 | 修订人 | 主要内容 |
|------|------|--------|----------|
| v1.0 | 2026-07-29 | Claude | 初版计划 |
| v1.1 | 2026-07-29 | Claude | S1 SSE 认证(cookie/fetch) / S2 流式问答 GET / S3 sentence-transformers 版本 / M1 jieba / M2 懒加载索引 / M3 marked+dompurify / M4 downgrade / M5 history 格式 / O1-O5 |

---

## 0. 前置条件与关键决策

### 0.1 Phase 1 已有基础

| 组件 | 状态 | 说明 |
|------|:--:|------|
| KnowledgeBase CRUD | ✅ | `sys_kb` 表 + per-KB Chroma Collection |
| Document 上传/解析/分块/向量化 | ✅ | 同步处理，4 种格式支持 (PDF/DOCX/MD/TXT) |
| RAG 检索 + 问答 | ✅ | POST `/qa/search` + POST `/qa/ask`，非流式 |
| JWT + API Key 双认证 | ✅ | `get_current_user_or_api_key` 依赖 |
| SoftDeleteMixin 三层软删除 | ✅ | KB → Document → Chunk |
| ChromaDB per-KB Collection | ✅ | `kb_{kb_id}` 命名，`asyncio.to_thread()` 包装 |
| Embedding (nomic-embed-text 768d) | ✅ | 通过 Ollama 兼容 API |
| 前端: 布局壳 + KB 管理 + QA 页 | ✅ | Vue 3 + Element Plus |
| 统一响应/异常/trace_id | ✅ | `APIResponse` + `AppException` + `TraceIdVar` |

### 0.2 Phase 2 新增能力一览

```
Phase 1:
  上传 → 同步解析(阻塞) → 分块 → 向量化 → 返回
  检索 → Embedding → Chroma Top-K → [可选] LLM 拼接 → JSON

Phase 2:
  上传 → BackgroundTasks 异步解析 → SSE 进度推送 → 完成
  检索 → Query Rewrite(可选) → BM25 + 向量混合检索 → RRF 融合
       → Cross-encoder Rerank → Redis 缓存 → LLM SSE 流式生成 → 打字效果
  权限 → KBMember(owner/editor/viewer) → 多级访问控制
```

### 0.3 关键决策（5 项）

#### D1: SSE 进度推送技术方案

| 候选方案 | 优势 | 劣势 | 结论 |
|---------|------|------|:--:|
| **SSE (StreamingResponse)** | FastAPI 原生支持，HTTP/1.1 兼容，单向推送足够 | 需客户端 EventSource 监听 | ✅ 选用 |
| WebSocket | 双向通信，低延迟 | 重协议，握手开销大，进度推送不需要双向 | ❌ |
| 轮询 (Polling) | 最简单，无连接管理 | 延迟高，浪费带宽 | ❌ 备选（前端降级用） |

**决定**：**SSE via `StreamingResponse`**。

- 进度数据通过 Redis key `doc:progress:{doc_id}` 中转（JSON: `{stage, progress, message}`）
- BackgroundTask 写入 Redis → SSE 端点定时读取 Redis 并 yield
- **S1 认证方式**：标准 `EventSource` API 不支持自定义请求头（如 `Authorization`），因此 SSE 端点采用以下方案之一：
  - **Cookie-based 认证**（推荐）：在 `app/main.py` 中间件中配置 `SameSite=Lax` cookie，登录后将 JWT 写入 cookie。SSE 端点通过 cookie 自动携带认证信息，前端 `EventSource` 可直接连接。
  - **fetch + ReadableStream**（现代方案）：前端使用 `fetch()` API（支持自定义 header）+ `ReadableStream` 手动解析 SSE 流。不依赖 `EventSource`，但需更多前端代码。
  - Phase 2 选择 **Cookie 方案**：登录时后端通过 `Set-Cookie` 下发 JWT（HttpOnly, SameSite=Lax），SSE 连接自动携带。
- 前端 `EventSource` 自动重连
- 心跳间隔 15s（复用 `SSE_HEARTBEAT_INTERVAL` 配置）

#### D2: BM25 全文检索实现

| 候选方案 | 优势 | 劣势 | 结论 |
|---------|------|------|:--:|
| **rank_bm25** | 纯 Python，零依赖，轻量 (<500 行) | 内存索引，重启需重建 | ✅ 选用 |
| whoosh | 纯 Python，支持磁盘索引 | API 复杂，维护停滞 | ❌ |
| SQLite FTS5 | 内置全文检索，SQL 友好 | ChromaDB 已占用 SQLite，可能冲突 | ❌ |
| Elasticsearch | 生产级，分布式 | 太重，Phase 2 不需要 | ❌ (Phase 4) |

**决定**：**`rank_bm25`**（pip install rank-bm25）。

- **M2 懒加载**：首次查询时通过 `ensure_index()` 从 `sys_chunk` 表构建内存索引，后续查询复用
- 每 KB 独立 BM25 索引（与 per-KB Chroma Collection 对称）
- 文档增删时调用 `invalidate(kb_id)` 使索引失效，下次查询自动重建
- 规模上限：10K chunks/KB 以内性能可接受

#### D3: Rerank 模型选择

| 候选方案 | 模型规模 | 中文能力 | 部署方式 | 结论 |
|---------|:--:|:--:|------|:--:|
| **cross-encoder/ms-marco-MiniLM-L-6-v2** | 384 | 弱 | sentence-transformers 本地加载 | ✅ Phase 2 默认 |
| bge-reranker-base | 768 | 强 | sentence-transformers 本地加载 | 🟡 备选（中文场景） |
| bge-reranker-v2-m3 | 1024 | 强 | 更大更慢 | ❌ Phase 2 太重 |

**决定**：**`cross-encoder/ms-marco-MiniLM-L-6-v2`**，通过 `sentence-transformers` 加载。

- 配置项 `RERANK_MODEL` 可切换，默认 MiniLM-L-6-v2
- 通过 `asyncio.to_thread()` 异步化（sentence-transformers 同步 API）
- 首次加载 ~90MB 模型，后续推理 <50ms/pair
- 安装：`pip install sentence-transformers`

#### D4: Query Rewrite 实现方式

| 候选方案 | 优势 | 劣势 | 结论 |
|---------|------|------|:--:|
| **LLM 改写** | 灵活，处理复杂指代 | 增加延迟 (~500ms-2s) | ✅ 选用 |
| 规则模板 | 快 (<1ms)，可预测 | 覆盖面窄，无法处理复杂指代 | ❌ |
| 混合（规则优先 + LLM 兜底） | 平衡性能与效果 | 复杂度高 | ❌ Phase 2 过度设计 |

**决定**：**LLM-based Query Rewrite**，遵循架构文档 A14 设计。

- **M5 触发条件**：仅在 `history` 长度 ≥ 2（即存在一轮完整问答：user + assistant）时执行。单轮问题或无 assistant 回复的历史跳过，0 延迟
- 复用现有 `openai.AsyncOpenAI` 客户端 + `LLM_MODEL_NAME`
- 改写 LLM 调用设置 `temperature=0.1, max_tokens=256`（低温度 + 短输出）
- 改写结果缓存到 Redis：`qr:{md5(question+history)}`，TTL=300s
- 失败时降级为原始问题（不阻塞检索）

#### D5: RAG 缓存键设计

| 方案 | 键格式 | 粒度 | 结论 |
|------|------|------|:--:|
| **question + kb_id** | `rag:cache:{kb_id}:{md5(question)}` | 问题级 | ✅ 选用 |
| question + kb_id + top_k | `rag:cache:{kb_id}:{md5(question)}:{top_k}` | 过细 | ❌ 缓存命中率低 |
| 仅 question | `rag:cache:{md5(question)}` | 过粗 | ❌ 跨 KB 泄漏 |

**决定**：**`rag:cache:{kb_id}:{md5(question_lower_stripped)}`**

- 规范化 question（小写 + 去首尾空格）后计算 MD5
- TTL：`RAG_CACHE_TTL_SECONDS`（默认 3600s）
- 值：`SearchResponse` 的 JSON 序列化
- 失效策略：
  - 文档上传/删除 → `DELETE rag:cache:{kb_id}:*`（SCAN 匹配删除）
  - KB 删除 → 同上
  - 可通过 `RAG_CACHE_ENABLED=false` 全局关闭

---

## 1. 依赖扩展

### 1.1 requirements.txt 追加

```text
# ── Phase 2: 混合检索 + Rerank + 流式 ──
rank-bm25>=0.2,<1.0           # BM25 检索
sentence-transformers>=2.3,<3.0  # S3: Cross-encoder Rerank 模型 (2.7.0 确认可用)
jieba>=0.42.1                  # M1: 中文分词，BM25 索引构建用
```

> **依赖说明**：
> - `rank-bm25`：纯 Python BM25 实现，无额外依赖
> - `sentence-transformers`：S3 锁定 2.x 系列（`>=2.3,<3.0`，最新 2.7.0），加载 cross-encoder 模型进行 Rerank，首次运行自动下载模型 (~90MB)
> - `jieba`：M1 中文分词，`BM25Service.build_index()` 使用 jieba.cut 对中文文本分词
> - 其余功能（SSE、Redis 缓存、Query Rewrite）复用现有依赖

### 1.2 模型准备

```bash
# Rerank 模型首次运行时自动下载，也可手动预下载:
python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"
```

---

## 2. 数据模型变更

### 2.1 新增：KBMember（知识库成员）

```sql
-- 知识库成员
CREATE TABLE sys_kb_member (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kb_id INT NOT NULL COMMENT '知识库 ID',
    user_id INT NOT NULL COMMENT '用户 ID',
    role ENUM('owner','editor','viewer') NOT NULL DEFAULT 'viewer' COMMENT '角色',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_kbm_kb_user (kb_id, user_id),
    INDEX idx_kbm_user (user_id),
    CONSTRAINT fk_kbm_kb FOREIGN KEY (kb_id) REFERENCES sys_kb(id) ON DELETE CASCADE,
    CONSTRAINT fk_kbm_user FOREIGN KEY (user_id) REFERENCES sys_user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库成员';
```

**角色权限矩阵**：

| 操作 | owner | editor | viewer |
|------|:---:|:---:|:---:|
| 查看 KB 详情 | ✅ | ✅ | ✅ |
| 编辑 KB 元信息 | ✅ | ✅ | ❌ |
| 删除 KB | ✅ | ❌ | ❌ |
| 上传文档 | ✅ | ✅ | ❌ |
| 删除文档 | ✅ | ✅ | ❌ |
| 管理成员 | ✅ | ❌ | ❌ |
| RAG 检索/问答 | ✅ | ✅ | ✅ |

### 2.2 已有表变更

**sys_document** — 无需 DDL 变更。`status` 字段已支持所有阶段：
- 已有: `uploading` → `parsing` → `chunking` → `indexing` → `done` → `error`
- Phase 2: 同上，但各阶段由 BackgroundTask 异步推进 + SSE 通知

**sys_kb** — 无需 DDL 变更。`owner_id` 保持不变，KBMember 表补充权限。

### 2.3 SQLAlchemy 模型（新增/修改）

**新增 `app/models/kb_member.py`**：
- 继承 `Base, TimestampMixin`（成员关系不可软删除，删除即真删）
- `kb_id: Mapped[int]`, `user_id: Mapped[int]`, `role: Mapped[str]`（owner/editor/viewer）

**修改 `app/models/__init__.py`**：追加 `KBMember` 导入

**修改 `app/services/kb_service.py`**：
- `create()` → 自动添加 owner 为 KBMember（role='owner'）
- `get_accessible()` → 校验 owner / 公开 / KBMember 三类权限

---

## 3. 后端 API 设计

### 3.1 新增/变更端点

| 方法 | 路径 | 说明 | 权限 | 变更类型 |
|------|------|------|------|:--:|
| `POST` | `/api/v1/documents/upload` | 上传文档 → BackgroundTasks 异步解析 | kb owner/editor | 🔄 修改 |
| `GET` | `/api/v1/documents/{doc_id}/progress` | SSE 文档解析进度 | kb owner/editor | 🆕 新增 |
| `POST` | `/api/v1/qa/hybrid-search` | BM25 + 向量混合检索 → RRF 融合 | kb 成员/public | 🆕 新增 |
| `POST` | `/api/v1/qa/ask` | RAG 问答（检索 + 非流式生成） | kb 成员/public | 🔄 增强 |
| `GET` | `/api/v1/qa/ask-stream` | RAG 问答（SSE 流式生成，query string 传参） | kb 成员/public | 🆕 新增 |
| `GET` | `/api/v1/knowledge-bases/{kb_id}/members` | 成员列表 | kb owner | 🆕 新增 |
| `POST` | `/api/v1/knowledge-bases/{kb_id}/members` | 添加成员 | kb owner | 🆕 新增 |
| `PUT` | `/api/v1/knowledge-bases/{kb_id}/members/{user_id}` | 修改成员角色 | kb owner | 🆕 新增 |
| `DELETE` | `/api/v1/knowledge-bases/{kb_id}/members/{user_id}` | 移除成员 | kb owner | 🆕 新增 |

### 3.2 端点详细设计

#### 3.2.1 文档上传（修改）

```
POST /api/v1/documents/upload

变更：
  Phase 1: 同步处理 → 返回 status='done'
  Phase 2: 创建 Document(status='uploading') → bg.add_task(parse) → 立即返回

响应：
  201 {"doc_id": N, "status": "uploading", "message": "文档已提交，正在后台解析"}

后续：
  前端调用 GET /documents/{doc_id}/progress (SSE) 监听进度
  也可 GET /documents/{doc_id} 查看当前状态
```

#### 3.2.2 SSE 进度推送（新增）

```
GET /api/v1/documents/{doc_id}/progress

Content-Type: text/event-stream

事件流格式：
  event: progress
  data: {"stage":"parsing","progress":0.25,"message":"正在提取文本..."}

  event: progress
  data: {"stage":"chunking","progress":0.50,"message":"已分 8 块..."}

  event: progress
  data: {"stage":"indexing","progress":0.75,"message":"正在生成向量..."}

  event: complete
  data: {"doc_id":N,"status":"done","chunk_count":8}

  event: error
  data: {"doc_id":N,"status":"error","message":"解析失败: PDF 损坏"}

实现：
  - **S1 认证**：SSE 端点采用 cookie-based 认证（JWT 通过 `Set-Cookie` 下发）。标准 `EventSource` 不支持自定义 `Authorization` header，因此依赖 cookie 自动携带。
    - 后端：登录接口在响应中设置 `Set-Cookie: access_token={jwt}; Path=/; HttpOnly; SameSite=Lax`
    - 前端：`new EventSource("/api/v1/documents/N/progress")` 自动携带 cookie
  - **O3 立即读取**：SSE 端点首次立即读取 Redis 一次，再进入轮询循环（间隔 1s），避免快速任务（<1s 完成）错过进度事件
  - BackgroundTask 在阶段切换时更新 Redis key `doc:progress:{doc_id}`
  - 客户端断开 → SSE 循环退出
  - 完成/错误后发送最终事件，30s 后清理 Redis key
  - 心跳：每 15s 发送 ": heartbeat\n\n"
```

#### 3.2.3 混合检索（新增）

```
POST /api/v1/qa/hybrid-search

Request:
  {"kb_id": 1, "question": "...", "top_k": 20, "rerank": true}

流程（含 Rerank）:
  1. Query Rewrite (有历史时)
  2. BM25 检索 → Top-20
  3. 向量检索 → Top-20
  4. RRF 融合 → Top-10
  5. [可选] Cross-encoder Rerank → Top-5
  6. 返回 SearchResult[]

配置项:
  HYBRID_BM25_TOP_K=20      BM25 召回数
  HYBRID_VECTOR_TOP_K=20    向量召回数
  HYBRID_RRF_K=60            RRF 平滑参数
  HYBRID_RERANK_TOP_K=5     Rerank 后返回数
```

#### 3.2.4 SSE 流式问答（新增）— **S2: GET 方法**

```
GET /api/v1/qa/ask-stream?kb_id=1&question=...&top_k=5

Query Parameters:
  kb_id: int          知识库 ID
  question: str       用户问题（需 URL encode，最大 1000 字符）
  top_k: int=5        检索数量 (1-20)

Content-Type: text/event-stream

S2 设计理由：GET 方法允许前端直接使用 EventSource(url) 或 fetch(url) 发起连接，
无需在 body 中传递 JSON。参数通过 query string 传递，兼容 cookie 认证方案。

事件流格式：
  event: sources
  data: {"sources": [...]}           ← 先返回检索结果

  data: "FastAPI"                     ← SSE token 流（逐字）
  data: " 是"
  data: " 一个"
  ...

  event: done
  data: {"total_tokens": 42}         ← 生成完成

  event: error
  data: {"code":"STREAM_ERROR","message":"..."}

实现：
  - 使用 openai.AsyncOpenAI.chat.completions.create(stream=True)
  - async for chunk in response → yield token → SSE
  - 客户端断开 → 取消生成任务 (asyncio.Task.cancel)
  - 心跳：每 15s 发送 ": heartbeat\n\n"（无 token 输出时）
  - 兼容 error 事件（S4 降级 + SSE error 事件二选一）
```

#### 3.2.5 成员管理（新增 4 端点）

```
GET    /knowledge-bases/{kb_id}/members
       → 200 {"members": [{user_id, username, role}, ...]}
       权限: owner

POST   /knowledge-bases/{kb_id}/members
       body: {"user_id": N, "role": "editor"}
       → 201 {"user_id": N, "role": "editor"}
       权限: owner
       校验: 不能添加不存在的用户 / 不能重复添加

PUT    /knowledge-bases/{kb_id}/members/{user_id}
       body: {"role": "viewer"}
       → 200
       权限: owner
       限制: 不能修改自己的 role（至少保留一个 owner）

DELETE /knowledge-bases/{kb_id}/members/{user_id}
       → 200
       权限: owner
       限制: 不能移除自己（owner）
```

### 3.3 权限变更

**修改 `KBService.get_accessible()`**：
```python
async def get_accessible(self, kb_id: int, user_id: int) -> KnowledgeBase:
    kb = await self.get(kb_id)           # 基础校验（存在）
    if kb.owner_id == user_id:           # owner 全权限
        return kb
    if kb.is_public:                     # 公开 KB 可读
        return kb
    # Phase 2 新增: 检查 KBMember 表
    member = await self.member_repo.get_by_kb_and_user(kb_id, user_id)
    if member is not None:
        return kb
    raise ForbiddenError("无权访问该知识库")
```

**新增 `KBService.get_editable()`**：
```python
async def get_editable(self, kb_id: int, user_id: int) -> KnowledgeBase:
    kb = await self.get(kb_id)
    if kb.owner_id == user_id:
        return kb
    member = await self.member_repo.get_by_kb_and_user(kb_id, user_id)
    if member and member.role in ("owner", "editor"):
        return kb
    raise ForbiddenError("无权编辑该知识库")
```

---

## 4. Core 服务设计

### 4.1 服务架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Layer                                 │
│  /documents/upload   /qa/hybrid-search   /qa/ask-stream         │
└──────────┬──────────────────┬────────────────────┬──────────────┘
           │                  │                    │
           ▼                  ▼                    ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  DocService      │ │ HybridSearch     │ │ StreamingAsk     │
│  (async upload)  │ │ Service          │ │ Service          │
│  + ProgressMgr   │ │                  │ │ (SSE yield)      │
└────────┬─────────┘ └───────┬──────────┘ └────────┬─────────┘
         │                   │                     │
         ▼                   ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Retrieval Pipeline                           │
│                                                                  │
│  QueryRewriter ──► BM25Retriever ──┐                            │
│                   VectorRetriever ─┤─ RRF Merger ──► Reranker   │
│                                    │                             │
│                   Redis Cache ◄────┘                             │
└─────────────────────────────────────────────────────────────────┘
         │                                       │
         ▼                                       ▼
┌──────────────┐                          ┌──────────────┐
│  Redis       │                          │  Ollama LLM  │
│  (cache +    │                          │  (生成)       │
│   progress)  │                          └──────────────┘
└──────────────┘
```

### 4.2 ProgressManager（`app/services/progress_manager.py`）

```python
class ProgressManager:
    """文档解析进度管理 —— 通过 Redis key 中转"""

    PROGRESS_KEY = "doc:progress:{doc_id}"
    PROGRESS_TTL = 300  # 5 分钟自动清理

    async def set(self, doc_id: int, stage: str, progress: float, message: str):
        """写入进度"""
        data = json.dumps({"stage": stage, "progress": progress, "message": message})
        await cache_set(self.PROGRESS_KEY.format(doc_id=doc_id), data, ttl=self.PROGRESS_TTL)

    async def get(self, doc_id: int) -> dict | None:
        """读取进度"""
        raw = await cache_get(self.PROGRESS_KEY.format(doc_id=doc_id))
        return json.loads(raw) if raw else None

    async def clear(self, doc_id: int):
        """清理进度 key"""
        await cache_delete(self.PROGRESS_KEY.format(doc_id=doc_id))
```

### 4.3 BM25Service（`app/services/bm25_service.py`）

```python
class BM25Service:
    """BM25 全文检索 —— rank_bm25 内存索引，per-KB 独立"""

    def __init__(self):
        self._indices: dict[int, tuple[BM25Okapi, list[str], list[int]]] = {}
        # {kb_id: (bm25_model, tokenized_corpus, chunk_ids)}

    async def build_index(self, kb_id: int, db: AsyncSession):
        """
        M2: 从 sys_chunk (WHERE deleted_at IS NULL) 读取所有 chunk 构建索引。
        仅在 ensure_index() 发现索引不存在时调用，不随应用启动执行。
        """
        ...

    async def search(self, kb_id: int, query: str, top_k: int = 20) -> list[dict]:
        """BM25 检索 → [{chunk_id, content, score}, ...]"""
        ...

    def invalidate(self, kb_id: int):
        """M2: 失效内存索引（文档变更时调用）。下次 ensure_index() 自动重建。"""
        ...

    async def ensure_index(self, kb_id: int, db: AsyncSession):
        """M2 懒加载入口：索引不存在则构建，存在则复用。"""
        ...
```

> **索引构建**：
> - **M2 时机**：不随应用启动构建，统一使用懒加载模式。首次 `search()` 时调用 `ensure_index()` 按需构建，后续复用内存索引
> - **M1 分词**：中文分词用 `jieba.cut()`（`jieba>=0.42.1`），英文用空格分词 + 小写。构建时通过 `asyncio.to_thread()` 异步化
> - **失效重建**：文档上传/删除 → `invalidate(kb_id)` → 下次查询 `ensure_index()` 自动重建

### 4.4 HybridSearchService（`app/services/hybrid_search_service.py`）

```python
class HybridSearchService:
    """BM25 + 向量混合检索 + RRF 融合 + Rerank"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.bm25 = bm25_service
        self.vector = vector_store_service
        self.reranker = rerank_service
        self.cache = rag_cache_service

    async def search(
        self, kb_id: int, question: str, top_k: int = 5,
        use_rerank: bool = True, use_cache: bool = True,
        history: list[dict] | None = None,
    ) -> list[SearchResult]:
        """
        完整检索管线:
        1. [可选] Query Rewrite (有历史时)
        2. [可选] Redis 缓存命中 → 直接返回
        3. 并行 BM25 (top_k*4) + Vector (top_k*4)
        4. RRF 融合 → top_k*2
        5. [可选] Cross-encoder Rerank → top_k
        6. [可选] 写入 Redis 缓存
        """
        ...

    @staticmethod
    def _rrf_fusion(
        bm25_results: list[dict], vector_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion:
        score(chunk) = Σ 1/(k + rank_in_list)
        """
        ...
```

### 4.5 RerankService（`app/services/rerank_service.py`）

```python
class RerankService:
    """Cross-encoder Rerank"""

    def __init__(self):
        self._model: CrossEncoder | None = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            self._model = CrossEncoder(settings.RERANK_MODEL)
        return self._model

    async def rerank(
        self, question: str, chunks: list[dict], top_k: int = 5
    ) -> list[dict]:
        """
        对候选 chunks 做 cross-encoder 重排序。
        chunks: [{content, chunk_id, ...}, ...]
        返回: 按 rerank_score 降序的前 top_k 个
        """
        pairs = [(question, c["content"]) for c in chunks]
        scores = await asyncio.to_thread(
            self.model.predict, pairs, show_progress_bar=False
        )
        # 按分数降序排列
        for i, c in enumerate(chunks):
            c["rerank_score"] = float(scores[i])
        ranked = sorted(chunks, key=lambda x: x.get("rerank_score", 0), reverse=True)
        return ranked[:top_k]
```

### 4.6 QueryRewriteService（`app/services/query_rewrite_service.py`）

```python
class QueryRewriteService:
    """LLM-based 查询改写（架构文档 A14）"""

    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL.rstrip("/"),
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        self.model = settings.LLM_MODEL_NAME

    async def rewrite(self, question: str, history: list[dict] | None = None) -> str:
        """
        D4 + M5: 仅在 history 长度 ≥ 2（存在完整问答轮次）时执行。

        M5 history 格式:
        [
          {"role": "user", "content": "原始问题"},
          {"role": "assistant", "content": "上一轮回答"},
          {"role": "user", "content": "追问（需改写）"}
        ]
        最后一条 message.role 必须为 "user"（当前问题）。

        失败或超时时返回原始 question（降级，不阻塞检索）。
        """
        ...
```

### 4.7 RAGCacheService（`app/services/rag_cache_service.py`）

```python
class RAGCacheService:
    """RAG 检索结果 Redis 缓存（D5）"""

    KEY_PREFIX = "rag:cache"

    def _key(self, kb_id: int, question: str) -> str:
        normalized = question.strip().lower()
        return f"{self.KEY_PREFIX}:{kb_id}:{hashlib.md5(normalized.encode()).hexdigest()}"

    async def get(self, kb_id: int, question: str) -> list[dict] | None:
        if not settings.RAG_CACHE_ENABLED:
            return None
        raw = await cache_get(self._key(kb_id, question))
        return json.loads(raw) if raw else None

    async def set(self, kb_id: int, question: str, results: list[dict]):
        if not settings.RAG_CACHE_ENABLED:
            return
        await cache_set(
            self._key(kb_id, question),
            json.dumps(results, ensure_ascii=False),
            ttl=settings.RAG_CACHE_TTL_SECONDS,
        )

    async def invalidate(self, kb_id: int):
        """
        文档变更时失效该 KB 所有缓存（SCAN 匹配删除）。

        O4: 文档上传/删除时异步调用 invalidate()，不阻塞主流程。
        调用方使用 asyncio.create_task() 或 bg.add_task() 触发。
        """
        r = await get_redis()
        pattern = f"{self.KEY_PREFIX}:{kb_id}:*"
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=pattern, count=100)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
```

### 4.8 重构 DocService（异步解析）

```python
class DocService:
    """文档生命周期管理 —— Phase 2 异步版"""

    async def create_document_record(
        self, kb_id: int, file: UploadFile, user_id: int
    ) -> Document:
        """仅创建记录 + 保存文件，不解析。返回 Document 供 bg.add_task 使用。"""
        # 校验 → 保存文件 → 创建记录 (status='uploading') → 返回
        ...

    async def parse_document_async(self, doc_id: int):
        """
        BackgroundTask 入口。
        逐步推进 status: uploading → parsing → chunking → indexing → done/error
        每阶段更新 Redis progress key。
        """
        ...
```

---

## 5. Schemas 设计

### 5.1 新增 Schemas

```python
# ── 成员管理 ──
class MemberAdd(BaseModel):
    user_id: int
    role: str = Field(default="viewer", pattern="^(editor|viewer)$")

class MemberUpdate(BaseModel):
    role: str = Field(pattern="^(editor|viewer)$")

class MemberResponse(BaseModel):
    user_id: int
    username: str
    role: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# ── SSE 进度 ──
class ProgressEvent(BaseModel):
    stage: str       # uploading/parsing/chunking/indexing/done/error
    progress: float  # 0.0 ~ 1.0
    message: str

# ── 混合检索 ──
class HybridSearchRequest(BaseModel):
    kb_id: int
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)
    use_rerank: bool = True
    # M5 history 格式: [{"role":"user","content":"..."}, {"role":"assistant","content":"..."}, {"role":"user","content":"..."}]
    # 仅当 len(history) >= 2 时触发 Query Rewrite
    history: list[dict] | None = None

class HybridSearchResponse(BaseModel):
    results: list[SearchResult]    # 复用 Phase 1 SearchResult
    rewritten_query: str | None = None  # 展示改写后的查询（调试用）

# ── 流式问答（S2: GET 方法，使用 Query 参数而非 Body）──
# GET /qa/ask-stream?kb_id=1&question=...&top_k=5
# 参数由 FastAPI 的 Query() 声明，无需 Pydantic Body model
# 客户端使用 EventSource 或 fetch(url) 直接连接

# ── 流式事件（用于 SSE data JSON 序列化）──
class StreamSourceEvent(BaseModel):
    sources: list[SearchResult]

class StreamDoneEvent(BaseModel):
    total_tokens: int

class StreamErrorEvent(BaseModel):
    code: str
    message: str
```

---

## 6. Repository 设计

### 6.1 KBMemberRepository（新增）

```python
class KBMemberRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_kb_and_user(self, kb_id: int, user_id: int) -> KBMember | None
    async def list_by_kb(self, kb_id: int) -> list[KBMember]
    async def list_by_user(self, user_id: int) -> list[KBMember]
    async def create(self, data: dict) -> KBMember
    async def update(self, member: KBMember) -> KBMember
    async def delete(self, member: KBMember) -> None
    async def count_by_kb(self, kb_id: int) -> int
```

---

## 7. 前端页面/组件设计

### 7.1 新增/修改文件清单

```
frontend/
  package.json                 ← 🔄 M3: 新增 marked + dompurify 依赖
  src/
    components/
      ProgressBar.vue          ← 🆕 SSE 进度条组件
      StreamingText.vue        ← 🆕 流式文本打字效果 (marked + dompurify)
      MemberManager.vue        ← 🆕 成员管理面板
    views/
      qa/
        QAPage.vue             ← 🔄 升级: 流式回答 + 历史记录
    api/
      member.ts                ← 🆕 成员管理 API
    store/
      qa.ts                    ← 🆕 QA 状态管理（对话历史）
    types/
      index.ts                 ← 🔄 追加 Phase 2 类型
```

### 7.2 ProgressBar.vue（进度条组件）

```
S1 认证方案（cookie-based）:
  - JWT 通过登录接口的 Set-Cookie 下发（HttpOnly, SameSite=Lax）
  - 前端 new EventSource("/api/v1/documents/N/progress") 自动携带 cookie
  - 无需手动设置 Authorization header

功能:
  - 通过 EventSource 连接 GET /documents/{doc_id}/progress（cookie 自动认证）
  - 显示阶段文字 + 百分比进度条
  - 完成时 emit('done', doc_id)
  - 错误时 emit('error', message)
  - 支持"上传中 → 解析中 → 分块中 → 索引中 → 完成" 5 阶段动画
  - 自动重连（EventSource 内置）
```

### 7.3 StreamingText.vue（流式文本组件）

```
S2 连接方式（GET + cookie）:
  - const url = `/api/v1/qa/ask-stream?kb_id=${kb_id}&question=${encodeURIComponent(q)}&top_k=5`
  - 使用 fetch(url) + ReadableStream 手动解析 SSE（可自定义 headers）
  - 或使用 EventSource(url) 自动携带 cookie（cookie 认证方案下无需额外 header）

功能:
  - 打字机效果逐字渲染
  - 先展示参考来源（event: sources），再逐步显示回答（data: token）
  - 中断按钮（AbortController）
  - M3 Markdown 渲染: 使用 marked + dompurify
    - frontend/package.json 新增依赖: "marked": "^15.0.0", "dompurify": "^3.2.0"
    - marked 将 Markdown 转为 HTML，dompurify 过滤 XSS
  - 完成后平滑过渡到完整回答
```

### 7.4 MemberManager.vue（成员管理面板）

```
功能:
  - 成员列表表格（用户名、角色、添加时间）
  - 添加成员对话框（输入用户名 → 选择角色 → 确认）
  - 修改角色下拉
  - 移除成员确认
  - 仅 KB owner 可见
```

### 7.5 QAPage.vue（升级）

```
Phase 2 新增:
  - 切换开关: "精确检索" / "混合检索" / "流式问答"
  - 结果区支持三种模式:
    1. 精确检索: Phase 1 已有（纯向量）
    2. 混合检索: 调用 /qa/hybrid-search，展示 RRF 融合结果
    3. 流式问答: 调用 /qa/ask-stream，StreamingText 打字效果
  - 对话历史面板（可折叠）
  - 空状态: "输入问题开始对话"
  - 知识库选择器移到侧边栏（减少页面切换）
```

### 7.6 KBDetail.vue（升级）

```
Phase 2 新增:
  - 成员管理标签页（el-tabs: "文档列表" / "成员管理"）
  - 上传进度实时显示（ProgressBar 组件）
  - 上传后不再阻塞等待，显示进度条即可
```

---

## 8. 配置文件变更

### 8.1 config.py 追加

```python
# ── Phase 2: 混合检索 ──
HYBRID_BM25_TOP_K: int = 20
HYBRID_VECTOR_TOP_K: int = 20
HYBRID_RRF_K: int = 60
HYBRID_RERANK_TOP_K: int = 5

# ── Phase 2: Rerank ──
RERANK_ENABLED: bool = True
RERANK_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# ── Phase 2: Query Rewrite ──
QUERY_REWRITE_ENABLED: bool = True
QUERY_REWRITE_CACHE_TTL: int = 300
QUERY_REWRITE_MAX_TOKENS: int = 256

# ── Phase 2: SSE ──
SSE_HEARTBEAT_INTERVAL: int = 15       # 已存在
SSE_PROGRESS_POLL_INTERVAL: float = 1.0  # 进度轮询间隔（秒）
```

### 8.2 .env.example 追加

```ini
# ── Phase 2: 混合检索 ──
HYBRID_BM25_TOP_K=20
HYBRID_VECTOR_TOP_K=20
HYBRID_RRF_K=60
HYBRID_RERANK_TOP_K=5

# ── Phase 2: Rerank ──
RERANK_ENABLED=true
# cross-encoder/ms-marco-MiniLM-L-6-v2 (英文优化)
# BAAI/bge-reranker-base (中文优化，需 pip install 后自动下载)
RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2

# ── Phase 2: Query Rewrite ──
QUERY_REWRITE_ENABLED=true
```

---

## 9. alembic 迁移计划

```bash
# 单次迁移（仅新增 KBMember 表，无现有表变更）
alembic revision --autogenerate -m "phase2: sys_kb_member table"
alembic upgrade head
```

迁移内容：
1. 创建 `sys_kb_member` 表
2. 为已有 KB 的 owner 自动创建 KBMember 记录（data migration）

```python
# migration 的 upgrade() 中追加 data migration:
def upgrade():
    # ... create table ...
    # 为现有 KB 创建 owner member 记录
    op.execute("""
        INSERT INTO sys_kb_member (kb_id, user_id, role, created_at, updated_at)
        SELECT id, owner_id, 'owner', NOW(), NOW()
        FROM sys_kb
        WHERE deleted_at IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM sys_kb_member
            WHERE sys_kb_member.kb_id = sys_kb.id
            AND sys_kb_member.user_id = sys_kb.owner_id
        )
    """)

# M4: downgrade() 清理 data migration 创建的记录后删除表
def downgrade():
    op.execute("""
        DELETE FROM sys_kb_member
        WHERE role = 'owner'
        AND (kb_id, user_id) IN (
            SELECT id, owner_id FROM sys_kb WHERE deleted_at IS NULL
        )
    """)
    op.drop_table("sys_kb_member")
```

---

## 10. 文件创建/修改顺序

```
Phase 2 共需创建/修改 ~29 个文件：

 1. requirements.txt                          ← 追加 rank-bm25 + sentence-transformers
 2. app/config.py                             ← 追加混合检索/Rerank/QueryRewrite 配置
 3. .env.example                              ← 追加 Phase 2 配置项

 4. app/models/kb_member.py                   ← 🆕 KBMember 模型
 5. app/models/__init__.py                    ← 🔄 追加 KBMember 导入
 6. alembic revision --autogenerate           ← 自动生成迁移脚本
 7. alembic upgrade head                      ← 执行迁移

 8. app/repositories/kb_member.py             ← 🆕 KBMemberRepository
 9. app/schemas/member.py                     ← 🆕 Member schemas

10. app/services/progress_manager.py          ← 🆕 ProgressManager
11. app/services/bm25_service.py              ← 🆕 BM25Service
12. app/services/rerank_service.py            ← 🆕 RerankService
13. app/services/query_rewrite_service.py     ← 🆕 QueryRewriteService
14. app/services/rag_cache_service.py         ← 🆕 RAGCacheService
15. app/services/hybrid_search_service.py     ← 🆕 HybridSearchService

16. app/services/doc_service.py               ← 🔄 重构: create_record + parse_async
17. app/services/rag_service.py               ← 🔄 增强: 流式 ask_stream
18. app/services/kb_service.py                ← 🔄 增强: 成员权限

19. app/api/v1/documents.py                   ← 🔄 修改: async upload + SSE progress
20. app/api/v1/qa.py                          ← 🔄 增强: hybrid-search + ask-stream
21. app/api/v1/knowledge_bases.py             ← 🔄 新增: member CRUD 子路由

── 前端 8 files ──

22. frontend/src/components/ProgressBar.vue
23. frontend/src/components/StreamingText.vue
24. frontend/src/components/MemberManager.vue
25. frontend/src/views/qa/QAPage.vue          ← 🔄 升级
26. frontend/src/views/knowledge/KBDetail.vue ← 🔄 升级
27. frontend/src/api/member.ts
28. frontend/src/store/qa.ts
29. frontend/src/types/index.ts               ← 🔄 追加类型
```

---

## 11. 验证步骤

### 11.1 后端 API 验证 (V1-V8)

```bash
# ── 前置：登录 ──
TOKEN=...  # 获取 token

# ── V1: 异步上传文档 ──
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.md" -F "kb_id=1"
# → 201 {"doc_id": N, "status": "uploading", "message": "文档已提交，正在后台解析"}

# ── V2: SSE 进度监听 ──
curl -N http://localhost:8000/api/v1/documents/N/progress \
  -H "Authorization: Bearer $TOKEN"
# → event:progress → event:progress → ... → event:complete

# ── V3: 混合检索（有 Rerank）──
curl -X POST http://localhost:8000/api/v1/qa/hybrid-search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kb_id":1,"question":"什么是 FastAPI？","use_rerank":true}'
# → 200 {"results": [...], "rewritten_query": null}

# ── V4: 混合检索（多轮 + Query Rewrite）──
curl -X POST http://localhost:8000/api/v1/qa/hybrid-search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kb_id":1,"question":"它的特性是什么？","history":[{"role":"user","content":"什么是 FastAPI？"}]}'
# → 200 {"rewritten_query": "FastAPI 的特性是什么？", ...}

# ── V5: 流式问答（S2: GET + query string）──
curl -N "http://localhost:8000/api/v1/qa/ask-stream?kb_id=1&question=FastAPI%20%E6%9C%89%E5%93%AA%E4%BA%9B%E7%89%B9%E6%80%A7%EF%BC%9F&top_k=5" \
  -H "Authorization: Bearer $TOKEN"
# → event:sources → data:... → ... → event:done

# ── V6: 添加成员 ──
curl -X POST http://localhost:8000/api/v1/knowledge-bases/1/members \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":3,"role":"editor"}'
# → 201

# ── V7: 成员列表 ──
curl http://localhost:8000/api/v1/knowledge-bases/1/members \
  -H "Authorization: Bearer $TOKEN"
# → 200 {"members": [{"user_id":1,"username":"admin","role":"owner"}, ...]}

# ── V8: editor 上传文档 ──
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $EDITOR_TOKEN" \
  -F "file=@test2.md" -F "kb_id=1"
# → 201 (editor 权限通过)
```

### 11.2 缓存验证

```bash
# 第一次检索（未命中缓存，调用 Rerank）
curl ... /qa/hybrid-search ... -d '{"kb_id":1,"question":"test cache"}'
# → 200 (正常延迟)

# 第二次相同问题（命中缓存，跳过检索+Rerank）
curl ... /qa/hybrid-search ... -d '{"kb_id":1,"question":"test cache"}'
# → 200 (低延迟 <50ms)

# 上传新文档后缓存失效
curl ... /documents/upload ...
# 内部: DELETE rag:cache:1:*

# 第三次相同问题（缓存已失效，重新检索）
curl ... /qa/hybrid-search ... -d '{"kb_id":1,"question":"test cache"}'
# → 200 (正常延迟)
```

### 11.3 成员权限验证

| 测试场景 | 期望结果 |
|---------|:--:|
| owner 添加 editor | 201 |
| owner 添加 viewer | 201 |
| editor 上传文档 | 201 |
| editor 删除文档 | 200 |
| viewer 上传文档 | 403 |
| viewer 删除文档 | 403 |
| editor 管理成员 | 403 |
| 非成员访问私有 KB | 403 |
| 成员访问私有 KB | 200 |
| owner 修改自己的 role | 400（不允许）|

### 11.4 前端验证

```
1. 登录 → 创建 KB → 知识库详情页
2. 上传 PDF 文档 → 进度条动画 (uploading → parsing → chunking → indexing → done)
3. 进入 Q&A 页 → 选择"混合检索" → 输入问题 → 查看融合结果
4. 选择"流式问答" → 输入问题 → 打字机效果逐字显示
5. KB 详情页 → 成员管理标签 → 添加成员 → 修改角色 → 移除成员
6. 切换不同账号 → 验证权限
```

---

## 12. 风险与简化

### 12.1 风险

| 风险 | 影响 | 应对 |
|------|------|------|
| sentence-transformers 下载模型慢 | 首次 Rerank 超时 | 启动时预热下载（lifespan） |
| rank_bm25 内存占用 | 大 KB (>10K chunks) 占用高 | M2 懒加载 + 内存限制；失效重建而非预加载 |
| BackgroundTask 与 DB session 生命周期 | 任务中 session 已关闭 | 任务内部创建独立 session |
| Windows ProactorEventLoop SSE 稳定性 | 客户端断开未正确清理 | 心跳 + try/finally 清理 |
| Rerank 模型中文效果差 | 中文 KB 检索质量下降 | 配置切换 `BAAI/bge-reranker-base` |

### 12.2 简化项（故意推迟）

| 推迟项 | 计划阶段 | 理由 |
|--------|:--:|------|
| BM25 增量索引更新 | Phase 4 | 全量重建在 <10K chunks 时 <1s |
| Redis Pub/Sub 多 Worker 进度推送 | Phase 3 | Phase 2 单 Worker 用 Redis key 轮询足够 |
| 检索结果缓存共享（跨用户） | Phase 3 | Phase 2 仅简单 key-value |
| LangGraph Agent + Checkpointer | Phase 3 | 不在 Phase 2 范围内 |
| RAG 评测看板 | Phase 4 | 不在 Phase 2 范围内 |
| Conversations / Messages 表 | Phase 3 | Phase 2 在 QA 页前端维护临时历史 |

---

## 13. 验收标准

| # | 验收项 | 通过条件 |
|---|--------|---------|
| ✅1 | 异步文档上传 | 上传后立即返回 201，status='uploading' |
| ✅2 | SSE 进度推送 | 前端 EventSource 收到 4+ 阶段事件，最终 event:complete |
| ✅3 | 进度错误处理 | 上传合法文件但模拟解析阶段异常（如注入错误模拟）→ SSE 收到 event:error |
| ✅4 | BM25 + 向量混合检索 | 返回 RRF 融合结果，分数归一化 |
| ✅5 | Cross-encoder Rerank | 开启 Rerank 后结果排序优于纯向量检索（定性判断） |
| ✅6 | Query Rewrite | 多轮对话中问题被改写为独立问题 |
| ✅7 | Redis 缓存命中 | 相同问题第二次检索延迟显著降低 |
| ✅8 | 缓存失效 | 文档上传后缓存自动清除 |
| ✅9 | SSE 流式生成 | 打字机效果，token 逐字返回 |
| ✅10 | 客户端断开清理 | 关闭 SSE 连接后后台任务正确清理 |
| ✅11 | 成员添加/列表/修改/删除 | CRUD 全部正常 |
| ✅12 | 角色权限控制 | owner/editor/viewer 权限矩阵全部通过 |
| ✅13 | Phase 1 回归 | V1-V13 全部通过（非流式 ask 仍可用） |
| ✅14 | 追溯/trace_id | SSE 事件中包含 trace_id |
| ✅15 | 前端验证 | 进度条 + 流式文本 + 成员管理全部可交互 |
