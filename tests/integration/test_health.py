"""
Integration tests: P0.2 Health + Ready endpoints
"""
import pytest
import httpx


class TestIntegrationHealth:
    """Health + Ready 端点"""

    async def test_health_returns_ok(self, client: httpx.AsyncClient):
        """GET /api/v1/health → 200, status=ok, 含 version"""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert len(body["version"]) > 0

    async def test_ready_returns_status(self, client: httpx.AsyncClient):
        """GET /api/v1/ready → 200 或 503，含 details"""
        resp = await client.get("/api/v1/ready")
        assert resp.status_code in (200, 503), f"Unexpected status: {resp.status_code}"
        body = resp.json()
        assert "details" in body
        assert "db" in body["details"]
        assert "redis" in body["details"]
        # status 字段
        assert body["status"] in ("ready", "not_ready")

    async def test_health_no_auth_required(self, client: httpx.AsyncClient):
        """健康检查端点不应要求认证"""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200  # not 401/403

    async def test_ready_no_auth_required(self, client: httpx.AsyncClient):
        """就绪探针端点不应要求认证"""
        resp = await client.get("/api/v1/ready")
        assert resp.status_code in (200, 503)  # not 401/403

    async def test_old_health_path_404(self, client: httpx.AsyncClient):
        """Phase 7: 旧 /health/liveness 路径应返回 404"""
        resp = await client.get("/health/liveness")
        assert resp.status_code == 404
