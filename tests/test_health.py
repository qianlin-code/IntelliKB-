"""
健康检查端点测试
"""
import pytest
import httpx


class TestHealth:
    """L1: 健康检查"""

    async def test_liveness_returns_200(self, client: httpx.AsyncClient):
        """GET /api/v1/health → 200"""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    async def test_readiness_returns_json(self, client: httpx.AsyncClient):
        """GET /api/v1/ready → 返回 db/redis 检查状态"""
        resp = await client.get("/api/v1/ready")
        # readiness 在 DB 可用时返回 200，否则返回 503
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert "status" in body
        assert "details" in body
        assert "db" in body["details"]

    async def test_root_returns_app_info(self, client: httpx.AsyncClient):
        """GET / → 应用信息"""
        resp = await client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["app"] == "IntelliKB"
        assert "docs" in body
