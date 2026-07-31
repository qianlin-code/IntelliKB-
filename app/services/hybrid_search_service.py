"""
混合检索服务 —— BM25 + 向量混合检索 + RRF 融合 + Rerank + Cache
"""
import asyncio
import logging
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.schemas.qa import SearchResult
from app.services.bm25_service import bm25_service
from app.services.embedding_service import embedding_service
from app.services.vector_store import vector_store_service
from app.services.rerank_service import rerank_service
from app.services.rag_cache_service import rag_cache_service
from app.services.query_rewrite_service import query_rewrite_service
from app.services.kb_service import KBService

logger = logging.getLogger("app")


class HybridSearchService:
    """BM25 + 向量混合检索 + RRF 融合 + Rerank"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(
        self,
        kb_id: int,
        question: str,
        user: User,
        top_k: int = 5,
        use_rerank: bool = True,
        use_cache: bool = True,
        history: list[dict] | None = None,
    ) -> tuple[list[SearchResult], str | None]:
        """
        完整检索管线:
        1. [可选] Query Rewrite (M5: history >= 2 时)
        2. [可选] Redis 缓存命中 → 直接返回
        3. 并行 BM25 (HYBRID_BM25_TOP_K) + Vector (HYBRID_VECTOR_TOP_K)
        4. RRF 融合 → HYBRID_BM25_TOP_K
        5. [可选] Cross-encoder Rerank → top_k
        6. [可选] 写入 Redis 缓存
        7. 返回 (SearchResult[], rewritten_query | None)
        """
        # 校验权限
        kb_service = KBService(self.db)
        await kb_service.get_accessible(kb_id, user.id)

        # 1. Query Rewrite (M5: 仅多轮时)
        rewritten_query = None
        search_question = question
        if history and len(history) >= 2:
            rewritten_query = await query_rewrite_service.rewrite(question, history)
            search_question = rewritten_query if rewritten_query != question else question

        # 2. Redis 缓存
        if use_cache:
            cached = await rag_cache_service.get(kb_id, search_question)
            if cached:
                logger.debug("Cache hit: kb=%d question='%s'", kb_id, search_question[:50])
                results = [SearchResult(**r) for r in cached]
                return results, rewritten_query

        # 3. 并行 BM25 + 向量检索
        bm25_top_k = settings.HYBRID_BM25_TOP_K
        vector_top_k = settings.HYBRID_VECTOR_TOP_K

        bm25_results, vector_results = await asyncio.gather(
            bm25_service.search(kb_id, search_question, bm25_top_k, self.db),
            self._vector_search(kb_id, search_question, vector_top_k),
        )

        # 4. RRF 融合
        rrf_k = settings.HYBRID_RRF_K
        merged = self._rrf_fusion(bm25_results, vector_results, k=rrf_k)

        # 回填 document_id（从 chunk 查询）
        merged = await self._fill_document_ids(merged)

        # 5. Rerank
        if use_rerank and settings.RERANK_ENABLED:
            merged = await rerank_service.rerank(search_question, merged, top_k)
        else:
            merged = merged[:top_k]

        # 6. Write cache
        if use_cache and merged:
            cache_data = [
                {
                    "chunk_id": r.get("chunk_id", 0),
                    "document_id": r.get("document_id", 0),
                    "content": r.get("content", ""),
                    "score": r.get("rerank_score", r.get("score", 0.0)),
                }
                for r in merged
            ]
            # O4: async cache write, don't block
            asyncio.create_task(rag_cache_service.set(kb_id, search_question, cache_data))

        # 7. Convert to SearchResult
        results = [
            SearchResult(
                chunk_id=r.get("chunk_id", 0),
                document_id=r.get("document_id", 0),
                content=r.get("content", ""),
                score=r.get("rerank_score", r.get("score", 0.0)),
            )
            for r in merged
        ]
        return results, rewritten_query

    async def _vector_search(self, kb_id: int, question: str, top_k: int) -> list[dict]:
        """向量检索 wrapper"""
        from app.config import settings
        try:
            query_embedding = await embedding_service.embed(question)
            return await vector_store_service.search(
                kb_id, query_embedding, top_k,
                score_threshold=settings.SEARCH_SCORE_THRESHOLD,
            )
        except Exception as e:
            logger.warning("Vector search failed: %s", str(e))
            return []

    async def _fill_document_ids(self, chunks: list[dict]) -> list[dict]:
        """从 sys_chunk 表回填 document_id"""
        chunk_ids = [c.get("chunk_id") for c in chunks if c.get("chunk_id")]
        if not chunk_ids:
            return chunks

        from sqlalchemy import select
        from app.models.document import DocumentChunk
        result = await self.db.execute(
            select(DocumentChunk.id, DocumentChunk.document_id).where(
                DocumentChunk.id.in_(chunk_ids)
            )
        )
        doc_map = {row[0]: row[1] for row in result.all()}
        for c in chunks:
            if c.get("chunk_id") and not c.get("document_id"):
                c["document_id"] = doc_map.get(c["chunk_id"], 0)
        return chunks

    @staticmethod
    def _rrf_fusion(
        bm25_results: list[dict],
        vector_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion:
        score(chunk) = Σ 1/(k + rank_in_list)
        """
        scores: dict[int, float] = defaultdict(float)
        content_map: dict[int, str] = {}
        doc_id_map: dict[int, int] = {}

        for rank, item in enumerate(bm25_results):
            cid = item.get("chunk_id", 0)
            if cid:
                scores[cid] += 1.0 / (k + rank + 1)
                content_map[cid] = item.get("content", "")
                doc_id_map[cid] = item.get("document_id", 0)

        for rank, item in enumerate(vector_results):
            cid = item.get("chunk_id", 0)
            if cid:
                scores[cid] += 1.0 / (k + rank + 1)
                content_map.setdefault(cid, item.get("content", ""))
                doc_id_map.setdefault(cid, item.get("document_id", 0))

        merged = [
            {
                "chunk_id": cid,
                "document_id": doc_id_map.get(cid, 0),
                "content": content_map.get(cid, ""),
                "score": round(score, 4),
            }
            for cid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True)
        ]
        return merged
