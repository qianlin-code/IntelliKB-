# IntelliKB Phase 3 — Agent 对话 + 持久化 + SSE 多 Worker

## 1. Phase 3 架构调整说明

### 1.1 从 ReAct 循环简化为硬编码两阶段

原计划使用 LangGraph ReAct 循环（`call_model → should_continue → call_tool → 循环`）。
实际实现中简化为：`retrieve_knowledge → call_model → end`。

**原因**：
- ollama qwen2.5:7b 的 function calling 不稳定，经常跳过工具直接回答
- 硬编码两阶段保证每次对话都先检索再生成，RAG 质量更可控

**恢复条件**：
- 切换到支持 function calling 的更强模型（如 qwen2.5:14b 或云端 LLM API）
- 或 ollama qwen2.5:7b 的 tool calling 能力稳定后

**相关文件**：`app/agent/graph.py` — `create_agent_graph()` 函数保留统一接口，切换时无需改动调用方。

### 1.2 工具集从 2 个简化为 1 个

原计划实现 `retrieve_knowledge` + `get_kb_info` 两个工具。
实际只保留 `retrieve_knowledge`。

**原因**：
- 减少弱模型在多个工具间的选择歧义
- `get_kb_info` 的信息可在 system prompt 中静态提供

**扩展条件**：
- 模型 tool calling 稳定后，可加入 `get_kb_info`、`calculator` 等工具

**相关文件**：`app/services/agent_service.py` → `_build_tools()`，仅注册 `retrieve_tool`，`kb_info_tool` 注释保留。

### 1.3 架构差异总结

| 维度 | 原计划 | 实际实现 | 影响 |
|------|--------|----------|------|
| Graph 拓扑 | `call_model → should_continue ↔ call_tool` 循环 | `call_tool → call_model → end` 线序 | 稳定，检索必执行 |
| 工具数量 | 2 个 (`retrieve_knowledge` + `get_kb_info`) | 1 个 (`retrieve_knowledge`) | 减少模型选择负担 |
| 模型依赖 | qwen2.5:7b function calling | qwen2.5:7b 纯文本生成 | 绕过 function calling 限制 |
| 流式粒度 | `astream_events(version="v2")` 逐 token | `astream(stream_mode="updates")` 节点级 | 非真正 token 级流式 |
| 对话持久化 | 同计划 | Conversation + Message 两张表 | 已实现 |
| SSE Pub/Sub | 同计划 | Redis Pub/Sub + key 轮询双通道 | 已实现 |
| KBMember 缓存 | 同计划 | Redis hash TTL=60s | 已实现 |

---

## 2. 修订历史

| 版本 | 日期 | 修订人 | 主要内容 |
|------|------|--------|----------|
| v1.0 | 2026-07-29 | Claude | 初版计划（5 大模块、5 项关键决策、14 节完整结构） |

---

## 2. 前置条件

| # | 条件 | 状态 |
|---|------|:----:|
| P1 | KnowledgeBase CRUD + Document 上传/管理 + 权限校验 | ✅ Phase 1 |
| P2 | Async 文档解析 + SSE 进度 + 成员权限 + Hybrid Search + Rerank + Redis 缓存 + SSE 流式问答 + Query Rewrite | ✅ Phase 2 |
| P3 | KBMember 表已存在（sys_kb_member） | ✅ Phase 2 |
| P4 | LLM 客户端已接入（AsyncOpenAI + ollama qwen2.5:7b） | ✅ Phase 2 |
| P5 | 项目目录结构、日志规范、认证体系（JWT + X-API-Key + Cookie） | ✅ Phase 0/1/2 |

**约定**：所有新端点支持 JWT Bearer + X-API-Key + Cookie 三种认证（SSE 端点用 Cookie）；所有非 SSE 响应走 `APIResponse`；SSE 流式数据格式为 `event: xxx\ndata: ...\n\n`。

---

## 3. 技术决策表（D1–D5）

### D1: Agent 框架

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|:----:|
| **LangGraph** | 内置 State/Checkpointer，Pregel 图架构，与 OpenAI-compatible client 无缝集成 | 新增依赖 `langgraph` ~500KB | **✅ 推荐** |
| 自研 ReAct Loop | 无额外依赖，完全可控 | 需要自实现 State/Checkpointer/persistence，开发量 ~3× | ❌ |
| CrewAI | 高层的多 Agent 编排 | 太臃肿，集成成本高 | ❌ |

**决策 D1**：使用 **LangGraph**（`langgraph>=0.2.0,<0.3.0`）。理由：
- LangGraph 的 `StateGraph` + `MessageGraph` 直接映射到 ReAct 模式的 **思考→行动→观察** 循环
- 内置 `MemorySaver` Checkpointer，可对接 MySQL (`SqliteSaver` 不适合生产，Phase 3 用内存 + DB fallback)
- `@tool` 装饰器自动生成 JSON schema，与 `tool_choice="auto"` 结合可直接传入 AsyncOpenAI
- 社区活跃，文档齐全
- **锁定 0.2.x 系列**，避免 0.3+ 潜在的 API 变化

### D2: 对话存储

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|:----:|
| **Conversation + Message 两张表** | 元数据和消息分离，高效分页、独立操作 | 多一次 JOIN | **✅ 推荐** |
| 一张 ConversationMessage 表 | 简单 | 冗余 metadata，分页耦合，扩展困难 | ❌ |

**决策 D2**：使用 **Conversation + Message 两张表**。理由：
- `sys_conversation` 存储 kb_id、user_id、title 等元数据，`sys_message` 存储消息体
- 对话级操作（重命名、删除）无需遍历消息
- 消息级支持 `tool_call` / `tool_result` 角色类型，metadata_json 存工具调用参数和来源
- 分页策略：对话按 `updated_at DESC` 分页，消息按 `created_at ASC` 顺序返回

### D3: 工具设计

| 工具 | 输入 | 输出 | 说明 |
|------|------|------|------|
| **retrieve_knowledge** `🟢 核心` | question: str, top_k: int | SearchResult[] | 调用 HybridSearchService.search()，带回 chunks |
| **get_kb_info** | 无（上下文绑定） | KB 统计信息 | 文档数、分块数、创建时间 |
| **calculator** (预留) | expression: str | 计算结果 | 演示用，展示 Agent 可以调用非检索工具 |
| **current_datetime** (预留) | 无 | 当前时间 | Agent 可感知时间上下文 |

> Phase 3 仅实现 **retrieve_knowledge**（核心）+ **get_kb_info**（辅助），其余工具作为扩展点。

**决策 D3**：工具集通过 LangGraph `@tool` 装饰器注册，自动生成 OpenAI tool schema。所有工具函数位于 `app/agent/tools/` 目录。

### D4: SSE 多 Worker 升级

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|:----:|
| **Redis Pub/Sub** | 无额外依赖，Worker 间原生解耦 | 无消息持久化 | **✅ 推荐** |
| Redis Stream | 持久化+消费组 | 复杂，本次不需要 | ❌ |
| RabbitMQ / Kafka | 全功能 MQ | 引入太重 | ❌ |

**决策 D4**：使用 **Redis Pub/Sub** 升级 SSE 进度推送。理由：
- 当前单 Worker 用 Redis key 轮询（L6），在多个 uvicorn worker 间无法工作
- Pub/Sub 模式：Worker A（文档解析完成）→ `PUBLISH doc:progress:{doc_id}` → 所有 Worker 收到 → 持有 SSE 连接的 Worker 推送给前端
- 新增 `ProgressPubSubManager` 服务，负责 publish + subscribe + 心跳
- 向后兼容：保留现有的 key 轮询方式作为 fallback

### D5: 多轮上下文窗口

| 决策项 | 取值 | 理由 |
|--------|:----:|------|
| 最大保留轮数 | **20 轮**（40 条消息） | qwen2.5:7b 上下文 32K，20 轮对话 + system + RAG context ≈ 4K-6K tokens |
| 超出后策略 | **保留最近的 20 轮** | Sliding window，保证 LLM 始终有最近上下文 |
| Token 上限硬限制 | **8192 tokens** | 超过则二次截断（丢弃最早的消息对） |

**决策 D5**：Sliding window 保留最近 20 轮对话。数据库全量存储，只在上送 LLM 时做截断。

---

## 4. 数据模型变更

### 4.1 `sys_conversation` 表（新增）

```python
class Conversation(Base, TimestampMixin, SoftDeleteMixin):
    """对话/会话"""
    __tablename__ = "sys_conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="知识库 ID")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="用户 ID")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="对话标题")
    message_count: Mapped[int] = mapped_column(Integer, default=0, comment="消息总数")
    # TimestampMixin: created_at, updated_at
    # SoftDeleteMixin: deleted_at
```

- `(kb_id, user_id)` 联合索引
- `user_id` 单独索引（按用户查看对话列表）

### 4.2 `sys_message` 表（新增）

```python
class Message(Base, TimestampMixin):
    """消息（硬删除，删除 conversation 前手动清理）"""
    __tablename__ = "sys_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="对话 ID")
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="角色: user/assistant/system/tool_call/tool_result")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")
    metadata_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="元数据 JSON（工具调用参数、引用来源等）"
    )
    token_count: Mapped[int] = mapped_column(Integer, default=0, comment="token 估算数")
    tool_call_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="工具调用 ID（对应 LLM response 中的 tool_call_id）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now, comment="更新时间")
```

- `conversation_id` 索引（按对话查询消息）
- `(conversation_id, id)` 复合索引（分页查询 last_id 游标）
- `tool_call_id` 字段用于关联 tool_call 和 tool_result 消息，方便前端展示配对
- **硬删除**：Message 不支持软删除。ConversationService.delete() 先硬删除所有 Message，再软删除 Conversation

### 4.3 `sys_kb_member` 不变

KBMember 保留现有设计。Phase 3 新增 KBMember 缓存一致性优化（新增一个 Redis hash 缓存，TTL=60s，成员变更时主动失效）。

---

## 5. 后端 API 设计

### 5.1 `/conversations` 对话管理

| 方法 | 路径 | 认证 | 说明 |
|------|------|:----:|------|
| `GET` | `/conversations?kb_id=X&page=1&page_size=20` | Bearer | 列出某知识库的对话（按 updated_at DESC） |
| `POST` | `/conversations` | Bearer | 创建新对话（body: `{kb_id, title?}`） |
| `GET` | `/conversations/{id}` | Bearer | 对话详情 + 消息列表（可选 `?include_messages=true`） |
| `PUT` | `/conversations/{id}` | Bearer | 更新标题（body: `{title}`） |
| `DELETE` | `/conversations/{id}` | Bearer | 软删除对话 |
| `GET` | `/conversations/{id}/messages` | Bearer | 消息列表（游标分页: `?before_id=X&limit=50`） |

认证方式：JWT Bearer + X-API-Key + Cookie。

### 5.2 `/agent/chat` Agent 对话

| 方法 | 路径 | 认证 | 说明 |
|------|------|:----:|------|
| `POST` | `/agent/chat` | Bearer+Cookie | Agent 对话（非流式） |
| `GET` | `/agent/chat-stream` | Cookie | SSE Agent 对话（流式，兼容 EventSource） |

**SSE query 参数说明**：
- `kb_id` (必填) — 知识库 ID
- `question` (必填) — 问题文本，必须通过 `encodeURIComponent()` 编码
- `conversation_id` (可选) — 对话 ID，不传则后端自动创建新对话

**POST /agent/chat** Request Body:
```json
{
  "conversation_id": 1,          // 新建对话传 null，后端创建
  "kb_id": 1,
  "question": "什么是知识库？",
  "stream": false
}
```

**POST /agent/chat** Response (non-streaming):
```json
{
  "code": 200,
  "data": {
    "conversation_id": 1,
    "answer": "根据检索结果，知识库是...",
    "sources": [{"chunk_id": 1, "document_id": 1, "content": "...", "score": 0.95}],
    "tool_calls": [
      {"tool": "retrieve_knowledge", "input": {"question": "知识库"}, "output": "3 chunks retrieved"}
    ],
    "token_count": 256
  }
}
```

**GET /agent/chat-stream** SSE 事件序列:
```
event: thought
data: {"content": "用户想知道什么是知识库，我需要检索相关知识"}

event: tool_call
data: {"tool": "retrieve_knowledge", "input": {"question": "什么是知识库"}, "tool_call_id": "call_xxx"}

event: tool_result
data: {"tool": "retrieve_knowledge", "output": "共检索到 3 条相关结果", "chunk_count": 3}

event: sources
data: {"sources": [...]}

data: "根据"
data: "检索"
data: "结果"
...

event: done
data: {"conversation_id": 1, "token_count": 256}
```

### 5.3 SSE 多 Worker Pub/Sub

| 方法 | 路径 | 认证 | 说明 |
|------|------|:----:|------|
| `GET` | `/documents/{doc_id}/progress-pubsub` | Cookie | Pub/Sub 版进度推送（取代 key 轮询） |

保留原有 `GET /documents/{doc_id}/progress` 作为 fallback。新端点通过 Redis Pub/Sub 订阅 `doc:progress:{doc_id}` 频道，收到消息即 push。

### 5.4 权限模型对照

**核心规则**：
- 查看对话列表/创建对话：需要 KB 访问权（owner/member 或 public KB）
- 修改/删除对话：必须是 `conversation.user_id == current_user.id`（只能操作自己的对话）
- Agent 对话 / SSE 进度：需要 KB 访问权

| 操作 | owner | editor | viewer | 备注 |
|------|:-----:|:------:|:------:|------|
| `GET /conversations` | ✅ | ✅ | ✅ | 需 KB 访问权 |
| `POST /conversations` | ✅ | ✅ | ✅ | 需 KB 访问权 |
| `PUT /conversations/{id}` | ✅ | ✅ | ❌ | 仅自己创建的对话（owner 覆盖全权限） |
| `DELETE /conversations/{id}` | ✅ | ✅ | ❌ | 可删除自己创建的对话 |
| `POST /agent/chat` | ✅ | ✅ | ✅ | 需 KB 访问权 |
| `GET /documents/{id}/progress-pubsub` | ✅ | ✅ | ✅ | 需 KB 访问权 |

---

## 6. Core 服务设计

### 6.1 ConversationService

```
app/services/conversation_service.py
```

```python
class ConversationService:
    """对话生命周期管理"""

    async def list(self, kb_id: int, user_id: int, page: int, page_size: int) -> tuple[list[Conversation], int]
    async def create(self, kb_id: int, user_id: int, title: str | None) -> Conversation
    async def get(self, conv_id: int, user_id: int) -> Conversation
    async def update_title(self, conv_id: int, user_id: int, title: str) -> Conversation
    async def delete(self, conv_id: int, user_id: int) -> None
    async def get_messages(self, conv_id: int, user_id: int, before_id: int | None, limit: int) -> list[Message]
```

接口设计要点：
- 查看对话列表/创建对话：需要 KB 访问权（通过 `KBMemberRepository` 校验 `user_id` 对 `kb_id` 的权限）
- 修改/删除对话：校验 `conversation.user_id == current_user.id`（只能操作自己的对话）
- `create()` 自动生成 title（取用户问题的前 `CONVERSATION_TITLE_LENGTH` 字符 + `"..."`）
- `delete()` 先硬删除关联的所有 Message（`message_repo.hard_delete_by_conversation(conv_id)`），再软删除 Conversation（方案 A 推荐）

### 6.2 AgentService（LangGraph ReAct）

```
app/services/agent_service.py
```

**核心架构**：

```
User Input → ConversationService.load_context() → AgentState → LangGraph ReAct Graph → Output
                                                        │
                                          ┌─────────────┼─────────────┐
                                          ▼             ▼             ▼
                                    retrieve_knowledge  get_kb_info  calculator...
```

**LangGraph State 定义**：
```python
from typing import TypedDict, Annotated, Sequence
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[Sequence[dict], add_messages]  # LangGraph 内置消息追加
    kb_id: int
    user_id: int
    sources: list[dict]              # 最终引用的来源
    tool_calls_log: list[dict]       # 工具调用日志
```

**AgentService 类**（db session 通过实例变量持有，通过闭包注入到工具中）：
```python
class AgentService:
    """Agent 对话服务——封装 LangGraph ReAct"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.kb_id: int | None = None       # 每次对话前设置
        self.user_id: int | None = None
        self.tools = []                     # 由 _build_tools() 按需构造

    def _build_tools(self):
        """通过闭包将 db session 注入到工具函数中"""
        db = self.db

        @tool
        async def retrieve_knowledge(question: str, top_k: int = 5) -> list[dict]:
            """检索知识库中与问题相关的文档片段"""
            results, _ = await hybrid_search_service.search(
                db, self.kb_id, question, self.user_id, top_k
            )
            return [r.model_dump(mode="json") for r in results]

        @tool
        async def get_knowledge_base_info() -> dict:
            """获取当前知识库的统计信息"""
            from app.services.kb_service import KBService
            kb_service = KBService(db)
            kb = await kb_service.get_accessible(self.kb_id, self.user_id)
            stats = await kb_service.get_stats(self.kb_id)
            return {
                "name": kb.name,
                "description": kb.description,
                "document_count": stats["document_count"],
                "chunk_count": stats["chunk_count"],
            }

        return [retrieve_knowledge, get_knowledge_base_info]

    async def chat(self, conv_id: int | None, kb_id: int, question: str, ...) -> ...
    async def chat_stream(self, conv_id: int | None, kb_id: int, question: str, ...) -> ...
```

**Graph 节点**：

| 节点 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `call_model` | 调用 LLM，传入 history + tools | AgentState.messages | AgentState.messages + AI message |
| `should_continue` | 条件边：检测是否需要调用工具 | AgentState.messages[-1] | "tools" 或 "end" |
| `call_tool` | 执行工具调用 | tool_call 参数 | tool_result → messages |

**Graph 结构**：
```
call_model → should_continue → "tools" → call_tool → call_model (循环)
                │
                └→ "end" → 输出结果
```

**Checkpointer**：Phase 3 使用 `MemorySaver`（进程内）。不引入外部 Checkpointer 以降低复杂度。

**Prompt 模板**：
```
你是一个智能知识库助手，基于 IntelliKB 平台为用户提供问答服务。
你擅长使用工具来获取信息，在回答时应该：

1. 优先使用 retrieve_knowledge 工具检索相关知识
2. 基于检索结果回答，并引用来源
3. 如果检索结果不足以回答，请明确说明
4. 用中文回答，保持专业友好
```

**thought 事件实现方案 B**：在 `call_model` 节点前手动 yield SSE 事件。因 LangGraph 的 `StateGraph` 节点本身是异步生成器，可在调用 LLM 前发射 thought 事件。

```python
# app/services/agent_service.py 中流式实现示意
async def _stream_graph(self, state: AgentState):
    """执行 LangGraph 并发射 SSE 事件"""
    # 方案 B: 调用 LLM 前手动 yield thought
    yield ThoughtEvent(content="正在分析用户问题，准备调用检索工具...")

    # 执行 graph
    async for event in self.graph.astream_events(state, version="v2"):
        if event["event"] == "on_tool_start":
            yield ToolCallEvent(tool=event["name"], input=event["input"])
        elif event["event"] == "on_tool_end":
            yield ToolResultEvent(tool=event["name"], output=event["output"])
        elif event["event"] == "on_chat_model_stream":
            yield TokenEvent(content=event["data"]["chunk"].content)
        elif event["event"] == "on_chain_end" and event["name"] == "call_model":
            yield SourcesEvent(sources=state["sources"])

    yield DoneEvent(conversation_id=..., token_count=...)
```

- `astream_events(version="v2")` 提供细粒度事件类型（工具开始/结束、LLM 流式块等）
- thought 内容可以动态生成（如"正在分析用户问题"→"正在检索相关知识库"→"正在生成回答"）

### 6.3 SSE Pub/Sub Manager

```
app/services/progress_pubsub.py
```

```python
class ProgressPubSubManager:
    """Redis Pub/Sub 进度推送"""

    CHANNEL_PREFIX = "doc:progress:"   # + doc_id

    async def publish(self, doc_id: int, data: dict) -> None
    # 无 subscribe/unsubscribe 方法——每个 SSE 连接创建独立 pubsub 对象
```

**连接生命周期**：每个 SSE 连接创建独立的 `PubSub` 对象，断开后立即清理。

```python
# app/api/v1/documents.py 中 SSE 端点实现示意
from app.core.redis_client import get_redis

async def sse_progress_endpoint(doc_id: int, request: Request):
    r = await get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"doc:progress:{doc_id}")
    disconnect_event = asyncio.Event()

    # 后台检测客户端断开
    async def _check_disconnect():
        while True:
            if await request.is_disconnected():
                disconnect_event.set()
                break
            await asyncio.sleep(1)
    check_task = asyncio.create_task(_check_disconnect())

    try:
        async for message in pubsub.listen():
            if disconnect_event.is_set():
                break
            if message["type"] == "message":
                yield f"event: progress\ndata: {message['data']}\n\n"
    finally:
        check_task.cancel()
        await pubsub.unsubscribe()
        await pubsub.close()
```

- 每个 SSE 连接创建独立 pubsub 对象，断开后 `unsubscribe()` + `close()` 保证无泄漏
- `asyncio.Event` + 后台检测协程实现客户端断开感知，不依赖超时

兼容策略：保留 `progress_manager`。解析流程同时写入 Redis key（轮询）和 Pub/Sub（推送），新端点只依赖 Pub/Sub。

### 6.4 KBMember 缓存一致性优化

```
app/services/kb_member_cache.py（新增）
```

- Redis hash: `kb_member:cache:{kb_id}` → `{user_id: role}`
- TTL: 60 秒（短 TTL 保证一致性）
- 新增成员/修改角色/移除成员时，主动 `DEL` 失效
- 查询路径：先查 Redis hash，miss 则查 MySQL 并回填

> 优化范围：成员列表查询、权限校验。不涉及现有行为变更。

---

## 7. Schemas 设计

### 7.1 conversation.py（新增）

```python
class ConversationCreate(BaseModel):
    kb_id: int
    title: str | None = None

class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

class ConversationResponse(BaseModel):
    id: int
    kb_id: int
    user_id: int
    title: str | None
    message_count: int
    created_at: str
    updated_at: str
    # model_config = {"from_attributes": True}

class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    page: int
    page_size: int
```

### 7.2 message.py（新增）

```python
class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    metadata_json: dict | None
    token_count: int
    created_at: str

class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    has_more: bool
```

### 7.3 agent.py（新增）

```python
class AgentChatRequest(BaseModel):
    conversation_id: int | None = None  # None 表示新建对话
    kb_id: int
    question: str = Field(min_length=1, max_length=2000)
    stream: bool = False

class ToolCallInfo(BaseModel):
    tool: str
    input: dict
    output: str

class AgentChatResponse(BaseModel):
    conversation_id: int
    answer: str
    sources: list[SearchResult]
    tool_calls: list[ToolCallInfo]
    token_count: int

class AgentSSEEvent(BaseModel):
    """SSE 各事件类型的数据结构"""
    event: str           # thought / tool_call / tool_result / sources / token / done
    data: dict
```

---

## 8. Repository 设计

### 8.1 ConversationRepository（新增）

```
app/repositories/conversation.py
```

```python
class ConversationRepository:
    async def list_by_kb_and_user(self, kb_id: int, user_id: int, skip: int, limit: int) -> tuple[list[Conversation], int]
    async def create(self, data: dict) -> Conversation
    async def get_by_id(self, conv_id: int) -> Conversation | None
    async def update(self, conv: Conversation) -> Conversation
    async def soft_delete(self, conv: Conversation) -> None
    async def increment_message_count(self, conv_id: int) -> None
```

### 8.2 MessageRepository（新增）

```
app/repositories/message.py
```

```python
class MessageRepository:
    async def create(self, data: dict) -> Message
    async def create_batch(self, messages: list[dict]) -> list[Message]
    async def list_by_conversation(self, conv_id: int, before_id: int | None, limit: int) -> tuple[list[Message], bool]
    # has_more = len(results) > limit，取 limit+1 条判断
```

---

## 9. 前端页面/组件设计

### 9.1 新增组件

| 组件 | 路径 | 功能 |
|------|------|------|
| `ConversationSidebar.vue` | `components/` | 左侧对话列表：新建、切换、删除、重命名 |
| `ChatMessage.vue` | `components/` | 单条消息：区分 user/assistant/tool_call，Markdown 渲染，工具调用可展开 |
| `ToolCallCard.vue` | `components/` | 工具调用卡片：显示工具名、输入参数、输出结果 |
| `AgentStreamRenderer.vue` | `components/` | Agent SSE 事件流渲染：解析 thought/tool_call/tool_result/sources/token/done 事件，调用 ToolCallCard 展示工具调用，调用 marked/dompurify 渲染 token 流 |

### 9.2 重构页面

**QAPage.vue** → 左右分栏布局：

```
┌──────────────────┬──────────────────────────────────────────────┐
│  Conversation     │                                              │
│  Sidebar          │           Message Area                       │
│                   │                                              │
│  ┌─────────────┐  │  ┌────────────────────────────────────────┐  │
│  │ + 新建对话   │  │  │  user: 什么是知识库？                  │  │
│  ├─────────────┤  │  ├────────────────────────────────────────┤  │
│  │ 对话1       │  │  │  assistant: ... (markdown)             │  │
│  │ 对话2       │  │  │  ┌ 工具调用 ──────────────────────┐    │  │
│  │ 对话3       │  │  │  │ 🔍 retrieve_knowledge          │    │  │
│  │ ...         │  │  │  │ 输入: 知识库                   │    │  │
│  │             │  │  │  │ 输出: 3 条结果                 │    │  │
│  │             │  │  │  └────────────────────────────────┘    │  │
│  │             │  │  ├────────────────────────────────────────┤  │
│  │             │  │  │  [输入框 Ctrl+Enter]                   │  │
│  └─────────────┘  │  └────────────────────────────────────────┘  │
└──────────────────┴──────────────────────────────────────────────┘
```

### 9.3 新增/修改 API 文件

| 文件 | 操作 | 说明 |
|------|:----:|------|
| `frontend/src/api/conversation.ts` | 新增 | 对话 CRUD API |
| `frontend/src/api/agent.ts` | 新增 | Agent 对话 API（含 stream） |
| `frontend/src/store/conversation.ts` | 新增 | Pinia store |
| `frontend/src/types/index.ts` | 修改 | 新增 Conversation/Message/Agent 类型 |
| `frontend/src/views/qa/QAPage.vue` | 重构 | 左右分栏 + 工具调用展示 |
| `frontend/src/components/AgentStreamRenderer.vue` | 新增 | Agent SSE 事件渲染（thought/tool_call/sources/token/done） |
| `frontend/src/components/StreamingText.vue` | 不变 | 只处理 `/qa/ask-stream` 纯 token 流，不修改 |

### 9.4 Store 设计 (conversation.ts)

```typescript
export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref<Conversation[]>([])
  const currentConvId = ref<number | null>(null)
  const messages = ref<Message[]>([])

  async function loadConversations(kbId: number) { ... }
  async function createConversation(kbId: number) { ... }
  async function deleteConversation(convId: number) { ... }
  async function loadMessages(convId: number) { ... }
  function appendMessage(msg: Message) { ... }
})
```

---

## 10. 配置文件变更

### `app/config.py` 新增字段

```python
# ── Phase 3: Agent ──
AGENT_ENABLED: bool = True
AGENT_MODEL: str = "qwen2.5:7b"        # Agent 专用模型（可不同于 RAG）
AGENT_TIMEOUT_SECONDS: int = 120
AGENT_MAX_TOOL_ITERATIONS: int = 5      # 最大工具调用轮次

# ── Phase 3: Conversation ──
CONVERSATION_MAX_HISTORY_ROUNDS: int = 20
CONVERSATION_TITLE_LENGTH: int = 30     # 自动标题截取长度（字符数）

# ── Phase 3: SSE Pub/Sub ──
SSE_PUBSUB_ENABLED: bool = True

# ── Phase 3: KBMember Cache ──
MEMBER_CACHE_TTL_SECONDS: int = 60
```

### `.env.example` 新增条目

```bash
# ── Phase 3: Agent ──
AGENT_ENABLED=true
AGENT_MODEL=qwen2.5:7b
AGENT_TIMEOUT_SECONDS=120
AGENT_MAX_TOOL_ITERATIONS=5

# ── Phase 3: 对话 ──
CONVERSATION_MAX_HISTORY_ROUNDS=20
CONVERSATION_TITLE_LENGTH=30

# ── Phase 3: SSE ──
SSE_PUBSUB_ENABLED=true

# ── Phase 3: 成员缓存 ──
MEMBER_CACHE_TTL_SECONDS=60
```

---

## 11. Alembic 迁移计划

### 迁移 1: `phase3_conversation_message_tables.py`

新建 `sys_conversation` 和 `sys_message` 两张表。

```python
"""Phase 3: 对话 + 消息表

Revision ID: phase3_001
Revises: df17e0a41ea1  (Phase 2 KBMember 迁移)
"""
def upgrade():
    op.create_table(
        "sys_conversation",
        op.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        op.Column("kb_id", sa.Integer(), nullable=False),
        op.Column("user_id", sa.Integer(), nullable=False),
        op.Column("title", sa.String(200), nullable=True),
        op.Column("message_count", sa.Integer(), default=0),
        op.Column("created_at", sa.DateTime(), nullable=False),
        op.Column("updated_at", sa.DateTime(), nullable=False),
        op.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_conv_kb_user", "sys_conversation", ["kb_id", "user_id"])
    op.create_index("idx_conv_user", "sys_conversation", ["user_id"])

    op.create_table(
        "sys_message",
        op.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        op.Column("conversation_id", sa.Integer(), nullable=False),
        op.Column("role", sa.String(20), nullable=False),
        op.Column("content", sa.Text(), nullable=False),
        op.Column("metadata_json", sa.Text(), nullable=True),
        op.Column("token_count", sa.Integer(), default=0),
        op.Column("created_at", sa.DateTime(), nullable=False),
        op.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_msg_conv", "sys_message", ["conversation_id"])
    op.create_index("idx_msg_conv_id", "sys_message", ["conversation_id", "id"])

def downgrade():
    op.drop_table("sys_message")
    op.drop_table("sys_conversation")
```

---

## 12. 文件创建/修改顺序

### 创建顺序（严格按此顺序执行）

```
 1. app/models/conversation.py               ── Conversation 模型
 2. app/models/message.py                     ── Message 模型
 3. app/models/__init__.py                    ── 注册新模型
 4. alembic 迁移                              ── phase3_001 自动生成 + upgrade head
 5. app/schemas/conversation.py               ── 对话 Schemas
 6. app/schemas/message.py                    ── 消息 Schemas
 7. app/schemas/agent.py                      ── Agent 对话 Schemas
 8. app/repositories/conversation.py          ── 对话 Repository
 9. app/repositories/message.py               ── 消息 Repository
10. app/repositories/__init__.py              ── 注册
11. app/services/conversation_service.py      ── 对话服务
12. app/agent/__init__.py                     ── Agent 包
13. app/agent/tools/__init__.py               ── 工具包
14. app/agent/tools/retrieve_knowledge.py     ── 检索工具
15. app/agent/tools/get_kb_info.py            ── KB 信息工具
16. app/agent/graph.py                        ── LangGraph StateGraph 定义
17. app/services/agent_service.py             ── Agent 服务（封装 LangGraph）
18. app/services/progress_pubsub.py           ── SSE Pub/Sub 管理器
19. app/services/kb_member_cache.py           ── 成员缓存优化
20. app/api/v1/conversations.py               ── 对话 API 路由
21. app/api/v1/agent_chat.py                  ── Agent 对话 API 路由
22. app/api/v1/__init__.py                    ── 注册新路由
23. app/config.py                             修改: 新增 Phase 3 配置
24. .env.example                              修改: 新增 Phase 3 环境变量
25. frontend/src/api/conversation.ts          ── 对话 API
26. frontend/src/api/agent.ts                 ── Agent API
27. frontend/src/store/conversation.ts        ── 对话 Store
28. frontend/src/types/index.ts               修改: 新增对话/消息/Agent 类型
29. frontend/src/components/ChatMessage.vue   ── 消息组件
30. frontend/src/components/ToolCallCard.vue  ── 工具调用卡片
31. frontend/src/components/ConversationSidebar.vue  ── 对话侧边栏
32. frontend/src/views/qa/QAPage.vue          重构: 左右分栏 + Agent 模式
33. frontend/src/components/AgentStreamRenderer.vue  ── Agent SSE 事件渲染组件
```

### 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `app/models/__init__.py` | import Conversation, Message |
| `app/repositories/__init__.py` | import ConversationRepository, MessageRepository |
| `app/api/v1/__init__.py` | 注册 conversations, agent_chat 路由 |
| `app/config.py` | 新增 Phase 3 配置项 |
| `.env.example` | 新增 Phase 3 环境变量 |
| `frontend/src/types/index.ts` | 新增对话/消息/Agent 类型 |
| `frontend/src/views/qa/QAPage.vue` | 重构为左右分栏 |
| `frontend/src/components/AgentStreamRenderer.vue` | 新增 Agent SSE 事件渲染 |

---

## 13. 验证步骤

### 13.1 后端验证（curl）

#### C1: 对话 CRUD

```bash
# 创建对话
curl -s -X POST http://localhost:8000/api/v1/conversations \
  -H "Authorization: Bearer $AT" \
  -H "Content-Type: application/json" \
  -d '{"kb_id": 17}' | python -m json.tool
# → 201, 返回 conversation_id, title 自动生成

# 列出对话
curl -s "http://localhost:8000/api/v1/conversations?kb_id=17&page=1&page_size=10" \
  -H "Authorization: Bearer $AT" | python -m json.tool
# → 200, items 数组

# 修改标题
curl -s -X PUT http://localhost:8000/api/v1/conversations/1 \
  -H "Authorization: Bearer $AT" \
  -H "Content-Type: application/json" \
  -d '{"title": "Phase 3 测试对话"}' | python -m json.tool
# → 200

# 删除对话
curl -s -X DELETE http://localhost:8000/api/v1/conversations/1 \
  -H "Authorization: Bearer $AT"
# → 200
```

#### C2: Agent 对话（非流式）

```bash
curl -s -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $AT" \
  -H "Content-Type: application/json" \
  -d '{"kb_id": 17, "question": "请介绍一下知识库中的文档内容", "conversation_id": null, "stream": false}' \
  | python -m json.tool
# → 200, 验证:
#   - answer: 非空
#   - sources: 有检索来源
#   - tool_calls: 包含 retrieve_knowledge
#   - conversation_id: 自动创建
```

#### C3: Agent 对话（流式 SSE）

```bash
curl -N "http://localhost:8000/api/v1/agent/chat-stream?kb_id=17&question=什么是知识库&conversation_id=2" \
  -H "Cookie: access_token=$AT"
# → 验证事件序列:
#   event: thought
#   event: tool_call
#   event: tool_result
#   event: sources
#   data: token...
#   event: done
```

#### C4: 多轮对话上下文

```bash
# 第一轮
curl -s -X POST ... -d '{"kb_id": 17, "question": "我的用户名是 test123", ...}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['data']['conversation_id'])"
# → conv_id=3

# 第二轮（同 conv_id）—— 复述确认
curl -s -X POST ... -d '{"kb_id": 17, "question": "请复述我的上一个问题", "conversation_id": 3}' | python -m json.tool
# → 应能复述出"我的用户名是 test123"

# 第三轮（同 conv_id）—— 引用历史
curl -s -X POST ... -d '{"kb_id": 17, "question": "我的用户名是什么？", "conversation_id": 3}' | python -m json.tool
# → 应回答"test123"
```

#### C5: SSE Pub/Sub 进度推送

```bash
# 在一个终端订阅
curl -N "http://localhost:8000/api/v1/documents/1/progress-pubsub" \
  -H "Cookie: access_token=$AT"

# 在另一终端上传文档
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $AT" \
  -F "file=@test.md" -F "kb_id=17"
# → 第一个终端应实时收到 progress 事件（无需轮询）
```

#### C6: KBMember 缓存

```bash
# 先查一次（MySQL）
curl -s "http://localhost:8000/api/v1/knowledge-bases/17/members" \
  -H "Authorization: Bearer $AT"
# → 200, 记录延迟（应 ~10ms MySQL）

# 再查第二次（Redis 命中）
# → 延迟应 < 5ms

# 添加成员
curl -s -X POST ... -d '{"user_id": 2, "role": "editor"}'
# → 缓存失效

# 再查（MySQL）
# → 新成员可见
```

### 13.2 前端验证

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| F1 | 进入知识库 → 点击"进入问答" | 显示左右分栏布局，左侧为对话列表 |
| F2 | 点击"+ 新建对话" | 创建新对话，右侧空白可输入 |
| F3 | 输入问题 → Ctrl+Enter | 显示 Assistant 消息，工具调用可展开 |
| F4 | 继续发送消息（同一对话） | 上下文连贯，Agent 能引用历史 |
| F5 | 左侧切换对话 | 右侧加载对应消息列表 |
| F6 | 重命名对话（右键/双击标题） | 标题更新成功 |
| F7 | 删除对话 | 对话消失，回到空状态 |
| F8 | 上传文档 → 观察进度 | SSE Pub/Sub 实时显示进度条 |

### 13.3 测试

| 测试 | 内容 |
|------|------|
| `tests/test_conversation_repo.py` | ConversationRepository CRUD |
| `tests/test_message_repo.py` | MessageRepository CRUD + 游标分页 |
| `tests/test_agent_service.py` | AgentService 单轮/多轮/工具调用（使用 mock LLM 响应，不依赖真实模型。Mock 策略：将 `AsyncOpenAI.chat.completions.create` 替换为返回预定义 tool_call 或文本响应的 fixture） |
| `tests/test_conversation_api.py` | 对话 API 端点（依赖 mock db） |

---

## 14. 风险与简化项

### 风险

| # | 风险 | 影响 | 缓解措施 |
|---|------|:----:|----------|
| R1 | LangGraph 版本兼容性 | 中 | 锁定 `langgraph>=0.2.0,<0.3.0`（0.2.x 系列），在独立的测试环境中先行验证 |
| R2 | LangGraph `add_messages` 与自定义 State 冲突 | 高 | 仔细设计 State TypedDict，先做最小原型验证再全量开发 |
| R3 | SSE Pub/Sub 连接泄漏 | 高 | 实现 `asyncio.gather(subscribe_loop, disconnect_wait)` 模式，任一完成即清理 |
| R4 | Agent 工具调用无限循环 | 中 | `AGENT_MAX_TOOL_ITERATIONS=5` 硬限制，触发后返回当前结果+警告 |
| R5 | Windows 下 ProactorEventLoop 与 ASGITransport 冲突 | 低 | 同 Phase 1/2，仅影响 pytest，不影响生产 |

### 简化项

| # | 简化内容 | 理由 |
|---|----------|------|
| S1 | LangGraph MemorySaver 用进程内内存，不持久化 Checkpointer | Phase 3 首要目标是 Agent 能力上线，Checkpointer 持久化可在 Phase 4 用 MySQL Saver 补充 |
| S2 | Agent 工具集只实现 2 个（retrieve + kb_info） | 聚焦核心 RAG 场景，calculator/weather 等工具的扩展接口已预留 |
| S3 | SSE Pub/Sub 不做消息持久化 | 进度通知是瞬时状态，丢失后用户可重新上传 |
| S4 | 前端 Agent SSE 用独立 AgentStreamRenderer 组件 | 职责分离：StreamingText 只处理纯 token 流，AgentStreamRenderer 处理完整 Agent 事件序列 |
| S5 | 模型：Agent 和 RAG 使用同一模型（qwen2.5:7b） | 分离不同模型需要额外配置和测试，Phase 4 可演进。如 Agent tool calling 不稳定，可在 Phase 4 将 AGENT_MODEL 独立配置为更强的模型（如 qwen2.5:14b） |
| S6 | RAG 评测看板（可选）不纳入 Phase 3 | 可在独立 Phase 实现 |

---

## 15. 验收标准

### 必要条件（P0）

| # | 标准 | 验证方式 |
|---|------|----------|
| A1 | 对话 CRUD 全部可用（创建/列表/详情/更新/删除） | curl C1 验证 |
| A2 | Agent 对话（非流式）返回含工具调用和引用来源的答案 | curl C2 验证 |
| A3 | Agent 对话（流式）SSE 事件序列完整（thought→tool_call→tool_result→sources→token→done） | curl C3 验证 |
| A4 | 多轮对话上下文连贯，Agent 可引用前序轮次 | curl C4 验证 |
| A5 | SSE Pub/Sub 实时推送文档解析进度 | curl C5 + 前端观察 |
| A6 | KBMember 缓存命中后延迟 < 5ms | curl C6 验证 |
| A7 | 前端左右分栏布局渲染正常 | 前端 F1-F7 验证 |
| A8 | 所有新端点支持 JWT Bearer + X-API-Key + Cookie | curl 三种认证方式 |

### 可选条件（P1）

| # | 标准 | 说明 |
|---|------|------|
| B1 | Agent 工具调用可视化展开/收起 | 前端体验优化 |
| B2 | 对话自动标题生成 | 仅截取前 N 字，非 LLM 生成 |
| B3 | 前端 SSE 流式问答 | 从 QAPage 切换到 Agent SSE |

### 后验条件

| # | 检查项 |
|---|--------|
| C1 | Phase 1 `/qa/search` 和 `/qa/ask` 端点仍然正常工作 |
| C2 | Phase 2 `/qa/hybrid-search` 和 `/qa/ask-stream` 端点仍然正常工作 |
| C3 | Phase 2 文档上传 + SSE 进度 + 成员权限仍然正常工作 |
| C4 | 所有新增端点返回符合 `APIResponse` 格式（SSE 除外） |
| C5 | 数据迁移可回滚 (downgrade) |
| C6 | ALEMBIC_SYNC_URL 兼容同步 URL（不加 +aiomysql） |

---

## 附录 A: 关键依赖

```
# requirements.txt 新增
langgraph>=0.2.0,<0.3.0    # 锁定 0.2.x 系列，避免 0.3+ 潜在的 API 变化
```

LangGraph 会自动依赖 `langchain-core`（含 `@tool` 装饰器和 Tool schema）。

## 附录 B: 目录结构变更

```
app/
├── agent/                        # 新增：Agent 包
│   ├── __init__.py
│   ├── graph.py                  # LangGraph StateGraph 定义
│   └── tools/
│       ├── __init__.py
│       ├── retrieve_knowledge.py # 检索工具
│       └── get_kb_info.py        # KB 信息工具
├── models/
│   ├── conversation.py           # 新增
│   ├── message.py                # 新增
│   └── ...
├── schemas/
│   ├── conversation.py           # 新增
│   ├── message.py                # 新增
│   ├── agent.py                  # 新增
│   └── ...
├── repositories/
│   ├── conversation.py           # 新增
│   ├── message.py                # 新增
│   └── ...
├── services/
│   ├── conversation_service.py   # 新增
│   ├── agent_service.py          # 新增
│   ├── progress_pubsub.py        # 新增
│   ├── kb_member_cache.py        # 新增
│   └── ...
└── api/v1/
    ├── conversations.py          # 新增
    ├── agent_chat.py             # 新增
    └── ...
```

---

## 附录 C: SSE 事件协议规范

### Agent SSE 事件格式

```
event: thought
data: {"content": "用户想知道..."}

event: tool_call
data: {"tool": "retrieve_knowledge", "input": {"question": "..."}, "tool_call_id": "call_xxx"}

event: tool_result
data: {"tool": "retrieve_knowledge", "output": "...", "chunk_count": 3}

event: sources
data: {"sources": [{"chunk_id": 1, "document_id": 1, "content": "...", "score": 0.95}]}

data: "逐"
data: "字"
data: "输"
data: "出"

event: done
data: {"conversation_id": 1, "total_tokens": 256, "tool_calls_count": 2}
```

### 文档进度 Pub/Sub 事件格式

```
event: progress
data: {"stage": "parsing", "progress": 0.25, "message": "正在提取文本..."}

event: progress
data: {"stage": "chunking", "progress": 0.50, "message": "正在分块..."}

event: progress
data: {"stage": "indexing", "progress": 0.75, "message": "正在生成向量..."}

event: complete
data: {"stage": "done", "progress": 1.0, "message": "完成，共 10 块"}

event: error
data: {"stage": "error", "progress": 0.0, "message": "解析失败: ..."}
```
