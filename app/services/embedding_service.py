"""
Embedding 服务 —— 通过 Ollama 兼容 API 生成文本向量

Phase 4: 使用共享 LLM 客户端工厂 (get_llm_client)。
"""
import logging

from app.config import settings
from app.core.llm_client import get_llm_client

logger = logging.getLogger("app")


class EmbeddingService:
    """通过 Ollama 兼容 OpenAI API 生成文本向量"""

    def __init__(self):
        self.client, _ = get_llm_client(purpose="embed")
        self.model = settings.EMBEDDING_MODEL
        self.dim = settings.EMBEDDING_DIM
        self._warmed_up = False

    async def warmup(self) -> None:
        """预热：发送一次 embedding 请求，让 Ollama 加载模型到内存"""
        if self._warmed_up:
            return
        try:
            await self.embed("warmup")
            self._warmed_up = True
            logger.info("Embedding 模型 %s 预热完成", self.model)
        except Exception:
            logger.warning("Embedding 预热失败，首次请求可能较慢", exc_info=True)

    async def embed(self, text: str) -> list[float]:
        """单文本向量化"""
        response = await self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """批量向量化，按 batch_size 切分循环调用 Ollama API"""
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await self.client.embeddings.create(
                model=self.model,
                input=batch,
            )
            all_embeddings.extend([d.embedding for d in response.data])
        return all_embeddings


# 模块级单例
embedding_service = EmbeddingService()
