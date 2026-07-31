"""
Redis Pub/Sub 进度推送管理器

替代基于 key 轮询的 SSE 进度（L6 限制），支持多 Worker 场景：
- Worker A 完成文档解析 → PUBLISH doc:progress:{doc_id}
- 所有 Worker 收到 → 持有 SSE 连接的 Worker 推送给前端
- 每个 SSE 连接创建独立的 PubSub 对象，断开后立即清理
"""
import json
import logging

from app.core.redis_client import get_redis

logger = logging.getLogger("app")


class ProgressPubSubManager:
    """Redis Pub/Sub 进度推送"""

    CHANNEL_PREFIX = "doc:progress:"

    async def publish(self, doc_id: int, stage: str, progress: float, message: str) -> None:
        """发布进度消息"""
        try:
            data = json.dumps({
                "stage": stage,
                "progress": progress,
                "message": message,
            }, ensure_ascii=False)
            channel = f"{self.CHANNEL_PREFIX}{doc_id}"
            r = await get_redis()
            count = await r.publish(channel, data)
            logger.debug("Pub/Sub 发布 doc=%d stage=%s subscribers=%d", doc_id, stage, count)
        except Exception as e:
            logger.warning("Pub/Sub 发布失败 doc=%d: %s", doc_id, str(e))

    async def publish_complete(self, doc_id: int, chunk_count: int) -> None:
        """发布完成事件"""
        await self.publish(doc_id, "done", 1.0, f"完成，共 {chunk_count} 块")

    async def publish_error(self, doc_id: int, error_msg: str) -> None:
        """发布错误事件"""
        await self.publish(doc_id, "error", 0.0, f"解析失败: {error_msg}")


# 模块级单例
progress_pubsub = ProgressPubSubManager()
