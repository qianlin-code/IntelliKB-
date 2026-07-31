"""
对话数据访问层
"""
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.conversation import Conversation
from app.models.message import Message


class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_kb_and_user(
        self, kb_id: int, user_id: int, skip: int, limit: int,
        search: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[list[Conversation], int]:
        """按 updated_at DESC 分页，返回 (items, total)。

        Phase 9: 支持搜索（标题 + 消息内容）和时间范围筛选。
        """
        conditions = [
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        ]
        if kb_id:
            conditions.append(Conversation.kb_id == kb_id)
        if start_date:
            conditions.append(Conversation.created_at >= start_date)
        if end_date:
            conditions.append(Conversation.created_at <= end_date)

        # Phase 9: 搜索 —— 标题匹配 或 消息内容匹配
        conv_ids_from_messages: set[int] | None = None
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            # 查询消息内容匹配的 conversation_id
            msg_result = await self.db.execute(
                select(Message.conversation_id).where(
                    Message.content.contains(search_term)
                ).distinct().limit(500)
            )
            conv_ids_from_messages = {row[0] for row in msg_result.all()}
            # 标题匹配
            conditions.append(
                or_(
                    Conversation.title.contains(search_term),
                    Conversation.id.in_(conv_ids_from_messages) if conv_ids_from_messages else False,
                )
            )

        # 总数
        count_q = select(func.count(Conversation.id)).where(*conditions)
        total = (await self.db.execute(count_q)).scalar() or 0

        # 分页（Phase 9: 置顶排最前，然后按 updated_at 降序）
        q = (
            select(Conversation)
            .where(*conditions)
            .order_by(Conversation.is_pinned.desc(), Conversation.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(q)
        items = result.scalars().all()
        return list(items), total

    async def create(self, data: dict) -> Conversation:
        now = utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        conv = Conversation(**data)
        self.db.add(conv)
        await self.db.flush()
        return conv

    async def get_by_id(self, conv_id: int) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_include_deleted(self, conv_id: int) -> Conversation | None:
        """包含已删除的记录，用于 delete() 中二次检查"""
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        return result.scalar_one_or_none()

    async def update(self, conv: Conversation) -> Conversation:
        conv.updated_at = utcnow()
        await self.db.flush()
        return conv

    async def soft_delete(self, conv: Conversation) -> None:
        conv.deleted_at = utcnow()
        conv.updated_at = utcnow()
        await self.db.flush()

    async def increment_message_count(self, conv_id: int) -> None:
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conv_id)
            .values(message_count=Conversation.message_count + 1)
        )
        await self.db.flush()
