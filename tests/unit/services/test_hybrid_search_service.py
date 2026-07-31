"""
Unit tests for app.services.hybrid_search_service
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.qa import SearchResult
from app.services.hybrid_search_service import HybridSearchService


@pytest.fixture
def service():
    with patch.object(HybridSearchService, "__init__", lambda self, db: None):
        svc = HybridSearchService(None)
        svc.db = None
        yield svc


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    return user


class TestHybridSearch:
    """HybridSearchService.search"""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_results(self, service, mock_user):
        cached = [{"chunk_id": 1, "document_id": 10, "content": "cached", "score": 0.95}]
        with patch("app.services.hybrid_search_service.KBService") as MockKB:
            MockKB.return_value.get_accessible = AsyncMock()
            with patch("app.services.hybrid_search_service.rag_cache_service.get", new=AsyncMock(return_value=cached)):
                results, rewritten = await service.search(1, "q", mock_user)

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].content == "cached"

    @pytest.mark.asyncio
    async def test_cache_miss_runs_full_pipeline(self, service, mock_user):
        with patch("app.services.hybrid_search_service.KBService") as MockKB:
            MockKB.return_value.get_accessible = AsyncMock()
            with patch("app.services.hybrid_search_service.rag_cache_service.get", new=AsyncMock(return_value=None)):
                with patch("app.services.hybrid_search_service.rag_cache_service.set", new=AsyncMock()):
                    with patch("app.services.hybrid_search_service.settings") as mock_settings:
                        mock_settings.HYBRID_BM25_TOP_K = 5
                        mock_settings.HYBRID_VECTOR_TOP_K = 5
                        mock_settings.HYBRID_RRF_K = 60
                        mock_settings.RERANK_ENABLED = True

                        with patch("app.services.hybrid_search_service.bm25_service.search", new=AsyncMock(return_value=[
                            {"chunk_id": 1, "content": "bm25", "score": 0.8},
                        ])):
                            with patch.object(service, "_vector_search", new=AsyncMock(return_value=[
                                {"chunk_id": 2, "content": "vector", "score": 0.9},
                            ])):
                                with patch.object(service, "_fill_document_ids", new=AsyncMock(return_value=[
                                    {"chunk_id": 1, "document_id": 10, "content": "bm25", "score": 0.8},
                                    {"chunk_id": 2, "document_id": 20, "content": "vector", "score": 0.9},
                                ])):
                                    with patch("app.services.hybrid_search_service.rerank_service.rerank", new=AsyncMock(return_value=[
                                        {"chunk_id": 2, "document_id": 20, "content": "vector", "rerank_score": 0.95},
                                        {"chunk_id": 1, "document_id": 10, "content": "bm25", "rerank_score": 0.85},
                                    ])):
                                        results, rewritten = await service.search(1, "q", mock_user, top_k=2)

        assert len(results) == 2
        assert results[0].chunk_id == 2
        assert results[0].score == 0.95

    @pytest.mark.asyncio
    async def test_query_rewrite_with_history(self, service, mock_user):
        with patch("app.services.hybrid_search_service.KBService") as MockKB:
            MockKB.return_value.get_accessible = AsyncMock()
            with patch("app.services.hybrid_search_service.query_rewrite_service.rewrite", new=AsyncMock(return_value="重写后的问题")) as mock_rewrite:
                with patch("app.services.hybrid_search_service.rag_cache_service.get", new=AsyncMock(return_value=[{"chunk_id": 1, "document_id": 10, "content": "c", "score": 0.9}])):
                    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
                    results, rewritten = await service.search(1, "那个呢", mock_user, history=history)

        mock_rewrite.assert_awaited_once_with("那个呢", history)
        assert rewritten == "重写后的问题"


class TestVectorSearch:
    """HybridSearchService._vector_search"""

    @pytest.mark.asyncio
    async def test_vector_search_returns_results(self, service):
        with patch("app.services.hybrid_search_service.embedding_service.embed", new=AsyncMock(return_value=[0.0] * 768)):
            with patch("app.services.hybrid_search_service.vector_store_service.search", new=AsyncMock(return_value=[
                {"chunk_id": 1, "content": "v", "score": 0.9},
            ])):
                results = await service._vector_search(1, "q", 5)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_vector_search_failure_returns_empty(self, service):
        with patch("app.services.hybrid_search_service.embedding_service.embed", new=AsyncMock(side_effect=RuntimeError("embed failed"))):
            results = await service._vector_search(1, "q", 5)
        assert results == []


class TestFillDocumentIds:
    """HybridSearchService._fill_document_ids"""

    @pytest.mark.asyncio
    async def test_fill_document_ids_from_db(self, service):
        chunks = [
            {"chunk_id": 1, "document_id": 0, "content": "a"},
            {"chunk_id": 2, "document_id": 0, "content": "b"},
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = [(1, 10), (2, 20)]
        service.db = MagicMock()
        service.db.execute = AsyncMock(return_value=mock_result)

        filled = await service._fill_document_ids(chunks)

        assert filled[0]["document_id"] == 10
        assert filled[1]["document_id"] == 20


class TestRRFFusion:
    """HybridSearchService._rrf_fusion"""

    def test_rrf_fusion_combines_rankings(self):
        bm25 = [
            {"chunk_id": 1, "content": "a", "document_id": 10},
            {"chunk_id": 2, "content": "b", "document_id": 20},
        ]
        vector = [
            {"chunk_id": 2, "content": "b", "document_id": 20},
            {"chunk_id": 3, "content": "c", "document_id": 30},
        ]
        merged = HybridSearchService._rrf_fusion(bm25, vector, k=60)

        assert len(merged) == 3
        # chunk 2 出现在两个列表中，得分最高
        assert merged[0]["chunk_id"] == 2
        assert all("score" in m for m in merged)
