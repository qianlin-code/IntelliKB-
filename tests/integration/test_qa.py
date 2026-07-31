"""
Integration tests: QA search + ask 端点

Phase 7 P1.1: 使用 test_kb_with_doc fixture 自动创建测试 KB，
不再硬编码 kb_id=20。
"""
import pytest
import httpx
from httpx import AsyncClient


class TestIntegrationQA:
    """QA 核心流程"""

    async def test_qa_search_returns_results(
        self, client: AsyncClient, auth_header: dict,
        test_kb_with_doc: int,
    ):
        """POST /api/v1/qa/search → 200, 返回 results 列表"""
        kb_id = test_kb_with_doc
        resp = await client.post("/api/v1/qa/search", json={
            "kb_id": kb_id,
            "question": "IntelliKB 是什么？",
            "top_k": 3,
        }, headers=auth_header)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        assert "results" in data
        assert isinstance(data["results"], list)

    async def test_qa_ask_returns_answer(
        self, client: AsyncClient, auth_header: dict,
        test_kb_with_doc: int,
    ):
        """POST /api/v1/qa/ask → 200, answer 非空"""
        kb_id = test_kb_with_doc
        resp = await client.post("/api/v1/qa/ask", json={
            "kb_id": kb_id,
            "question": "你好",
            "top_k": 3,
        }, headers=auth_header)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        data = body["data"]
        assert "answer" in data
        assert isinstance(data["answer"], str)
        assert len(data["answer"]) > 0, "Answer should not be empty"

    async def test_qa_ask_stream_sse(
        self, client: AsyncClient, auth_header: dict,
        test_kb_with_doc: int,
    ):
        """POST /api/v1/qa/ask-stream → SSE 正常结束，包含 sources/done"""
        kb_id = test_kb_with_doc
        async with client.stream(
            "POST",
            "/api/v1/qa/ask-stream",
            json={"kb_id": kb_id, "question": "你好", "top_k": 3},
            headers=auth_header,
        ) as response:
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"
            body = ""
            async for chunk in response.aiter_text():
                body += chunk
            assert "event: done" in body, f"SSE should end with done event, got: {body[:500]}"

    async def test_qa_search_requires_auth(self, client: AsyncClient):
        """搜索端点需要认证"""
        resp = await client.post("/api/v1/qa/search", json={
            "kb_id": 1,
            "question": "test",
            "top_k": 3,
        })
        assert resp.status_code in (401, 403)
