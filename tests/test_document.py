"""
文档上传/列表/删除 测试（M6）

前置条件:
    - tests/conftest.py: client + auth_header + mock_embedding_and_vector
    - MySQL 可访问
"""
import pytest
import httpx


def _create_kb(client: httpx.AsyncClient, auth_header: dict[str, str], name: str = "文档测试KB") -> int:
    """辅助: 创建知识库并返回 kb_id"""

    async def _inner():
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": name, "is_public": True,
        }, headers=auth_header)
        return resp.json()["data"]["id"]
    return _inner


class TestDocument:
    """Document 上传/列表/删除 测试（mock embedding + vector）"""

    # ── 上传 ──

    async def test_upload_md_document_201(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """上传 .md 文档 → 201"""
        # 先创建 KB
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "MD上传测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        content = b"# Test\n\nThis is a test document.\n\n## Section\n\nHello World."
        resp = await client.post("/api/v1/documents/upload", files={
            "file": ("test.md", content, "text/markdown"),
        }, data={"kb_id": str(kb_id)}, headers=auth_header)
        assert resp.status_code == 201
        body = resp.json()
        assert body["code"] == 201
        assert body["data"]["filename"] == "test.md"
        assert body["data"]["file_type"] == "md"
        # 文档上传后异步处理（parsing → chunking → indexing → done），
        # 响应可能在任何阶段返回。接受所有非失败状态。
        assert body["data"]["status"] in ("uploading", "parsing", "chunking", "indexing", "done"), (
            f"Expected non-failed status, got: {body['data']['status']}"
        )

    async def test_upload_txt_document_201(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """上传 .txt 文档 → 201"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "TXT上传测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        content = b"Plain text document.\nLine 2.\nLine 3.\n"
        resp = await client.post("/api/v1/documents/upload", files={
            "file": ("notes.txt", content, "text/plain"),
        }, data={"kb_id": str(kb_id)}, headers=auth_header)
        assert resp.status_code == 201
        assert resp.json()["data"]["file_type"] == "txt"

    async def test_upload_invalid_extension_400(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """上传 .exe → 400"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "验证测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        resp = await client.post("/api/v1/documents/upload", files={
            "file": ("malware.exe", b"fake", "application/octet-stream"),
        }, data={"kb_id": str(kb_id)}, headers=auth_header)
        assert resp.status_code == 400

    async def test_upload_without_auth_401(
        self, client: httpx.AsyncClient,
        mock_embedding_and_vector,
    ):
        """无认证上传 → 401"""
        resp = await client.post("/api/v1/documents/upload", files={
            "file": ("test.md", b"test", "text/markdown"),
        }, data={"kb_id": "1"})
        assert resp.status_code == 401

    # ── 列表 ──

    async def test_list_documents_200(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """GET /documents?kb_id= → 200"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "列表测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        # 上传一个文档
        await client.post("/api/v1/documents/upload", files={
            "file": ("test.md", b"# Test\nContent.", "text/markdown"),
        }, data={"kb_id": str(kb_id)}, headers=auth_header)

        resp = await client.get("/api/v1/documents", params={"kb_id": kb_id}, headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] >= 1

    # ── 删除 ──

    async def test_delete_document_200(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """DELETE /documents/{id} → 200"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "删除测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        resp = await client.post("/api/v1/documents/upload", files={
            "file": ("del.md", b"# Delete me", "text/markdown"),
        }, data={"kb_id": str(kb_id)}, headers=auth_header)
        doc_id = resp.json()["data"]["doc_id"]

        resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=auth_header)
        assert resp.status_code == 200

    # ── 分块 ──

    async def test_get_chunks_200(
        self, client: httpx.AsyncClient, auth_header: dict[str, str],
        mock_embedding_and_vector,
    ):
        """GET /documents/{id}/chunks → 200"""
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "分块测试", "is_public": True,
        }, headers=auth_header)
        kb_id = resp.json()["data"]["id"]

        resp = await client.post("/api/v1/documents/upload", files={
            "file": ("chunked.md", b"# Test\n\n" + b"Content.\n" * 50, "text/markdown"),
        }, data={"kb_id": str(kb_id)}, headers=auth_header)
        doc_id = resp.json()["data"]["doc_id"]

        resp = await client.get(f"/api/v1/documents/{doc_id}/chunks", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert "chunks" in body["data"]
        assert body["data"]["total"] > 0
