"""
认证服务 —— 注册/登录/刷新/登出/API Key 管理

N4: refresh 轮转时同步撤销旧 access token。
  - 若传入 current_access_token → 解码后黑名单
  - 若未传 → SCAN Redis 中该用户所有 access jti 批量清除
T4: 兜底 TTL 使用 ACCESS_TOKEN_EXPIRE_MINUTES × 60
T5: 单次完整 SCAN 迭代（decode_responses=True 时 keys 已是 str）
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    hash_secret, verify_secret_async,
    create_access_token, create_refresh_token, decode_token, generate_api_key,
)
from app.core.redis_client import get_redis, blacklist_set
from app.core.exceptions import UnauthorizedError, ConflictError, NotFoundError
from app.core.time_utils import utcnow
from app.repositories.user import UserRepository

logger = logging.getLogger("app")


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = UserRepository(db)

    async def register(self, username: str, password: str, email: str | None = None):
        if await self.repo.get_by_username(username):
            raise ConflictError("用户名已存在")
        if email and await self.repo.get_by_email(email):
            raise ConflictError("邮箱已被注册")
        user = await self.repo.create({
            "username": username,
            "password_hash": hash_secret(password),
            "email": email,
        })
        return user

    async def login(self, username: str, password: str) -> dict:
        user = await self.repo.get_by_username(username)
        if not user:
            raise UnauthorizedError("用户名或密码错误")
        if not await verify_secret_async(password, user.password_hash):
            raise UnauthorizedError("用户名或密码错误")
        if not user.is_active:
            raise UnauthorizedError("用户已被禁用，请联系管理员")

        access_token = create_access_token(user.id, user.username)
        refresh_token = create_refresh_token(user.id, user.username)

        # N4: 注册 access jti 到 Redis（Redis 不可用时跳过）
        try:
            access_payload = decode_token(access_token)
            r = await get_redis()
            await r.setex(
                f"access:{user.id}:{access_payload['jti']}",
                settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 + 60,
                "1",
            )
        except Exception:
            pass

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def refresh_token(
        self, refresh_token: str, current_access_token: str | None = None
    ) -> dict:
        """N4: 刷新 token，同时撤销旧 access。"""
        try:
            payload = decode_token(refresh_token)
        except Exception:
            raise UnauthorizedError("Refresh Token 无效或已过期")

        if payload.get("type") != "refresh":
            raise UnauthorizedError("Token 类型错误，需要 refresh token")

        user_id = int(payload["sub"])
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise UnauthorizedError("用户不存在")

        # 旧 refresh 加入黑名单
        await blacklist_set(payload["jti"], payload["exp"])

        # N4: 撤销旧 access token
        r = await get_redis()
        if current_access_token:
            try:
                access_payload = decode_token(current_access_token)
                await blacklist_set(access_payload["jti"], access_payload["exp"])
            except Exception:
                pass
        else:
            # T5: 单次完整 SCAN 迭代（decode_responses=True 时 keys 已是 str）
            cursor = 0
            pattern = f"access:{user_id}:*"
            while True:
                cursor, keys = await r.scan(cursor, match=pattern, count=100)
                for key in keys:
                    jti = key.split(":")[-1]
                    # T4: 最大兜底 TTL = ACCESS_TOKEN_EXPIRE_MINUTES × 60
                    # 精确 TTL 需要把 exp 写入 value，Phase 0 简化用 max TTL
                    await r.setex(
                        f"blacklist:{jti}",
                        settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                        "1",
                    )
                if cursor == 0:
                    break

        # 生成新双 token
        new_access = create_access_token(user.id, user.username)
        new_refresh = create_refresh_token(user.id, user.username)

        new_access_payload = decode_token(new_access)
        await r.setex(
            f"access:{user.id}:{new_access_payload['jti']}",
            settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 + 60,
            "1",
        )

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def logout(self, user_id: int, access_token: str, refresh_token: str | None = None):
        try:
            payload = decode_token(access_token)
            await blacklist_set(payload["jti"], payload["exp"])
        except Exception:
            pass
        if refresh_token:
            try:
                payload = decode_token(refresh_token)
                await blacklist_set(payload["jti"], payload["exp"])
            except Exception:
                pass

    async def generate_user_api_key(self, user_id: int) -> str:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("用户不存在")
        raw, hashed, prefix, expires_at = generate_api_key()
        user.api_key_hash = hashed
        user.api_key_prefix = prefix
        user.api_key_expires_at = expires_at
        user.api_key_enabled = True
        await self.repo.update(user)
        return raw

    async def revoke_api_key(self, user_id: int) -> None:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("用户不存在")
        user.api_key_hash = None
        user.api_key_prefix = None
        user.api_key_expires_at = None
        user.api_key_enabled = False
        await self.repo.update(user)

    async def get_api_key_info(self, user_id: int) -> dict:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("用户不存在")
        return {
            "prefix": user.api_key_prefix,
            "expires_at": user.api_key_expires_at.isoformat() if user.api_key_expires_at else None,
            "last_used_at": user.api_key_last_used_at.isoformat() if user.api_key_last_used_at else None,
            "enabled": user.api_key_enabled,
        }
