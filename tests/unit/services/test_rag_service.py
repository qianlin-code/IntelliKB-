"""
Unit tests for app.services.rag_service
"""
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.schemas.qa import SearchResult
from app.services.rag_service import RAGService


@pytest.fixture
def service():
    with patch.object(RAGService, "__init__", lambda self, db: None):
        svc = RAGService(None)
        svc.db = None
        svc.llm_client = MagicMock()
        svc.llm_model = "test-model"
        yield svc


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    return user


class TestSearch:
    """RAGService.search"""

    @pytest.mark.asyncio
    async def test_search_returns_search_results(self, service, mock_user):
        with patch("app.services.rag_service.KBService") as MockKB:
            MockKB.return_value.get_accessible = AsyncMock()
            with patch("app.services.rag_service.embedding_service.embed", new=AsyncMock(return_value=[0.0] * 768)):
                with patch("app.services.rag_service.vector_store_service.search", new=AsyncMock(return_value=[
                    {"chunk_id": 1, "document_id": 10, "content": "hello", "score": 0.9},
                ])):
                    results = await service.search(1, "q", mock_user, top_k=5)

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].chunk_id == 1
        assert results[0].document_id == 10


class TestAsk:
    """RAGService.ask"""

    @pytest.mark.asyncio
    async def test_ask_returns_answer_with_sources(self, service, mock_user):
        sources = [SearchResult(chunk_id=1, document_id=10, content="hello", score=0.9)]
        service.search = AsyncMock(return_value=sources)

        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="答案 [source:1]"))]
        service.llm_client.chat.completions.create = AsyncMock(return_value=response)

        result = await service.ask(1, "q", mock_user)

        assert result.answer == "答案 [source:1]"
        assert result.sources == sources
        assert result.llm_error is False

    @pytest.mark.asyncio
    async def test_ask_returns_empty_message_when_no_sources(self, service, mock_user):
        service.search = AsyncMock(return_value=[])
        result = await service.ask(1, "q", mock_user)
        assert "未找到相关文档片段" in result.answer
        assert result.sources == []

    @pytest.mark.asyncio
    async def test_ask_handles_timeout(self, service, mock_user):
        sources = [SearchResult(chunk_id=1, document_id=10, content="hello", score=0.9)]
        service.search = AsyncMock(return_value=sources)
        service.llm_client.chat.completions.create = AsyncMock(side_effect=openai.APITimeoutError("timeout"))

        result = await service.ask(1, "q", mock_user)

        assert result.llm_error is True
        assert "超时" in result.answer
        assert result.sources == sources

    @pytest.mark.asyncio
    async def test_ask_handles_generic_exception(self, service, mock_user):
        sources = [SearchResult(chunk_id=1, document_id=10, content="hello", score=0.9)]
        service.search = AsyncMock(return_value=sources)
        service.llm_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

        result = await service.ask(1, "q", mock_user)

        assert result.llm_error is True
        assert "不可用" in result.answer


class TestAskStream:
    """RAGService.ask_stream"""

    @pytest.mark.asyncio
    async def test_ask_stream_yields_sources_done_when_empty(self, service, mock_user):
        service.search = AsyncMock(return_value=[])
        frames = [f async for f in service.ask_stream(1, "q", mock_user)]

        assert any("event: sources" in f for f in frames)
        assert any("event: done" in f for f in frames)

    @pytest.mark.asyncio
    async def test_ask_stream_yields_tokens(self, service, mock_user):
        sources = [SearchResult(chunk_id=1, document_id=10, content="hello", score=0.9)]
        service.search = AsyncMock(return_value=sources)

        chunk = MagicMock(choices=[MagicMock(delta=MagicMock(content="答"))])
        stream = async_iter([chunk])
        service.llm_client.chat.completions.create = AsyncMock(return_value=stream)

        frames = [f async for f in service.ask_stream(1, "q", mock_user)]

        assert any("event: sources" in f for f in frames)
        assert any('"答"' in f for f in frames)
        assert any("event: done" in f for f in frames)


async def async_iter(items):
    for item in items:
        yield item
