"""
消息数据访问层
"""
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.message import Message


class MessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Message:
        now = utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        msg = Message(**data)
        self.db.add(msg)
        await self.db.flush()
        return msg

    async def create_batch(self, messages: list[dict]) -> list[Message]:
        now = utcnow()
        for m in messages:
            m.setdefault("created_at", now)
            m.setdefault("updated_at", now)
        objs = [Message(**m) for m in messages]
        self.db.add_all(objs)
        await self.db.flush()
        return objs

    async def list_by_conversation(
        self, conv_id: int, before_id: int | None, limit: int,
    ) -> tuple[list[Message], bool]:
        """
        游标分页，按 id ASC 返回。
        has_more = 实际结果 > limit，因此取 limit+1 条判断。
        """
        q = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.id.asc())
            .limit(limit + 1)
        )
        if before_id is not None:
            q = q.where(Message.id < before_id)

        result = await self.db.execute(q)
        rows = result.scalars().all()

        has_more = len(rows) > limit
        items = rows[:limit]
        return list(items), has_more

    async def hard_delete_by_conversation(self, conv_id: int) -> int:
        """硬删除对话下所有消息，返回删除条数"""
        result = await self.db.execute(
            delete(Message).where(Message.conversation_id == conv_id)
        )
        await self.db.flush()
        return result.rowcount

    async def get_by_id(self, msg_id: int) -> Message | None:
        result = await self.db.execute(
            select(Message).where(Message.id == msg_id)
        )
        return result.scalar_one_or_none()
