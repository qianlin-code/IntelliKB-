"""
Redis 客户端封装 —— 异步连接管理 + 基础操作 + 黑名单 TTL
"""
import asyncio
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.config import settings

# 全局 Redis 连接池 + 初始化锁（防并发竞态）
_redis_pool: aioredis.Redis | None = None
_init_lock = asyncio.Lock()


async def get_redis() -> aioredis.Redis:
    """获取 Redis 连接（线程安全，懒初始化）"""
    global _redis_pool
    if _redis_pool is None:
        async with _init_lock:
            if _redis_pool is None:
                kwargs: dict = {
                    "encoding": "utf-8",
                    "decode_responses": True,
                    "max_connections": settings.REDIS_MAX_CONNECTIONS,
                    "socket_timeout": settings.REDIS_SOCKET_TIMEOUT,
                    "socket_connect_timeout": settings.REDIS_SOCKET_TIMEOUT,
                }
                if settings.REDIS_PASSWORD:
                    kwargs["password"] = settings.REDIS_PASSWORD
                _redis_pool = aioredis.from_url(settings.redis_url, **kwargs)
    return _redis_pool


async def close_redis():
    """关闭 Redis 连接池"""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None


async def check_redis_connection() -> bool:
    """健康检查 —— 测试 Redis 连通性"""
    try:
        r = await get_redis()
        await r.ping()
        return True
    except Exception:
        return False


# ── 工具函数 ──

async def cache_get(key: str) -> str | None:
    """缓存读取"""
    r = await get_redis()
    return await r.get(key)


async def cache_set(key: str, value: str, ttl: int = 300) -> None:
    """缓存写入，默认 5 分钟过期"""
    r = await get_redis()
    await r.set(key, value, ex=ttl)


async def cache_delete(key: str) -> None:
    """缓存删除"""
    r = await get_redis()
    await r.delete(key)


async def blacklist_set(jti: str, exp_timestamp: int | float) -> None:
    """
    将 JWT jti 加入黑名单，TTL = exp - now()。
    避免黑名单 key 永久占用 Redis。

    exp_timestamp 来自 JWT payload 的 exp 字段（UTC 时间戳）。
    """
    now_ts = datetime.now(UTC).timestamp()
    ttl = max(1, int(exp_timestamp - now_ts))
    r = await get_redis()
    await r.setex(f"blacklist:{jti}", ttl, "1")
