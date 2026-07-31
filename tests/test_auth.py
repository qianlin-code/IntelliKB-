"""
认证端点测试 — 注册 / 登录 / 获取当前用户

前置条件:
    - tests/conftest.py 提供的 AsyncClient fixture
    - MySQL 可访问
    - Redis 非必需（限流逻辑在 Redis 不可用时静默跳过）

注意:
    - 每个测试使用 uuid4 生成唯一用户名，避免多次运行间的数据冲突。
    - Windows 上 httpx.ASGITransport + lifespan 后台任务清理时可能触发
      "Task got Future attached to a different loop" 错误。这是 CPython
      WindowsSelectorEventLoop 的已知限制，不影响测试逻辑本身。
      Phase 1 切换到 testcontainers 后自然解决。
"""
import uuid

import pytest
import httpx


def _unique(name: str) -> str:
    """生成唯一用户名"""
    return f"m2_{name}_{uuid.uuid4().hex[:8]}"


class TestAuth:
    """
    认证流程集成测试。

    每个测试方法独立运行，使用唯一用户名避免冲突。
    """

    # ── L2: 注册 ──

    async def test_register_creates_user_201(self, client: httpx.AsyncClient):
        """POST /api/v1/auth/register → 201"""
        resp = await client.post("/api/v1/auth/register", json={
            "username": _unique("reg"),
            "password": "test1234",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["code"] == 201
        assert body["message"] == "注册成功"

    async def test_register_duplicate_username_409(self, client: httpx.AsyncClient):
        """重复用户名注册 → 409"""
        username = _unique("dup")
        # 第一次：201
        await client.post("/api/v1/auth/register", json={
            "username": username,
            "password": "test1234",
        })
        # 第二次：409
        resp = await client.post("/api/v1/auth/register", json={
            "username": username,
            "password": "test1234",
        })
        assert resp.status_code == 409
        body = resp.json()
        assert body["code"] == 409

    # ── L3: 登录 ──

    async def test_login_returns_tokens_200(self, client: httpx.AsyncClient):
        """POST /api/v1/auth/login → 200 且返回 access_token + refresh_token"""
        username = _unique("login")
        # 先注册
        await client.post("/api/v1/auth/register", json={
            "username": username,
            "password": "test1234",
        })
        # 登录
        resp = await client.post("/api/v1/auth/login", json={
            "username": username,
            "password": "test1234",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert isinstance(data["expires_in"], int)
        assert data["expires_in"] > 0

    async def test_login_wrong_password_401(self, client: httpx.AsyncClient):
        """错误密码登录 → 401"""
        username = _unique("wrongpwd")
        await client.post("/api/v1/auth/register", json={
            "username": username,
            "password": "test1234",
        })
        resp = await client.post("/api/v1/auth/login", json={
            "username": username,
            "password": "wrongpassword!!",
        })
        assert resp.status_code == 401

    # ── L4: /me Bearer Token ──

    async def test_me_with_bearer_token_200(self, client: httpx.AsyncClient):
        """GET /api/v1/auth/me (Bearer Token) → 200"""
        username = _unique("me")
        # 注册 + 登录
        await client.post("/api/v1/auth/register", json={
            "username": username,
            "password": "test1234",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "username": username,
            "password": "test1234",
        })
        token = login_resp.json()["data"]["access_token"]

        # /me
        resp = await client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["username"] == username

    async def test_me_without_token_401(self, client: httpx.AsyncClient):
        """GET /api/v1/auth/me (无 Token) → 401"""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401


class TestSSEAuthPriority:
    """
    SSE 端点认证优先级测试。

    get_current_user_cookie 用于 /qa/ask-stream 和 /agent/chat-stream，
    必须保证显式传入的 access_token query param 优先于浏览器中可能存在的
    陈旧 Cookie，避免前端 SSE 请求被错误地判定为 401。
    """

    async def test_query_param_takes_precedence_over_cookie(self, monkeypatch):
        """有效 query param + 无效 cookie → 使用 query param 认证成功"""
        from unittest.mock import AsyncMock, MagicMock
        from app.depends import auth

        valid_token = "valid_query_param_token"
        invalid_cookie_token = "invalid_cookie_token"

        # 构造 Request mock：同时带有 query param 和 cookie
        request = MagicMock()
        request.query_params = {"access_token": valid_token}
        request.cookies = {"access_token": invalid_cookie_token}
        request.headers = {}

        # mock 用户对象
        mock_user = MagicMock()
        mock_user.is_active = True

        # patch JWT 验证，记录实际传入的 token
        verified_tokens = []
        async def fake_verify(token, db):
            verified_tokens.append(token)
            return mock_user

        monkeypatch.setattr(auth, "_verify_jwt_and_get_user", fake_verify)
        monkeypatch.setattr(auth, "_verify_api_key_and_get_user", AsyncMock())

        db = MagicMock()
        user = await auth.get_current_user_cookie(request, db)

        assert user is mock_user
        assert verified_tokens == [valid_token]

    async def test_cookie_used_when_no_query_param(self, monkeypatch):
        """无 query param 时回退到 cookie 认证"""
        from unittest.mock import AsyncMock, MagicMock
        from app.depends import auth

        cookie_token = "cookie_token"

        request = MagicMock()
        request.query_params = {}
        request.cookies = {"access_token": cookie_token}
        request.headers = {}

        mock_user = MagicMock()
        mock_user.is_active = True

        verified_tokens = []
        async def fake_verify(token, db):
            verified_tokens.append(token)
            return mock_user

        monkeypatch.setattr(auth, "_verify_jwt_and_get_user", fake_verify)
        monkeypatch.setattr(auth, "_verify_api_key_and_get_user", AsyncMock())

        db = MagicMock()
        user = await auth.get_current_user_cookie(request, db)

        assert user is mock_user
        assert verified_tokens == [cookie_token]

    async def test_bearer_used_when_no_token_cookie(self, monkeypatch):
        """无 query param / cookie 时回退到 Authorization Bearer"""
        from unittest.mock import AsyncMock, MagicMock
        from app.depends import auth

        bearer_token = "bearer_token"

        request = MagicMock()
        request.query_params = {}
        request.cookies = {}
        request.headers = {"Authorization": f"Bearer {bearer_token}"}

        mock_user = MagicMock()
        mock_user.is_active = True

        verified_tokens = []
        async def fake_verify(token, db):
            verified_tokens.append(token)
            return mock_user

        monkeypatch.setattr(auth, "_verify_jwt_and_get_user", fake_verify)
        monkeypatch.setattr(auth, "_verify_api_key_and_get_user", AsyncMock())

        db = MagicMock()
        user = await auth.get_current_user_cookie(request, db)

        assert user is mock_user
        assert verified_tokens == [bearer_token]
