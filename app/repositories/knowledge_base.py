"""
知识库数据访问层
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.knowledge_base import KnowledgeBase


class KBRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, kb_id: int) -> KnowledgeBase | None:
        result = await self.db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_owner(
        self, owner_id: int, skip: int = 0, limit: int = 20
    ) -> list[KnowledgeBase]:
        result = await self.db.execute(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.owner_id == owner_id,
                KnowledgeBase.deleted_at.is_(None),
            )
            .order_by(KnowledgeBase.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_owner(self, owner_id: int) -> int:
        result = await self.db.execute(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.owner_id == owner_id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def create(self, data: dict) -> KnowledgeBase:
        now = utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        kb = KnowledgeBase(**data)
        self.db.add(kb)
        await self.db.flush()
        return kb

    async def update(self, kb: KnowledgeBase) -> KnowledgeBase:
        kb.updated_at = utcnow()
        await self.db.flush()
        return kb

    async def soft_delete(self, kb: KnowledgeBase) -> None:
        kb.deleted_at = utcnow()
        kb.updated_at = utcnow()
        await self.db.flush()
