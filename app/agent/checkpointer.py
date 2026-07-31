"""
MySQL Checkpointer —— LangGraph BaseCheckpointSaver 实现

基于 MySQL 持久化 LangGraph 检查点，支持：
- 对话中断恢复
- checkpoint_ns 隔离（跨 namespace 同名 checkpoint_id 不冲突）
- msgpack 序列化（JsonPlusSerializer）

列语义：
- type:   语义类型 "checkpoint" / "pending_writes"
- serde_type: serde 序列化类型字符串，由 dumps_typed 返回，反序列化时使用

注意：JsonPlusSerializer（langgraph >= 4.x）仅提供 dumps_typed / loads_typed，
不提供 dumps / loads 方法。元数据为简单 dict，直接使用 json 模块处理。

每个方法独立管理 AsyncSession（async with self._session_factory() as session），
避免与 LangGraph 工具节点的请求级 session 产生 aiomysql 并发冲突。
"""
import json
import logging
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import RunnableConfig
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checkpoint import AgentCheckpoint

logger = logging.getLogger("app")


class MySQLCheckpointSaver(BaseCheckpointSaver):
    """LangGraph MySQL Checkpointer（langgraph 1.x / checkpoint 4.x）

    通过 async_session_factory 为每个操作创建独立 session，
    与 AgentService 工具节点的请求级 session 完全隔离。
    """

    def __init__(self, session_factory: Callable[[], AsyncSession]):
        """从 async_session_factory 创建 Checkpointer。

        session_factory: 一个返回 AsyncSession 上下文管理器的 callable，
                         如 app.core.database.async_session_factory。

        示例:
            from app.core.database import async_session_factory
            checkpointer = MySQLCheckpointSaver(async_session_factory)
        """
        super().__init__(serde=JsonPlusSerializer())
        self._session_factory = session_factory

    # ── 读操作 ──

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """通过 thread_id + checkpoint_ns + checkpoint_id 查询检查点

        每个方法内 async with self._session_factory() as session，
        读写完成后自动 commit + close，不持有跨调用 session。
        """
        thread_id = config["configurable"].get("thread_id", "")
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        query = select(AgentCheckpoint).where(
            AgentCheckpoint.thread_id == thread_id,
            AgentCheckpoint.checkpoint_ns == checkpoint_ns,
            AgentCheckpoint.type == "checkpoint",
        )

        if checkpoint_id:
            query = query.where(AgentCheckpoint.checkpoint_id == checkpoint_id)
        else:
            # 取最新 checkpoint
            query = query.order_by(desc(AgentCheckpoint.id)).limit(1)

        async with self._session_factory() as session:
            result = await session.execute(query)
            row = result.scalar_one_or_none()

            if row is None:
                return None

            # 使用 serde_type 反序列化（checkpoint_json 为 MEDIUMBLOB bytes）
            checkpoint = self.serde.loads_typed(
                (row.serde_type, row.checkpoint_json)
            )
            metadata = {}
            if row.metadata_json:
                metadata = json.loads(row.metadata_json)

            parent_config = None
            if row.parent_checkpoint_id:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row.parent_checkpoint_id,
                    }
                }

            # 查询 pending_writes（按祖先 checkpoint_id + 语义 type 匹配）
            pending_query = select(AgentCheckpoint).where(
                AgentCheckpoint.thread_id == thread_id,
                AgentCheckpoint.checkpoint_ns == checkpoint_ns,
                AgentCheckpoint.parent_checkpoint_id == row.checkpoint_id,
                AgentCheckpoint.type == "pending_writes",
            ).order_by(desc(AgentCheckpoint.id)).limit(1)
            pending_result = await session.execute(pending_query)
            pending_row = pending_result.scalar_one_or_none()
            pending_sends = []
            if pending_row:
                pending_sends = self.serde.loads_typed(
                    (pending_row.serde_type, pending_row.checkpoint_json)
                )

        config_out = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": row.checkpoint_id,
            }
        }

        return CheckpointTuple(
            config=config_out,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_sends,
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, str] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> list[CheckpointTuple]:
        """按 thread_id 分页查询历史检查点"""
        if config is None:
            return []

        thread_id = config["configurable"].get("thread_id", "")
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")

        query = select(AgentCheckpoint).where(
            AgentCheckpoint.thread_id == thread_id,
            AgentCheckpoint.checkpoint_ns == checkpoint_ns,
            AgentCheckpoint.type == "checkpoint",
        )

        if before:
            before_id = before["configurable"].get("checkpoint_id")
            if before_id:
                query = query.where(AgentCheckpoint.checkpoint_id < before_id)

        query = query.order_by(desc(AgentCheckpoint.id))

        if limit:
            query = query.limit(limit)

        async with self._session_factory() as session:
            result = await session.execute(query)
            rows = result.scalars().all()

            tuples = []
            for row in rows:
                checkpoint = self.serde.loads_typed(
                    (row.serde_type, row.checkpoint_json)
                )
                metadata_val = {}
                if row.metadata_json:
                    metadata_val = json.loads(row.metadata_json)
                tuples.append(CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": row.checkpoint_id,
                        }
                    },
                    checkpoint=checkpoint,
                    metadata=metadata_val,
                ))

        return tuples

    # ── 写操作 ──

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Any,
        metadata: dict,
        new_versions: dict[str, str | int | float],
    ) -> RunnableConfig:
        """写入检查点，返回包含新 checkpoint_id 的 config

        使用独立 session，add + commit 后立即释放。
        """
        thread_id = config["configurable"].get("thread_id", "")
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        type_str, checkpoint_json_bytes = self.serde.dumps_typed(checkpoint)
        metadata_json = json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None

        row = AgentCheckpoint(
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=checkpoint["id"],
            parent_checkpoint_id=parent_checkpoint_id,
            type="checkpoint",
            serde_type=type_str,
            checkpoint_json=checkpoint_json_bytes,
            metadata_json=metadata_json,
        )

        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

        logger.debug(
            "Checkpoint saved: thread=%s checkpoint=%s ns=%s",
            thread_id, checkpoint["id"], checkpoint_ns,
        )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """写入 pending channel writes（中断恢复用）

        使用独立 session，add + commit 后立即释放。
        """
        thread_id = config["configurable"].get("thread_id", "")
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id", "")

        type_str, writes_json_bytes = self.serde.dumps_typed(writes)

        row = AgentCheckpoint(
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=f"{checkpoint_id}:writes:{task_id}",
            parent_checkpoint_id=checkpoint_id,
            type="pending_writes",
            serde_type=type_str,
            checkpoint_json=writes_json_bytes,
        )

        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
