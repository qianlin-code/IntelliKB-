"""
KBMember 缓存一致性优化

查询路径：先查 Redis hash → miss 则查 MySQL 并回填
失效策略：新增/修改/移除成员时主动 DEL（同时清除正缓存和否定缓存）
"""
import json
import logging

from app.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger("app")

CACHE_PREFIX = "kb_member:cache:"
NEGATIVE_PREFIX = "neg:kb_member:"
NEGATIVE_TTL = 60  # 否定缓存 TTL（秒）

# ── Phase 4: 角色常量（与 models/kb_member.py 保持一致）──
ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"


class KBMemberCache:
    """KBMember Redis hash 缓存"""

    async def get_members(self, kb_id: int) -> dict[str, str] | None:
        """获取成员缓存 {user_id: role}"""
        try:
            r = await get_redis()
            key = f"{CACHE_PREFIX}{kb_id}"
            data = await r.hgetall(key)
            if data:
                return {str(k): str(v) for k, v in data.items()}
            return None
        except Exception as e:
            logger.warning("KBMember 缓存读取失败 kb=%d: %s", kb_id, str(e))
            return None

    async def set_members(self, kb_id: int, members: dict[str, str]) -> None:
        """写入成员缓存，TTL=60s"""
        try:
            r = await get_redis()
            key = f"{CACHE_PREFIX}{kb_id}"
            await r.hset(key, mapping=members)
            await r.expire(key, settings.MEMBER_CACHE_TTL_SECONDS)
        except Exception as e:
            logger.warning("KBMember 缓存写入失败 kb=%d: %s", kb_id, str(e))

    async def invalidate(self, kb_id: int) -> None:
        """失效缓存（正缓存 + 所有用户的否定缓存）

        使用 scan_iter 分批扫描，避免生产环境 Redis 阻塞。
        scan_iter 每次迭代返回一个 key，不阻塞 Redis 主线程。
        """
        try:
            r = await get_redis()
            # 清除正缓存
            key = f"{CACHE_PREFIX}{kb_id}"
            await r.delete(key)

            # 分批扫描并删除所有该 KB 的否定缓存
            neg_pattern = f"{NEGATIVE_PREFIX}{kb_id}:*"
            neg_keys = []
            async for key in r.scan_iter(match=neg_pattern):
                neg_keys.append(key)
            if neg_keys:
                await r.delete(*neg_keys)
            logger.debug("Cache invalidated: kb_id=%d neg_keys=%d", kb_id, len(neg_keys))
        except Exception as e:
            logger.warning("KBMember 缓存失效失败 kb=%d: %s", kb_id, str(e))

    async def get_role(self, kb_id: int, user_id: int) -> str | None:
        """获取指定用户的角色（先缓存后 DB）"""
        members = await self.get_members(kb_id)
        if members:
            return members.get(str(user_id))
        return None

    # ── Phase 4: 否定缓存 ──

    async def set_negative(self, kb_id: int, user_id: int) -> None:
        """设置否定缓存：标记该用户对该 KB 无权限（60s TTL）"""
        try:
            r = await get_redis()
            key = f"{NEGATIVE_PREFIX}{kb_id}:{user_id}"
            await r.setex(key, NEGATIVE_TTL, "1")
        except Exception as e:
            logger.warning("否定缓存写入失败 kb=%d user=%d: %s", kb_id, user_id, str(e))

    async def is_negative(self, kb_id: int, user_id: int) -> bool:
        """检查否定缓存"""
        try:
            r = await get_redis()
            key = f"{NEGATIVE_PREFIX}{kb_id}:{user_id}"
            return await r.exists(key) > 0
        except Exception as e:
            logger.warning("否定缓存查询失败 kb=%d user=%d: %s", kb_id, user_id, str(e))
            return False


# 模块级单例
kb_member_cache = KBMemberCache()
