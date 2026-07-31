"""
知识库成员数据访问层
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.kb_member import KBMember


class KBMemberRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_kb_and_user(self, kb_id: int, user_id: int) -> KBMember | None:
        result = await self.db.execute(
            select(KBMember).where(
                KBMember.kb_id == kb_id,
                KBMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_kb(self, kb_id: int) -> list[KBMember]:
        result = await self.db.execute(
            select(KBMember)
            .where(KBMember.kb_id == kb_id)
            .order_by(KBMember.created_at)
        )
        return list(result.scalars().all())

    async def list_by_user(self, user_id: int) -> list[KBMember]:
        result = await self.db.execute(
            select(KBMember).where(KBMember.user_id == user_id)
        )
        return list(result.scalars().all())

    async def create(self, data: dict) -> KBMember:
        now = utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        member = KBMember(**data)
        self.db.add(member)
        await self.db.flush()
        return member

    async def update(self, member: KBMember) -> KBMember:
        member.updated_at = utcnow()
        await self.db.flush()
        return member

    async def delete(self, member: KBMember) -> None:
        await self.db.delete(member)
        await self.db.flush()

    async def count_by_kb(self, kb_id: int) -> int:
        result = await self.db.execute(
            select(func.count(KBMember.id)).where(KBMember.kb_id == kb_id)
        )
        return result.scalar() or 0
