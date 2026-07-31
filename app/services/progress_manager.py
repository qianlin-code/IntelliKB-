"""
文档解析进度管理 —— 通过 Redis key 中转
"""
import json
import logging

from app.core.redis_client import cache_get, cache_set, cache_delete

logger = logging.getLogger("app")


class ProgressManager:
    """文档解析进度管理"""

    PROGRESS_KEY = "doc:progress:{doc_id}"
    PROGRESS_TTL = 300  # 5 分钟自动清理

    async def set(self, doc_id: int, stage: str, progress: float, message: str) -> None:
        """写入进度"""
        data = json.dumps({
            "stage": stage,
            "progress": progress,
            "message": message,
        }, ensure_ascii=False)
        await cache_set(
            self.PROGRESS_KEY.format(doc_id=doc_id),
            data,
            ttl=self.PROGRESS_TTL,
        )
        logger.debug("Progress doc=%d stage=%s progress=%.2f", doc_id, stage, progress)

    async def get(self, doc_id: int) -> dict | None:
        """读取进度"""
        raw = await cache_get(self.PROGRESS_KEY.format(doc_id=doc_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def clear(self, doc_id: int) -> None:
        """清理进度 key"""
        await cache_delete(self.PROGRESS_KEY.format(doc_id=doc_id))


# 模块级单例
progress_manager = ProgressManager()
