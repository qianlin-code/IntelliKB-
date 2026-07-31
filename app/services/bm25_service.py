"""
BM25 全文检索 —— rank_bm25 内存索引，per-KB 独立

实现细节 #3: asyncio.Lock 保护每个 kb_id 的索引构建，避免并发重复构建。
M2: 懒加载模式 —— 首次查询时 ensure_index() 构建，不随应用启动预加载。
M1: jieba 中文分词 + 空格英文分词。
"""
import asyncio
import logging

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk

logger = logging.getLogger("app")

# 尝试导入 jieba
try:
    import jieba
    _has_jieba = True
except ImportError:
    _has_jieba = False
    logger.warning("jieba 未安装，中文分词将使用字符级切分")


class BM25Service:
    """BM25 全文检索 —— rank_bm25 内存索引，per-KB 独立"""

    def __init__(self):
        # {kb_id: (BM25Okapi, tokenized_corpus, chunk_ids)}
        self._indices: dict[int, tuple[BM25Okapi, list[list[str]], list[int]]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """M1: 中文 jieba 分词 + 英文空格分词"""
        if _has_jieba:
            words = list(jieba.cut(text))
        else:
            # 回退：字符级切分（适用于中文）+ 空格分词（英文）
            import re
            words = re.findall(r'[一-鿿]|[a-zA-Z]+|\d+', text)
        return [w.strip().lower() for w in words if w.strip()]

    async def _build_index(self, kb_id: int, db: AsyncSession) -> None:
        """从 sys_chunk 构建 BM25 索引"""
        # 读取该 KB 所有未删除的 chunk
        result = await db.execute(
            select(DocumentChunk.id, DocumentChunk.content)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(
                Document.kb_id == kb_id,
                DocumentChunk.deleted_at.is_(None),
                Document.deleted_at.is_(None),
            )
            .order_by(DocumentChunk.id)
        )
        rows = result.all()
        if not rows:
            self._indices[kb_id] = (None, [], [])  # type: ignore
            return

        chunk_ids = [row[0] for row in rows]
        tokenized = [self._tokenize(row[1]) for row in rows]
        bm25 = BM25Okapi(tokenized)
        self._indices[kb_id] = (bm25, tokenized, chunk_ids)
        logger.info("BM25 index built for kb_id=%d chunks=%d", kb_id, len(chunk_ids))

    async def ensure_index(self, kb_id: int, db: AsyncSession) -> None:
        """
        M2 懒加载入口 + 实现细节 #3: asyncio.Lock 保护。

        索引不存在则构建，存在则复用。
        """
        if kb_id in self._indices:
            return

        lock = self._locks.setdefault(kb_id, asyncio.Lock())
        async with lock:
            # double-check after acquiring lock
            if kb_id not in self._indices:
                await self._build_index(kb_id, db)

    def invalidate(self, kb_id: int) -> None:
        """M2: 失效内存索引（文档变更时调用），下次 ensure_index() 自动重建"""
        self._indices.pop(kb_id, None)
        logger.info("BM25 index invalidated for kb_id=%d", kb_id)

    async def search(
        self, kb_id: int, query: str, top_k: int = 20, db: AsyncSession | None = None,
    ) -> list[dict]:
        """
        BM25 检索 → [{chunk_id, content, score}, ...]

        如果 db 不为 None 且索引不存在，自动构建。
        """
        await self.ensure_index(kb_id, db) if db else None

        entry = self._indices.get(kb_id)
        if entry is None or entry[0] is None:
            return []

        bm25, tokenized_corpus, chunk_ids = entry
        tokenized_query = self._tokenize(query)
        scores = bm25.get_scores(tokenized_query)

        # 按分数降序取 top_k
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results: list[dict] = []
        for idx, score in indexed[:top_k]:
            if score <= 0:
                continue
            results.append({
                "chunk_id": chunk_ids[idx],
                "content": " ".join(tokenized_corpus[idx]),
                "score": float(score),
                "document_id": 0,  # 由调用方通过 chunk_id 回填
            })
        return results


# 模块级单例
bm25_service = BM25Service()
