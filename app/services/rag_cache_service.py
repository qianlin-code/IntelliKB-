"""
RAG 检索结果 Redis 缓存（D5）

O4: 文档上传/删除时异步调用 invalidate()，不阻塞主流程。
"""
import hashlib
import json
import logging

from app.config import settings
from app.core.redis_client import get_redis, cache_get, cache_set

logger = logging.getLogger("app")


class RAGCacheService:
    """RAG 检索结果 Redis 缓存"""

    KEY_PREFIX = "rag:cache"

    def _key(self, kb_id: int, question: str) -> str:
        normalized = question.strip().lower()
        return f"{self.KEY_PREFIX}:{kb_id}:{hashlib.md5(normalized.encode()).hexdigest()}"

    async def get(self, kb_id: int, question: str) -> list[dict] | None:
        if not settings.RAG_CACHE_ENABLED:
            return None
        raw = await cache_get(self._key(kb_id, question))
        if raw is None:
            return None
        try:
            data = raw.decode() if isinstance(raw, bytes) else raw
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set(self, kb_id: int, question: str, results: list[dict]) -> None:
        if not settings.RAG_CACHE_ENABLED:
            return
        key = self._key(kb_id, question)
        value = json.dumps(results, ensure_ascii=False)
        await cache_set(key, value, ttl=settings.RAG_CACHE_TTL_SECONDS)
        logger.debug("Cache set: %s (%d results)", key, len(results))

    async def invalidate(self, kb_id: int) -> None:
        """
        O4: 文档变更时失效该 KB 所有缓存（SCAN 匹配删除）。
        调用方使用 asyncio.create_task() 触发，不阻塞主流程。
        """
        r = await get_redis()
        pattern = f"{self.KEY_PREFIX}:{kb_id}:*"
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await r.scan(cursor, match=pattern, count=100)
            if keys:
                await r.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        if deleted:
            logger.info("Cache invalidated: kb_id=%d deleted=%d keys", kb_id, deleted)


# 模块级单例
rag_cache_service = RAGCacheService()
