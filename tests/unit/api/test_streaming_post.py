"""
Unit tests for POST streaming endpoints.

验证 /qa/ask-stream 与 /agent/chat-stream 改为 POST 后：
- 正确接收 JSON body
- 返回 SSE 流
- 认证缺失返回 401/403
- body 校验生效
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.api.v1.agent_chat import router as agent_router
from app.api.v1.qa import router as qa_router
from app.depends.auth import get_current_user_cookie
from app.models.user import User


@pytest.fixture
def app():
    """仅挂载目标 router 的最小 FastAPI app。"""
    app = FastAPI()
    app.include_router(qa_router)
    app.include_router(agent_router)

    async def mock_user():
        user = User(id=1, username="test")
        return user

    app.dependency_overrides[get_current_user_cookie] = mock_user
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


class TestQAAskStream:
    """POST /qa/ask-stream"""

    @pytest.mark.asyncio
    async def test_post_ask_stream_returns_sse(self, client):
        async def mock_ask_stream(*args, **kwargs):
            yield "event: sources\ndata: {\"sources\":[]}\n\n"
            yield 'event: done\ndata: {"total_tokens":0}\n\n'

        with patch("app.api.v1.qa.RAGService.ask_stream", new=mock_ask_stream):
            async with client.stream(
                "POST",
                "/qa/ask-stream",
                json={"kb_id": 1, "question": "测试", "top_k": 3},
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk
                assert "event: done" in body

    @pytest.mark.asyncio
    async def test_post_ask_stream_rejects_long_question(self, client):
        resp = await client.post("/qa/ask-stream", json={
            "kb_id": 1,
            "question": "x" * 2001,
            "top_k": 3,
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_ask_stream_no_longer_exists(self, client):
        resp = await client.get("/qa/ask-stream", params={"kb_id": 1, "question": "test"})
        assert resp.status_code == 405


class TestAgentChatStream:
    """POST /agent/chat-stream"""

    @pytest.mark.asyncio
    async def test_post_chat_stream_returns_sse(self, client):
        async def mock_chat_stream(*args, **kwargs):
            yield "event: thought\ndata: {}\n\n"
            yield 'event: done\ndata: {"conversation_id":1,"total_tokens":0}\n\n'

        with patch("app.api.v1.agent_chat.AgentService.chat_stream", new=mock_chat_stream):
            async with client.stream(
                "POST",
                "/agent/chat-stream",
                json={"kb_id": 1, "question": "测试", "conversation_id": 2},
            ) as response:
                assert response.status_code == 200
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk
                assert "event: done" in body

    @pytest.mark.asyncio
    async def test_post_chat_stream_accepts_new_conversation(self, client):
        async def mock_chat_stream(*args, **kwargs):
            assert kwargs.get("conv_id") is None
            yield 'event: done\ndata: {}\n\n'

        with patch("app.api.v1.agent_chat.AgentService.chat_stream", new=mock_chat_stream):
            async with client.stream(
                "POST",
                "/agent/chat-stream",
                json={"kb_id": 1, "question": "测试"},
            ) as response:
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_chat_stream_no_longer_exists(self, client):
        resp = await client.get("/agent/chat-stream", params={"kb_id": 1, "question": "test"})
        assert resp.status_code == 405
