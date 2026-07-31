"""
Unit tests for app.services.vector_store
"""
from unittest.mock import MagicMock

import pytest

from app.services.vector_store import VectorStoreService


@pytest.fixture
def service():
    svc = VectorStoreService()
    # 直接注入 mock client，绕过 property 创建逻辑
    svc._client = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_search_filters_by_score_threshold(service):
    """低于 score_threshold 的结果应被过滤掉。"""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["1", "2", "3"]],
        "documents": [["doc1", "doc2", "doc3"]],
        "metadatas": [[{"document_id": 10}, {"document_id": 20}, {"document_id": 30}]],
        "distances": [[0.2, 0.5, 0.7]],  # scores: 0.8, 0.5, 0.3
    }
    service._client.get_collection.return_value = mock_collection

    results = await service.search(
        kb_id=1,
        query_embedding=[0.0] * 768,
        top_k=3,
        score_threshold=0.55,
    )

    assert len(results) == 1
    assert results[0]["chunk_id"] == 1
    assert results[0]["score"] == 0.8


@pytest.mark.asyncio
async def test_search_returns_all_when_no_threshold(service):
    """未提供 threshold 时返回全部结果。"""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["1", "2"]],
        "documents": [["doc1", "doc2"]],
        "metadatas": [[{"document_id": 10}, {"document_id": 20}]],
        "distances": [[0.2, 0.6]],  # scores: 0.8, 0.4
    }
    service._client.get_collection.return_value = mock_collection

    results = await service.search(
        kb_id=1,
        query_embedding=[0.0] * 768,
        top_k=2,
    )

    assert len(results) == 2
