"""
Integration tests: Agent chat 端点（需要 Ollama 运行）

Phase 7 P1.1: 使用 test_kb_with_doc fixture 自动创建测试 KB，
不再硬编码 kb_id=20。
"""
import pytest
import httpx
from httpx import AsyncClient


class TestIntegrationAgentChat:
    """Agent chat 核心流程"""

    async def test_agent_chat_returns_response(
        self, client: AsyncClient, auth_header: dict,
        test_kb_with_doc: int,
    ):
        """POST /api/v1/agent/chat → 200, conversation_id > 0, answer 非空"""
        kb_id = test_kb_with_doc
        resp = await client.post("/api/v1/agent/chat", json={
            "kb_id": kb_id,
            "question": "你好，1+1等于几？",
        }, headers=auth_header)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        assert "conversation_id" in data
        assert data["conversation_id"] > 0, "conversation_id should be positive"
        assert "answer" in data
        assert isinstance(data["answer"], str)

    async def test_agent_chat_stream_sse(
        self, client: AsyncClient, auth_header: dict,
        test_kb_with_doc: int,
    ):
        """POST /api/v1/agent/chat-stream → SSE 正常结束，done 帧出现"""
        kb_id = test_kb_with_doc
        async with client.stream(
            "POST",
            "/api/v1/agent/chat-stream",
            json={"kb_id": kb_id, "question": "你好"},
            headers=auth_header,
        ) as response:
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

            body = ""
            async for chunk in response.aiter_text():
                body += chunk

            # 流中应有 done 事件
            assert "event: done" in body, f"SSE should end with done event, got: {body[:500]}"

    async def test_agent_chat_requires_auth(self, client: AsyncClient):
        """Agent 对话端点需要认证"""
        resp = await client.post("/api/v1/agent/chat", json={
            "kb_id": 1,
            "question": "test",
        })
        assert resp.status_code in (401, 403)
