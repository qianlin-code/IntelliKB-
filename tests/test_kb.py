"""
知识库 CRUD 测试（M6）

前置条件:
    - tests/conftest.py: client + auth_header + mock_embedding_and_vector
    - MySQL 可访问
"""
import pytest
import httpx


class TestKnowledgeBase:
    """KB CRUD 集成测试（mock embedding + vector）"""

    # ── 创建 ──

    async def test_create_kb_201(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """POST /knowledge-bases → 201"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "测试知识库",
            "description": "Phase 1 验收",
            "is_public": True,
        }, headers=auth_header)
        assert resp.status_code == 201
        body = resp.json()
        assert body["code"] == 201
        assert body["data"]["name"] == "测试知识库"
        assert body["data"]["is_public"] is True
        assert body["data"]["id"] > 0

    async def test_create_kb_empty_name_422(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """POST /knowledge-bases 空名称 → 422"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "",
        }, headers=auth_header)
        assert resp.status_code == 422

    # ── 列表 ──

    async def test_list_kb_200(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """GET /knowledge-bases → 200"""
        resp = await client.get("/api/v1/knowledge-bases", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert "items" in body["data"]
        assert "total" in body["data"]

    # ── 详情 ──

    async def test_get_kb_200(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """GET /knowledge-bases/{id} → 200"""
        # 先创建
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "详情测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        resp = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "详情测试"

    async def test_get_kb_not_found_404(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """GET /knowledge-bases/99999 → 404"""
        resp = await client.get("/api/v1/knowledge-bases/99999", headers=auth_header)
        assert resp.status_code == 404

    # ── 更新 ──

    async def test_update_kb_200(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """PUT /knowledge-bases/{id} → 200"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "更新测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        resp = await client.put(f"/api/v1/knowledge-bases/{kb_id}", json={
            "name": "已更新",
        }, headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "已更新"

    # ── 删除 ──

    async def test_delete_kb_200(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """DELETE /knowledge-bases/{id} → 200"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "删除测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        resp = await client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_header)
        assert resp.status_code == 200

        # 确认已删除（404）
        resp = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_header)
        assert resp.status_code == 404

    # ── 权限 ──

    async def test_public_kb_accessible(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """公开 KB → 其他用户可读"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "公开 KB", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        # 同一用户可读（owner）
        resp = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_header)
        assert resp.status_code == 200

    # ── 统计 ──

    async def test_kb_stats_200(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """GET /knowledge-bases/{id}/stats → 200"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "统计测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        resp = await client.get(f"/api/v1/knowledge-bases/{kb_id}/stats", headers=auth_header)
        assert resp.status_code == 200
        stats = resp.json()["data"]
        assert stats["kb_id"] == kb_id
        assert stats["document_count"] == 0
        assert stats["chunk_count"] == 0
