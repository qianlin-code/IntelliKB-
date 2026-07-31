# IntelliKB Phase 4 — 质量增强：持久化 + 前端 + 缓存 + 标题

> **目标路径**：本规划在评审通过后应保存为 `docs/phase4-plan.md`。

## 背景

Phase 3 交付了 Agent 对话 + 对话持久化 + SSE Pub/Sub + KBMember 缓存的核心能力，但以下问题需要在 Phase 4 解决：

- **LangGraph 无 Checkpointer** — 每次对话从头执行，无法中断/恢复，无法支持后续 `astream_events`
- **前端体验粗糙** — ChatMessage 不支持 Markdown/代码高亮，无对话搜索/导出，SSE 解析器重复
- **KBMember 缓存未接入** — `kb_member_cache.py` 代码已写但权限校验路径完全不使用
- **对话标题为字符串截断** — 缺 LLM 语义标题

Phase 4 定位于"质量增强"，不改动核心架构（简化 Graph 保持，不引入 ReAct 循环，不升级模型，不做 token 级流式）。

---

## 范围边界

| 优先级 | 功能 | 说明 |
|:------:|------|------|
| **P0** | MySQL Checkpointer | 新建 `sys_agent_checkpoint` 表，实现 `BaseCheckpointSaver` 子类 |
| **P0** | 前端交互增强 | Markdown 渲染 + 代码高亮 + 对话搜索 + SSE 解析统一 + 对话导出 |
| **P1** | KBMember 缓存接入 | `kb_member_cache` 集成到 `KBService.get_accessible/get_editable` + 失效 |
| **P1** | 语义标题 | LLM 生成对话标题（替代字符截断） |
| **P2** | LLM 客户端统一 | 共享 `AsyncOpenAI` 工厂 + `LLM_MAX_RETRIES` 生效 |
| **延后 Phase 5** | 完整 ReAct、Token 流式、RAG 评测看板 | — |

---

## 技术决策

### D1: Checkpointer 存储方案

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|:----:|
| **MySQL 自建表** | 与现有 DB 统一，备份/运维一致 | 需要实现 `BaseCheckpointSaver` 子类 | **✅ 推荐** |
| AsyncSqliteSaver | LangGraph 内置，零开发 | 独立存储，不利于运维 | ❌ |
| MemorySaver + DB 持久化 | 简单 | 两层状态，一致性难保证 | ❌ |

**决策 D1**：MySQL 自建表。实际运行版本为 `langgraph 1.2.9` + `langgraph-checkpoint 4.1.1`，其 `BaseCheckpointSaver` 需实现以下 4 个异步方法（接口签名与 0.2.69 基本一致，注意 `CheckpointTuple` 参数名 `pending_writes` 而非 `pending_sends`）：

```python
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import RunnableConfig

class BaseCheckpointSaver:
    """LangGraph 1.2.9 / checkpoint 4.1.1 接口签名"""

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """通过 config["configurable"]["thread_id"] + checkpoint_ns + checkpoint_id 查询检查点"""
        ...

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, str | int | float],
    ) -> RunnableConfig:
        """写入检查点，返回包含新 checkpoint_id 的 config"""
        ...

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, str] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> list[CheckpointTuple]:
        """分页查询历史检查点"""
        ...

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """写入 pending channel writes（中断恢复用）"""
        ...
```

数据以 JSON 序列化存储，`thread_id` 映射到 `"conv:{conversation_id}"`。

### D2: Markdown 渲染方案

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|:----:|
| **marked + DOMPurify** | StreamingText 已使用，成熟 | 需要额外引入 highlight.js | **✅ 推荐** |
| @vueuse/markdown | Vue 集成好 | 额外依赖 | ❌ |
| 自研 | 可控 | 工作量太大 | ❌ |

**决策 D2**：复用 StreamingText 已有的 `marked` + `DOMPurify` 方案，新增 `highlight.js` 做代码语法高亮。ChatMessage 和 StreamingText 统一使用同一套 `useMarkdown` composable。

**marked 版本注意事项**：若 `marked` 版本为 v13+（当前 `npm view marked version` 确认），则 `marked.setOptions({ highlight })` 已废弃。v13+ 中应使用 `marked.use({ renderer })` 自定义 `<pre><code>` 输出并手动调用 highlight.js：

```typescript
// marked v13+ API
const renderer = new marked.Renderer()
renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
  const highlighted = lang && hljs.getLanguage(lang)
    ? hljs.highlight(text, { language: lang }).value
    : text
  return `<pre><code class="hljs ${lang || ''}">${highlighted}</code></pre>`
}
marked.use({ renderer })
```

若当前 `node_modules` 中版本为 v12.x，则沿用 `setOptions({ highlight })`，无需修改。

### D3: 语义标题生成策略

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|:----:|
| **首轮对话后异步生成** | 不阻塞用户 | 标题延迟可见 | **✅ 推荐** |
| 提交问题时同步生成 | 即时 | 阻塞响应，额外 LLM 调用 | ❌ |
| 固定模板 | 零延迟 | 无意义 | ❌ |

**决策 D3**：首轮 Agent 对话完成后，发起异步 LLM 调用（`max_tokens=20`），用前 3 条消息生成 ≤12 字标题。

---

## 后端变更

### 1. MySQL Checkpointer（P0）

#### 1.1 数据模型 — `app/models/checkpoint.py`（新增）

```python
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.dialects.mysql import MEDIUMBLOB, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time_utils import utcnow
from app.models.base import Base


class AgentCheckpoint(Base):
    """LangGraph checkpointer 持久化"""
    __tablename__ = "sys_agent_checkpoint"
    __table_args__ = (
        Index("idx_ckpt_thread_ns_id", "thread_id", "checkpoint_ns", "checkpoint_id", unique=True),
        Index("idx_ckpt_created_at", "created_at"),  # 优化 cleanup_expired() 删除性能
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    checkpoint_ns: Mapped[str] = mapped_column(
        String(256), nullable=False, default="", server_default="",
        comment="检查点命名空间"
    )
    checkpoint_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="语义类型: checkpoint / pending_writes"
    )
    serde_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="serde 序列化类型，如 json"
    )
    checkpoint_json: Mapped[bytes] = mapped_column(MEDIUMBLOB, nullable=False)  # msgpack 二进制序列化
    metadata_json: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=utcnow, server_default=func.now(),
    )
```

要点：
- 唯一索引改为 `(thread_id, checkpoint_ns, checkpoint_id)`，避免同名 `checkpoint_id` 跨 namespace 冲突
- `checkpoint_ns` 增加 `server_default=""`，`created_at` 增加 `server_default=func.now()`，与模型 `default=` 保持一致
- `checkpoint_json` 使用 `MEDIUMBLOB`（最大 16MB），因为 JsonPlusSerializer 序列化为 msgpack **二进制**数据，不是文本
- `metadata_json` 为 JSON 字符串，使用 `MEDIUMTEXT`
- `serde_type` 列存储 `dumps_typed()` 返回的类型字符串（如 "msgpack"），反序列化时传递给 `loads_typed()`
- `idx_ckpt_created_at` 索引优化 `cleanup_expired()` 的批量删除性能

#### 1.2 Checkpointer 实现 — `app/agent/checkpointer.py`（新增）

实现 `BaseCheckpointSaver` 四个核心方法（完整接口签名见 D1）：

| 方法 | 功能 | SQL 操作 |
|------|------|----------|
| `aget_tuple(config)` | 通过 `thread_id + checkpoint_ns + checkpoint_id` 反序列化 | `SELECT ... WHERE (thread_id, checkpoint_ns, checkpoint_id)` |
| `aput(config, checkpoint, metadata, new_versions)` | INSERT checkpoint | `INSERT INTO sys_agent_checkpoint (type='checkpoint')` |
| `alist(config, filter, before, limit)` | 按 `thread_id` 分页查历史 | `SELECT ... ORDER BY id DESC LIMIT $limit` |
| `aput_writes(config, writes, task_id)` | INSERT pending channel writes | `INSERT INTO sys_agent_checkpoint (type='pending_writes')` |

关键设计点：
- `thread_id` = `"conv:{conversation_id}"`，自然绑定到对话
- `checkpoint_json` 存 LangGraph 序列化的完整状态（含 messages/sources/tool_calls_log），使用 `JsonPlusSerializer`
- 每次 graph 执行后自动写入，下次相同 `thread_id` 执行时可恢复
- 隐式的 `checkpoint_ns=""`（默认 namespace），无需前端显式传入

##### 1.2.1 LangGraph 4.x 适配要点

实际运行时环境为 `langgraph 1.2.9` + `langgraph-checkpoint 4.1.1`（而非规划初期预期的 0.2.69）。4.x 引入了多项破坏性变更，以下是实现过程中发现的 3 个关键适配点：

**适配 1: JsonPlusSerializer 仅提供 typed 方法**

4.x 的 `JsonPlusSerializer` 只提供 `dumps_typed()` / `loads_typed()` 方法，**不提供** `dumps()` / `loads()`。
- `dumps_typed(obj)` 返回 `(type_str: str, data: bytes)` 元组，如 `("msgpack", b'\x87\xa1...')`
- `loads_typed((type_str, data))` 根据 type_str 选择反序列化策略

因此元数据（metadata）序列化不能使用 `self.serde.dumps(metadata)`，需改为：
```python
metadata_json = json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None
```
注意反序列化时同样需使用 `json.loads()` 而非 `self.serde.loads()`。

**适配 2: CheckpointTuple 参数名变更**

4.x 中 `CheckpointTuple` 的关键字参数为 `pending_writes`，**不是** 0.2.x 的 `pending_sends`：
```python
# ✅ langgraph-checkpoint 4.x
return CheckpointTuple(
    config=config_out,
    checkpoint=checkpoint,
    metadata=metadata,
    parent_config=parent_config,
    pending_writes=pending_sends,  # 不是 pending_sends=
)
```
使用错误参数名会导致 `TypeError: CheckpointTuple.__new__() got an unexpected keyword argument 'pending_sends'`。

**适配 3: checkpoint_json 需使用 MEDIUMBLOB**

因为 `dumps_typed()` 返回的是 msgpack **二进制**数据（`bytes`），不是 JSON 字符串。MySQL `MEDIUMTEXT` 列无法存储任意二进制数据：
- 写入时报错：`(1366) Incorrect string value`
- 修复：列类型改为 `MEDIUMBLOB`，ORM 模型使用 `Mapped[bytes]`
- `metadata_json` 为 JSON 字符串，仍使用 `MEDIUMTEXT`，不受影响
- 反序列化时从 BLOB 列读出的值已是 `bytes`，不用 `.encode()`

---

#### 1.3 Checkpoint 清理策略

每个 `thread_id` 仅保留最近 **10 个** checkpoint，或 **30 天 TTL**，避免 `sys_agent_checkpoint` 表无限膨胀。

由 `app/services/checkpoint_cleanup_service.py`（新增）实现：

```python
"""
Checkpoint 清理服务

策略：每个 thread 保留最近 10 个 checkpoint，超过 30 天的强制清理。
由 ConversationService.delete() 触发，或通过 lifespan 定时任务执行。
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checkpoint import AgentCheckpoint

logger = logging.getLogger("app")

MAX_CHECKPOINTS_PER_THREAD = 10
MAX_CHECKPOINT_AGE_DAYS = 30


class CheckpointCleanupService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def cleanup_thread(self, thread_id: str) -> int:
        """清理单个 thread 的旧 checkpoint，保留最近 10 个"""
        sub = (
            select(AgentCheckpoint.id)
            .where(AgentCheckpoint.thread_id == thread_id)
            .order_by(AgentCheckpoint.id.desc())
            .limit(MAX_CHECKPOINTS_PER_THREAD)
            .subquery()
        )
        result = await self.db.execute(
            delete(AgentCheckpoint).where(
                AgentCheckpoint.thread_id == thread_id,
                AgentCheckpoint.id.not_in(select(sub.c.id)),
            )
        )
        deleted = result.rowcount
        if deleted:
            logger.info("Checkpoint cleanup: thread=%s deleted=%d", thread_id, deleted)
        return deleted

    async def cleanup_expired(self) -> int:
        """清理所有超过 30 天的 checkpoint（使用 naive datetime 与 created_at 比较）"""
        cutoff = datetime.utcnow() - timedelta(days=MAX_CHECKPOINT_AGE_DAYS)
        result = await self.db.execute(
            delete(AgentCheckpoint).where(AgentCheckpoint.created_at < cutoff)
        )
        return result.rowcount
```

> **`NOT IN` 子查询性能说明**：`cleanup_thread()` 使用 `NOT IN` 子查询保留最近 10 个 checkpoint。在单个 `thread_id` 下 checkpoint 数量较少（≤ 100）时性能良好。若某 thread 积累了 1000+ checkpoint（如高频 Agent 对话），`NOT IN` 子查询可能产生较大的临时表。编码时保留 `NOT IN` 方案（简洁可靠），但在验收阶段需增加大数据量清理性能确认（见 C1 验证步骤）。若性能不达标，可改为两步方案：先 `SELECT` 待删除的 id 列表，再 `IN (...)` 批量删除。

> **注意**：`cutoff` 使用 `datetime.utcnow()`（naive datetime），与 `AgentCheckpoint.created_at` 的 naive datetime 类型一致，避免比较时触发 `TypeError`。

触发时机：
- **主动触发**：`ConversationService.delete()` 删除对话时，先调用 `checkpoint_cleanup_service.cleanup_thread(thread_id)`
- **被动触发**：在 `app/main.py` 现有的 async `lifespan` 上下文管理器中启动和停止周期任务（与 Phase 3 alembic 初始化保持一致的生命周期模式），每 1 小时执行一次 `cleanup_expired()`：

```python
# app/main.py — 在现有 async lifespan 上下文管理器中集成

from contextlib import asynccontextmanager
from fastapi import FastAPI

_checkpoint_cleanup_task: asyncio.Task | None = None


async def _periodic_checkpoint_cleanup():
    """每小时清理过期 checkpoint（带异常保护，单次失败不影响下一周期）"""
    from app.core.database import async_session_factory
    while True:
        try:
            async with async_session_factory() as db:
                service = CheckpointCleanupService(db)
                deleted = await service.cleanup_expired()
                if deleted:
                    logger.info("Periodic checkpoint cleanup: deleted %d", deleted)
        except asyncio.CancelledError:
            break  # 优雅退出
        except Exception as e:
            logger.exception("Checkpoint periodic cleanup error: %s", e)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理（Phase 3 现有 + Phase 4 新增 checkpoint 清理）"""
    global _checkpoint_cleanup_task

    # Phase 3: alembic 自动迁移
    # Phase 4: 启动 checkpoint 周期清理任务
    logger.info("Starting checkpoint cleanup background task")
    _checkpoint_cleanup_task = asyncio.create_task(_periodic_checkpoint_cleanup())

    yield  # 应用正常运行

    # 关闭时取消周期任务，避免 dangling task 警告
    if _checkpoint_cleanup_task and not _checkpoint_cleanup_task.done():
        _checkpoint_cleanup_task.cancel()
        try:
            await _checkpoint_cleanup_task
        except asyncio.CancelledError:
            pass  # 预期取消，静默处理
        except Exception as e:
            logger.exception("Checkpoint cleanup task shutdown error: %s", e)
    logger.info("Checkpoint cleanup background task stopped")
```

> 生命周期模式说明：Phase 3 已使用 `@asynccontextmanager` 模式的 `lifespan`（用于 alembic 自动迁移）。Phase 4 的 checkpoint 清理任务直接合并到同一个 `lifespan` 函数中，不引入新的 `@app.on_event` 装饰器，保持与现有代码一致。

#### 1.4 CHECKPOINT_ENABLED 配置开关

在 `app/config.py` 中新增：

```python
CHECKPOINT_ENABLED: bool = True  # 是否启用 MySQL Checkpointer
```

行为说明：

| `CHECKPOINT_ENABLED` | AgentService 行为 | 效果 |
|:--------------------:|-------------------|------|
| `True`（默认） | 向 graph 传入 `MySQLCheckpointSaver(self.db)` | 对话持久化到 MySQL，中断可恢复 |
| `False` | 向 graph 传入 `None` | LangGraph 回退到 `MemorySaver`（应用重启后状态丢失） |

```python
# app/services/agent_service.py
checkpointer = MySQLCheckpointSaver(self.db) if settings.CHECKPOINT_ENABLED else None
graph = self._get_graph(checkpointer=checkpointer)
```

用途：
- 调试/测试时快速关闭 Checkpointer，避免脏数据干扰
- 若 Checkpointer 出现线上问题，可零停机回退到 MemorySaver
- CI 环境可关闭以跳过 MySQL 依赖

#### 1.5 AgentService 集成 — 修改 `app/services/agent_service.py`

```python
# chat() 和 chat_stream() 中：
from app.agent.checkpointer import MySQLCheckpointSaver

checkpointer = MySQLCheckpointSaver(self.db) if settings.CHECKPOINT_ENABLED else None
graph = self._get_graph(checkpointer=checkpointer)

# 使用 thread_id 绑定对话
config = {"configurable": {"thread_id": f"conv:{conv_id}"}}

# ainvoke 时传入 config
final_state = await graph.ainvoke(initial_state, config)

# astream 时传入 config
async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
```

> **流式粒度说明**：当前输出使用 `astream(stream_mode="updates")`，为**节点级流式**（非 token 级）。具体行为：`call_tool` 节点一次输出，`call_model` 节点完整输出后再通过 `prev_sent_len` 记录增量 delta。这不是真正的 token 级流式（`astream_events(version="v2")` 才能做到），但 SSE 序列中前端看到的 `data:` 行均为累积增量，体验优于一次性输出。Token 级流式已规划到 Phase 5。

> **关键约束**：`_get_graph(checkpointer=...)` 内部必须每次调用 `graph.compile(checkpointer=checkpointer)`，**禁止缓存 compiled graph**。LangGraph 的 `StateGraph.compile()` 会将 checkpointer 嵌入图内部，若缓存编译后的 graph，`CHECKPOINT_ENABLED` 开关（或其他 checkpointer 参数变更）将不会生效——热切换后 cached graph 仍使用旧的 checkpointer（或 None/MemorySaver）。正确做法：
>
> ```python
> def _get_graph(self, checkpointer=None):
>     """每次调用重新编译，确保 checkpointer 参数实时生效"""
>     graph = create_agent_graph(...)
>     return graph.compile(checkpointer=checkpointer)  # 禁止缓存返回值
> ```

关键行为变化：
- **之前**：每次对话从头装载历史 → 截断 → 注入 State → 执行 → 持久化 Message
- **之后**：首次对话同之前；后续轮次复用 checkpoint，LangGraph 自动追加新消息到 State
- **兼容**：Conversation 历史仍双写（checkpoint + `sys_message`），checkpoint 用于 LangGraph 内部恢复，`sys_message` 用于 API 查询/前端展示

---

### 2. 语义标题（P1）

#### 2.1 修改 `app/services/conversation_service.py`

保留现有 `generate_title()` 作为 fallback，新增：

```python
@staticmethod
async def generate_semantic_title(question: str, answer: str, llm_client) -> str:
    """使用 LLM 生成对话标题（≤12 字）"""
    try:
        response = await llm_client.chat.completions.create(
            model=settings.AGENT_MODEL,
            messages=[
                {"role": "system", "content": "为以下对话生成一个简洁的标题（不超过12个汉字）。只返回标题本身，不要引号或额外文字。"},
                {"role": "user", "content": f"问题：{question[:200]}\n回答摘要：{answer[:200]}"},
            ],
            max_tokens=20,
            temperature=0.3,
        )
        title = response.choices[0].message.content.strip()
        return title[:12]  # 与提示词"不超过12个汉字"保持一致，防止模型超长
    except Exception:
        return ConversationService.generate_title(question)  # fallback
```

#### 2.2 修改 `app/services/agent_service.py` — 异步触发时机

**`chat()`（非流式）**：同步调用但设置 5s 超时，失败不影响主流程：

```python
if is_new_conversation:
    try:
        title = await asyncio.wait_for(
            ConversationService.generate_semantic_title(question, answer, self.llm_client),
            timeout=5.0,
        )
        await conv_service.update_title(conv_id, current_user_id, title)
    except (asyncio.TimeoutError, Exception):
        pass  # 标题生成失败不影响主流程
```

**`chat_stream()`（流式）**：使用 FastAPI `BackgroundTasks` 触发（通过路由层的 `background_tasks: BackgroundTasks` 参数注入），不在 `chat_stream()` 内部使用 `asyncio.create_task`，避免 request-scoped 的 `conv_service` 在后台任务执行时已关闭：

```python
# app/services/agent_service.py — chat_stream() 签名增加 BackgroundTasks 参数
from fastapi import BackgroundTasks

async def chat_stream(
    self,
    ...,
    background_tasks: BackgroundTasks | None = None,
):
    ...
    # 在 yield SSE done 事件之后
    if is_new_conversation and background_tasks:
        background_tasks.add_task(
            self._update_title_async,
            conv_id, current_user_id, question, collected_answer,
        )
```

后台任务的独立 `AsyncSession` 实现（不使用 request-scoped 会话）：

```python
async def _update_title_async(self, conv_id, user_id, question, answer):
    """后台异步更新标题（使用独立 AsyncSession，不持有 request-scoped 会话）"""
    from app.core.database import async_session_factory
    from app.services.conversation_service import ConversationService

    async with async_session_factory() as db:
        conv_service = ConversationService(db)
        try:
            title = await ConversationService.generate_semantic_title(
                question, answer, self.llm_client,
            )
            await conv_service.update_title(conv_id, user_id, title)
            logger.info("语义标题生成成功 conv=%d title=%s", conv_id, title)
        except Exception as e:
            logger.warning("语义标题生成失败 conv=%d: %s", conv_id, e)
```

路由层注入 BackgroundTasks：

```python
# app/api/v1/agent_chat.py
from fastapi import BackgroundTasks

@router.post("/agent/chat/stream")
async def agent_chat_stream(..., background_tasks: BackgroundTasks):
    async for event in agent_service.chat_stream(..., background_tasks=background_tasks):
        ...
```

---

### 3. KBMember 缓存接入（P1）

#### 3.1 统一角色常量

在 `app/services/kb_member_cache.py` 顶部新增角色常量，供缓存和权限校验路径统一使用：

```python
# 角色常量（与 models/kb_member.py 保持一致）
ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
```

#### 3.2 修改 `app/services/kb_service.py` — `get_accessible()`

```python
async def get_accessible(self, kb_id: int, user_id: int) -> KnowledgeBase:
    kb = await self.get(kb_id)
    if kb.owner_id == user_id:
        return kb
    if kb.is_public:
        return kb

    # Phase 4: 先查缓存
    from app.services.kb_member_cache import kb_member_cache
    role = await kb_member_cache.get_role(kb_id, user_id)
    if role:
        return kb
    if await kb_member_cache.is_negative(kb_id, user_id):
        # 否定缓存命中 — 该用户在 60s 内已被确认无权限
        raise ForbiddenError("无权访问该知识库")

    # miss → 查 DB → 回填
    from app.repositories.kb_member import KBMemberRepository
    member_repo = KBMemberRepository(self.db)
    member = await member_repo.get_by_kb_and_user(kb_id, user_id)
    if member is not None:
        # 回填整个 KB 的成员缓存（一次 DB 查询缓存整组）
        members = await member_repo.list_by_kb(kb_id)
        member_dict = {str(m.user_id): m.role for m in members}
        await kb_member_cache.set_members(kb_id, member_dict)
        return kb

    # DB miss → 设置否定缓存（60s TTL），避免无权限用户反复穿透到 DB
    await kb_member_cache.set_negative(kb_id, user_id)
    raise ForbiddenError("无权访问该知识库")
```

#### 3.3 否定缓存实现（`app/services/kb_member_cache.py` 新增）

```python
# KBMemberCache 新增方法
NEGATIVE_TTL = 60  # 否定缓存 TTL（秒）

async def set_negative(self, kb_id: int, user_id: int) -> None:
    """设置否定缓存：标记该用户对该 KB 无权限（60s TTL）"""
    key = f"neg:kb_member:{kb_id}:{user_id}"
    await self.redis.setex(key, NEGATIVE_TTL, "1")

async def is_negative(self, kb_id: int, user_id: int) -> bool:
    """检查否定缓存"""
    key = f"neg:kb_member:{kb_id}:{user_id}"
    return await self.redis.exists(key) > 0
```

`invalidate()` 增强 — 同时清除正缓存和否定缓存：

```python
async def invalidate(self, kb_id: int) -> None:
    """失效缓存（正缓存 + 所有用户的否定缓存）

    使用 scan_iter 分批扫描，避免生产环境 Redis 阻塞。
    scan_iter 每次迭代返回一个 key，不阻塞 Redis 主线程。
    """
    # 清除正缓存
    key = self._key(kb_id)
    await self.redis.delete(key)

    # 分批扫描并删除所有该 KB 的否定缓存（避免 KEYS 命令阻塞 Redis）
    neg_pattern = f"neg:kb_member:{kb_id}:*"
    neg_keys = []
    async for key in self.redis.scan_iter(match=neg_pattern):
        neg_keys.append(key)
    if neg_keys:
        await self.redis.delete(*neg_keys)
    logger.debug("Cache invalidated: kb_id=%d neg_keys=%d", kb_id, len(neg_keys))
```

#### 3.4 修改 `app/services/kb_service.py` — `get_editable()`

```python
async def get_editable(self, kb_id: int, user_id: int) -> KnowledgeBase:
    """Phase 4: 获取知识库并校验编辑权限（owner 或 editor），含缓存"""
    kb = await self.get(kb_id)
    if kb.owner_id == user_id:
        return kb

    # Phase 4: 先查缓存
    from app.services.kb_member_cache import kb_member_cache, ROLE_EDITOR, ROLE_OWNER
    role = await kb_member_cache.get_role(kb_id, user_id)
    if role and role in (ROLE_OWNER, ROLE_EDITOR):
        return kb
    # miss 或 缓存的角色无编辑权限 → 查 DB

    from app.repositories.kb_member import KBMemberRepository
    member_repo = KBMemberRepository(self.db)
    member = await member_repo.get_by_kb_and_user(kb_id, user_id)
    if member and member.role in (ROLE_OWNER, ROLE_EDITOR):
        # 回填缓存
        members = await member_repo.list_by_kb(kb_id)
        member_dict = {str(m.user_id): m.role for m in members}
        await kb_member_cache.set_members(kb_id, member_dict)
        return kb

    raise ForbiddenError("无权编辑该知识库")
```

缓存命中逻辑：
- `get_accessible()`：任意角色（owner/editor/viewer）命中即通过；否定缓存命中直接拒绝
- `get_editable()`：仅 owner/editor 命中通过，viewer 命中或 miss → 查 DB 确认

#### 3.5 修改成员 CRUD 方法

`add_member()` / `update_member()` / `remove_member()` 在 DB 写操作成功后调用：

```python
await kb_member_cache.invalidate(kb_id)  # Phase 4: 主动失效（同时清除正缓存和否定缓存）
```

---

### 4. LLM 客户端统一（P2）

#### 4.1 新增 `app/core/llm_client.py`

```python
"""
共享 LLM 客户端工厂

消除 RAGService / QueryRewriteService / AgentService / EmbeddingService
四处独立的 AsyncOpenAI 实例化，统一超时、重试、base_url 配置。
"""
from functools import lru_cache

from openai import AsyncOpenAI

from app.config import settings


@lru_cache(maxsize=2)
def get_llm_client(purpose: str = "default") -> AsyncOpenAI:
    """获取 AsyncOpenAI 客户端（按用途缓存）

    purpose:
        "default" — RAG / QueryRewrite（使用 LLM_MODEL_NAME + LLM_TIMEOUT_SECONDS）
        "agent"   — Agent 对话（使用 AGENT_MODEL + AGENT_TIMEOUT_SECONDS）
        "embed"   — Embedding（使用 EMBEDDING_MODEL）
    """
    if purpose == "agent":
        timeout = settings.AGENT_TIMEOUT_SECONDS
    elif purpose == "embed":
        timeout = 60.0
    else:
        timeout = settings.LLM_TIMEOUT_SECONDS

    return AsyncOpenAI(
        base_url=settings.LLM_BASE_URL.rstrip("/"),
        api_key=settings.LLM_API_KEY,
        timeout=timeout,
        max_retries=settings.LLM_MAX_RETRIES,
    )
```

替换 4 处独立 `AsyncOpenAI(...)` 调用为 `get_llm_client(purpose=...)`。

---

## 前端变更（P0）

### 1. Markdown + 代码高亮 — 修改 `ChatMessage.vue`

新增依赖：`marked`（已安装）+ `highlight.js`（新增）+ `dompurify`（已安装，补充 package.json 声明）。

ChatMessage 中 assistant 消息的 content 渲染改为 markdown：

```vue
<!-- ChatMessage.vue 模板中 -->
<div class="markdown-body" v-html="renderedContent"></div>
```

```typescript
import { marked } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github.css'  // 引入代码高亮主题

// marked v13+ API（见 D2 决策说明）
const renderer = new marked.Renderer()
renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
  const highlighted = lang && hljs.getLanguage(lang)
    ? hljs.highlight(text, { language: lang }).value
    : text
  return `<pre><code class="hljs ${lang || ''}">${highlighted}</code></pre>`
}
marked.use({ renderer })

const renderedContent = computed(() => {
  if (props.role !== 'assistant') return ''
  const html = marked.parse(props.content) as string
  return DOMPurify.sanitize(html)
})
```

> 若实际 `node_modules` 中 marked 版本 < v13，则退回 `marked.setOptions({ highlight })` API。以 `npm ls marked --depth=0` 输出为准。
>
> **类型适配说明**：编码时需以实际安装的 `marked` 版本导出的类型为准。不同版本的 `marked` 对 `Renderer`、`Tokens.Code` 等类型的导出路径可能不同（如 v13+ 从 `marked` 直接导出，v12 可能需要从 `marked/lib/marked.esm.js` 导入类型）。若 TypeScript 报类型不匹配，需要根据 `node_modules/marked/package.json` 中的 `types` 字段确认正确导入路径，必要时使用 `as any` 做局部类型适配。

> highlight.js 主题 CSS 可在 `ChatMessage.vue` 中局部引入，或在 `main.ts` 中全局引入。推荐在 `ChatMessage.vue` 中引入以减少全局样式污染。

### 2. SSE 解析统一 — 提取 `useSSE.ts`

将 `StreamingText.vue` 和 `AgentStreamRenderer.vue` 中重复的 SSE frame 解析逻辑抽象为共享 composable。

关键修正：按 `\n\n` 切分 frame 后，对 `data:` 行做**拼接**（允许多行 data），再 yield 事件。当前按 `\n` 切分会破坏多行消息。

```typescript
// frontend/src/composables/useSSE.ts
export function useSSE(url: string, options?: { signal?: AbortSignal }) {
  const lastEventId = ref<string | null>(null)

  async function* stream(): AsyncGenerator<{ event: string; data: string }> {
    // 断线重连：携带 Last-Event-ID 头部（服务端据此恢复未推送的事件）
    const headers: Record<string, string> = {}
    if (lastEventId.value) {
      headers['Last-Event-ID'] = lastEventId.value
    }

    const response = await fetch(url, {
      signal: options?.signal,
      headers,
    })

    // 检查 HTTP 状态码
    if (!response.ok) {
      throw new Error(`SSE connection failed: ${response.status} ${response.statusText}`)
    }
    if (!response.body) {
      throw new Error('Response body is null — streaming not supported')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // 按 \n\n 切分完整 frame
        const frames = buffer.split('\n\n')
        buffer = frames.pop()!  // 最后一个可能不完整，保留在 buffer

        for (const frame of frames) {
          if (!frame.trim()) continue

          let eventType = ''
          const dataLines: string[] = []

          for (const line of frame.split('\n')) {
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim()
            } else if (line.startsWith('data:')) {
              // 多行 data 拼接（用 \n 连接）
              dataLines.push(line.slice(5).trim())
            } else if (line.startsWith('id:')) {
              // 记录 Last-Event-ID，用于断线重连
              lastEventId.value = line.slice(3).trim()
            }
          }

          // 即使没有 event: 行，只要有 data: 行就 yield
          if (dataLines.length > 0) {
            yield { event: eventType, data: dataLines.join('\n') }
          }
        }
      }
    } finally {
      // 确保 reader 释放（即使循环因 AbortSignal 中断）
      reader.releaseLock()
    }
  }

  return { stream, lastEventId }
}
```

> **注意**：`try/finally` 确保 reader 在循环正常结束或 `AbortSignal` 中断后都能释放锁，避免内存泄漏。`response.ok` 检查确保连接错误时正确报错。
>
> **`Last-Event-ID` 处理策略**：Phase 4 后端不实现 SSE 事件回放机制。`id:` 行的解析和 `Last-Event-ID` 请求头为**预留字段**——前端已实现接收和发送逻辑，但后端当前忽略该头部。这为后续 Phase（如断线重连恢复未推送事件）预留了前端基础设施，届时后端只需开始发送 `id:` 行并解析 `Last-Event-ID` 头部即可启用该功能。

### 3. 对话搜索 — 修改 `ConversationSidebar.vue`

在对话列表顶部添加搜索输入框：

```vue
<el-input
  v-model="searchQuery"
  placeholder="搜索对话..."
  prefix-icon="Search"
  clearable
/>
```

```typescript
const filteredConversations = computed(() => {
  if (!searchQuery.value) return store.conversations
  const q = searchQuery.value.toLowerCase()
  return store.conversations.filter(c =>
    (c.title || '新对话').toLowerCase().includes(q)
  )
})
```

### 4. 对话导出 — 修改 `ConversationSidebar.vue`

新增导出按钮，下载为 Markdown。

**重要**：导出前必须确保目标对话的消息已加载。若当前侧边栏只展示对话列表（`store.conversations`），导出时需要先根据 `conv.id` 加载该对话的消息，或仅允许导出当前已加载对话：

```typescript
async function exportConversation(conv: Conversation) {
  // 如果目标对话不是当前选中的，先加载消息
  let messages = store.messages
  if (conv.id !== store.currentConversationId) {
    messages = await store.loadMessages(conv.id)
  }
  let md = `# ${conv.title || '对话'}\n\n`
  md += `> ${conv.created_at}\n\n---\n\n`
  for (const m of messages) {
    md += `### ${m.role === 'user' ? '👤 User' : '🤖 Assistant'}\n\n`
    md += m.content + '\n\n'
  }
  const blob = new Blob([md], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `${conv.title || 'conversation'}.md`
  a.click(); URL.revokeObjectURL(url)
}
```

> 简化实现：若 `store.loadMessages(conv.id)` 方法不存在，则仅允许导出当前已激活的对话（`conv.id === store.currentConversationId`），未激活时给出提示"请先切换到该对话后再导出"。

---

## Alembic 迁移

```python
"""Phase 4: Agent checkpoint table

Revision ID: phase4_001
Revises: phase3_001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


def upgrade():
    op.create_table(
        "sys_agent_checkpoint",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("checkpoint_id", sa.String(128), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(128), nullable=True),
        sa.Column("checkpoint_ns", sa.String(256), nullable=False, server_default=""),
        sa.Column("type", sa.String(50), nullable=False,
                  comment="语义类型: checkpoint / pending_writes"),
        sa.Column("serde_type", sa.String(50), nullable=False,
                  comment="serde 序列化类型，如 json"),
        # checkpoint_json 为 msgpack 二进制数据，使用 MEDIUMBLOB（最大 16MB）
        sa.Column("checkpoint_json", mysql.MEDIUMBLOB(), nullable=False),
        # metadata_json 为 JSON 字符串，使用 MEDIUMTEXT
        sa.Column("metadata_json", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    # 唯一索引: (thread_id, checkpoint_ns, checkpoint_id)
    op.create_index(
        "idx_ckpt_thread_ns_id", "sys_agent_checkpoint",
        ["thread_id", "checkpoint_ns", "checkpoint_id"],
        unique=True,
    )
    # 优化 cleanup_expired() 删除性能
    op.create_index(
        "idx_ckpt_created_at", "sys_agent_checkpoint",
        ["created_at"],
    )


def downgrade():
    # 先删索引，再删表
    op.drop_index("idx_ckpt_thread_ns_id", table_name="sys_agent_checkpoint")
    op.drop_index("idx_ckpt_created_at", table_name="sys_agent_checkpoint")
    op.drop_table("sys_agent_checkpoint")
```

---

## 文件创建/修改顺序

### 后端

```
 1. app/core/llm_client.py               — 新增: LLM 客户端工厂 (P2)
 2. app/models/checkpoint.py             — 新增: AgentCheckpoint 模型（含 idx_ckpt_created_at）
 3. app/models/__init__.py               — 修改: 注册 AgentCheckpoint
 4. alembic 迁移                          — phase4_001（MEDIUMTEXT + idx_ckpt_created_at）
 5. app/agent/checkpointer.py            — 新增: MySQLCheckpointSaver
 6. app/services/checkpoint_cleanup_service.py — 新增: Checkpoint 清理 (P0)（naive datetime）
 7. app/services/kb_service.py           — 修改: 接入 kb_member_cache + 否定缓存 (P1)
 8. app/services/kb_member_cache.py      — 修改: 新增角色常量 + set_negative / is_negative (P1)
 9. app/services/conversation_service.py — 修改: 新增 generate_semantic_title (P1)
10. app/services/agent_service.py        — 修改: 集成 checkpointer + BackgroundTasks 语义标题 + 清理触发
11. app/services/rag_service.py          — 修改: 使用 get_llm_client (P2)
12. app/services/query_rewrite_service.py — 修改: 使用 get_llm_client (P2)
13. app/services/embedding_service.py    — 修改: 使用 get_llm_client (P2)
14. app/agent/graph.py                   — 修改: 接受 checkpointer 参数
15. app/config.py                         — 修改: 新增 CHECKPOINT_ENABLED 等
16. app/main.py                           — 修改: 初始化 checkpointer + 周期清理（优雅退出）
17. app/api/v1/agent_chat.py              — 修改: 注入 BackgroundTasks
```

### 前端

```
18. npm install highlight.js              — 新增依赖（marked/dompurify 已安装）
19. frontend/src/composables/useSSE.ts          — 新增: 统一 SSE 解析（含错误处理 + Last-Event-ID）
20. frontend/src/composables/useMarkdown.ts      — 新增: 统一 Markdown 渲染
21. frontend/src/components/ChatMessage.vue     — 修改: Markdown + 代码高亮（含 highlight.js 主题）
22. frontend/src/components/ConversationSidebar.vue — 修改: 搜索 + 导出
23. frontend/src/components/StreamingText.vue   — 修改: 使用 useSSE + useMarkdown
24. frontend/src/components/AgentStreamRenderer.vue — 修改: 使用 useSSE + useMarkdown
25. frontend/src/views/qa/QAPage.vue            — 修改: 适配 useSSE + 标题更新（传入 BackgroundTasks）
26. frontend/src/types/index.ts                 — 修改: 新增导出相关类型
27. frontend/package.json                       — 修改: 补充 marked/dompurify/highlight.js 声明
```

---

## 验证步骤

### C1: Checkpointer 持久化

```bash
# Agent 对话首轮
curl -s -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $AT" \
  -H "Content-Type: application/json" \
  -d '{"kb_id": 17, "question": "第一轮问题", "conversation_id": null}' | python -m json.tool
# → 200, 记录 conversation_id

# 查询 checkpoint 表
mysql> SELECT thread_id, checkpoint_id, type, serde_type, LENGTH(checkpoint_json), created_at FROM sys_agent_checkpoint;
# → 应有至少 1 条 type='checkpoint' 记录，serde_type='msgpack'

# 第二轮（同 conversation_id）
curl -s -X POST ... -d '{"kb_id": 17, "question": "第二轮问题", "conversation_id": X}'
# → 200, checkpoint 从首轮恢复，APPEND 消息而非重放全量历史

# 第三轮 — 验证上下文
curl -s -X POST ... -d '{"kb_id": 17, "question": "复述我第一个问题", "conversation_id": X}'
# → 应能复述"第一轮问题"

# 验证清理：超过 10 个 checkpoint 时仅保留最近 10 个
mysql> SELECT COUNT(*) FROM sys_agent_checkpoint WHERE thread_id = 'conv:X';
# → ≤ 10

# 验证大数据量清理性能：向同一 thread 插入 1000+ 条 checkpoint 记录后触发 cleanup_thread()
mysql> SELECT COUNT(*) FROM sys_agent_checkpoint WHERE thread_id = 'conv:perf_test';
# → 1000 (插入后)
# 触发清理后:
mysql> SELECT COUNT(*) FROM sys_agent_checkpoint WHERE thread_id = 'conv:perf_test';
# → ≤ 10, 清理耗时 < 1s（NOT IN 子查询方案性能可接受）
# 若耗时 > 2s，考虑改为两步方案（先 SELECT 再 DELETE ... IN (...))

# 验证 CHECKPOINT_ENABLED=False
CHECKPOINT_ENABLED=false python -c "from app.config import settings; print(settings.CHECKPOINT_ENABLED)"
# → False, checkpointer 为 None, graph 使用 MemorySaver

# 验证 MemorySaver fallback：CHECKPOINT_ENABLED=false 时，首轮对话后重启服务
# Step 1: CHECKPOINT_ENABLED=false 启动服务
# Step 2: 发送首轮对话 — 正常返回，记录 conversation_id
# Step 3: 重启服务（MemorySaver 状态丢失）
# Step 4: 使用同一 conversation_id 发送"复述我第一个问题"
# → 应无法复述（上下文已丢失），验证 MemorySaver 非持久化行为符合预期
```

### C2: Markdown + 代码高亮

1. 前端 Agent 对话中发送：`请解释这段代码：\`\`\`python\nprint("hello")\n\`\`\``
2. ✅ Assistant 回复中代码块应有语法高亮（配色由 highlight.js GitHub 主题提供）
3. ✅ 表格、列表、标题等 Markdown 元素正确渲染
4. ✅ 纯文本消息无异常（向后兼容）

### C3: 对话搜索

1. 创建 5+ 个对话，标题含不同关键词
2. 在侧边栏搜索框输入关键词
3. ✅ 仅匹配的对话可见
4. ✅ 清空搜索恢复全部对话

### C4: 对话导出

1. 点击某对话的导出按钮
2. ✅ 下载 `.md` 文件
3. ✅ 文件内容格式为 Markdown，含标题、时间、用户/助手消息

### C5: 语义标题

1. 新建对话，发送"什么是知识库？"
2. ✅ 对话标题最初为字符截断（"什么是知识库？"），3-5 秒后更新为 LLM 生成的语义标题（如"知识库概念介绍"）
3. ✅ `chat_stream()` SSE 流式对话中，标题更新通过 `BackgroundTasks` 触发，不阻塞 SSE 流
4. ✅ LLM 调用失败时，fallback 到字符串截断（原始行为）

### C6: KBMember 缓存 + 否定缓存

```bash
# 第一次查询 get_accessible
curl -s "http://localhost:8000/api/v1/knowledge-bases/17/members" \
  -H "Authorization: Bearer $AT"
# → DB 查询（首次 miss），回填缓存

# 第二次查询（60s 内）
# → Redis 命中，无 DB 查询

# 无权限用户首次访问 → 否定缓存写入
curl -s "http://localhost:8000/api/v1/knowledge-bases/17/members" \
  -H "Authorization: Bearer $OTHER_USER_TOKEN"
# → 403 Forbidden；Redis 写入否定缓存

# 同用户 60s 内再次访问
# → 否定缓存命中，直接 403，无 DB 查询

# 添加成员 → 缓存失效
curl -s -X POST ... -d '{"user_id": 999, "role": "editor"}'
# → 正缓存 + 否定缓存均被 invalidate

# 第三次查询
# → DB 查询（缓存已失效，重新回填）
```

### C7: 向后兼容验证

| # | 测试项 | 验证 |
|:--:|--------|:----:|
| P1 | `/qa/search` + `/qa/ask` 端点正常 | Phase 1/2 不变 |
| P2 | `/qa/hybrid-search` + `/qa/ask-stream` 正常 | Phase 2 不变 |
| P3 | 文档上传 + SSE 进度正常 | Phase 2/3 不变 |
| P4 | 对话 CRUD + Agent 对话正常 | Phase 3 不变 |
| P5 | 数据迁移可回滚 (downgrade) | `alembic downgrade -1` — 先删索引再删表 |

---

## 风险与缓解

| # | 风险 | 影响 | 缓解 |
|:--:|------|:----:|------|
| R1 | LangGraph `BaseCheckpointSaver` 接口在 1.2.9 / checkpoint 4.1.1 中存在包装性变更（typed 方法、参数重命名） | 中 | 锁定 `langgraph>=1.0,<2.0` + `langgraph-checkpoint>=4.0,<5.0`；参见 §1.2.1 的 3 项适配要点 |
| R2 | Checkpoint msgpack 序列化体积过大（含完整 messages 历史） | 低 | 每个 thread 仅保留最近 10 个 checkpoint，30 天强制清理；定期 `cleanup_expired()`；字段已使用 `MEDIUMBLOB` 预留空间（最大 16MB） |
| R3 | `marked` + `highlight.js` 增加前端打包体积 | 低 | Vite tree-shake，按需引入语言包；`marked` 已在使用中 |
| R4 | LLM 标题生成增加首次对话延迟 | 低 | `chat_stream()` 用 `BackgroundTasks` 异步执行（独立 `AsyncSession`）；`chat()` 设置 5s 超时，失败不影响对话流 |
| R5 | KBMember 缓存 TTL=60s 期间权限变更不可见 | 低 | 所有 mutation 端点立即 `invalidate()`（同时清除正缓存和否定缓存）；60s 仅是失效兜底 |
