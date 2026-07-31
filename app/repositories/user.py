"""
用户数据访问层
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.user import User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, data: dict) -> User:
        now = utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        user = User(**data)
        self.db.add(user)
        await self.db.flush()
        # 立即提交事务：FastAPI get_db() 的 commit 发生在响应 yield 之后，
        # 注册/更新后若客户端立刻发起下一次请求（如登录），可能读到未提交数据。
        await self.db.commit()
        return user

    async def update(self, user: User) -> User:
        user.updated_at = utcnow()
        await self.db.flush()
        # 同上：确保 API Key 生成/撤销等写操作在返回前持久化。
        await self.db.commit()
        return user
