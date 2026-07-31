"""
Checkpoint 清理服务

策略：每个 thread 保留最近 10 个 checkpoint，超过 30 天的强制清理。
由 ConversationService.delete() 触发，或通过 lifespan 定时任务执行。
"""
import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.checkpoint import AgentCheckpoint

logger = logging.getLogger("app")

MAX_CHECKPOINTS_PER_THREAD = 10
MAX_CHECKPOINT_AGE_DAYS = 30


class CheckpointCleanupService:
    """Checkpoint 清理"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def cleanup_thread(self, thread_id: str) -> int:
        """清理单个 thread 的旧 checkpoint，保留最近 10 个

        使用 NOT IN 子查询保留最近 10 个 checkpoint。
        单个 thread 下 checkpoint 数量较少（≤ 100）时性能良好。
        """
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
        cutoff = utcnow() - timedelta(days=MAX_CHECKPOINT_AGE_DAYS)
        result = await self.db.execute(
            delete(AgentCheckpoint).where(AgentCheckpoint.created_at < cutoff)
        )
        deleted = result.rowcount
        if deleted:
            logger.info("Checkpoint expired cleanup: deleted %d records", deleted)
        return deleted
