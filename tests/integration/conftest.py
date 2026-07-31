"""
Integration test fixtures — use REAL HTTP client against running backend.

与 tests/conftest.py 不同，此模块使用 httpx.AsyncClient 直接连接
运行中的后端（默认 http://127.0.0.1:8000），避免 Windows ASGITransport
的 "Task got Future attached to a different loop" 问题。

前置条件:
    - 后端在 8000 端口运行
    - MySQL + Redis 可访问
    - Ollama 运行（Agent 测试需要）

运行方式:
    pytest tests/integration/ -v
    pytest tests/integration/ -v -m integration

方案 A（配额锁竞争修复）:
    kb_creation_lock 是 MySQL GET_LOCK 实现的用户级互斥锁。
    每个测试模块创建独立的测试用户（而非回退到 admin），确保不同模块
    之间不会争抢同一个 MySQL advisory lock，从根源消除锁竞争。

    当注册频率限制触发 429 时，使用指数退避重试（最多 3 次），
    尽量避免回退到 admin。若最终仍需回退，测试仍可运行但可能有锁等待。

Windows teardown 警告修复:
    - client fixture 在 module scope 下管理 httpx.AsyncClient 生命周期，
      避免 function scope 下的频繁创建/销毁。
    - 在 teardown 阶段显式关闭 AsyncClient，捕获 Windows ProactorEventLoop
      下的 "Event loop is closed" 错误并降级为 warning 日志。
    - 通过 pytest.ini 的 filterwarnings 配置过滤已知的 asyncio 清理警告。

已知限制:
    - Windows 上 httpx 客户端关闭时可能触发 "Event loop is closed" 错误，
      发生于 teardown 阶段，不影响测试断言本身。
    - Agent 测试需要 Ollama 运行，否则会超时或失败。
    - 每个测试模块使用独立的用户，避免 kb_creation_lock 用户级锁竞争。
"""
import asyncio as _asyncio
import logging
import os
import uuid
from typing import AsyncGenerator

import pytest_asyncio
import httpx

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")

logger = logging.getLogger("integration_test")


# ── 方案 A：会话级测试用户池，避免 kb_creation_lock 竞争 ──
# 使用模块级变量跟踪已创建的用户，防止同一用户被重复创建/锁定

_test_user_counter: int = 0


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Real HTTP client connecting to running backend（module 级复用）。

    Windows teardown 修复：
        - max_keepalive_connections=0 禁用 HTTP keep-alive，每次请求使用
          新连接，避免 Windows Python 3.13 下跨测试的连接池状态污染导致的
          "Event loop is closed" RuntimeError 在请求中途触发。
        - teardown 阶段的 RuntimeError("Event loop is closed") 被 try/except
          捕获并降级为 debug 日志，避免产生 ERROR 级别的测试输出。
          这是 CPython Windows + anyio + httpcore 的已知边界问题。
    """
    limits = httpx.Limits(max_keepalive_connections=0, max_connections=10)
    ac = httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=httpx.Timeout(180.0),
        limits=limits,
    )
    try:
        yield ac
    finally:
        # 显式清理并捕获 Windows 事件循环关闭异常
        try:
            await ac.aclose()
        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                logger.debug("client fixture cleanup: 事件循环已关闭（Windows 已知问题）")
            else:
                raise


@pytest_asyncio.fixture(scope="module")
async def test_user(client: httpx.AsyncClient) -> dict:
    """为每个测试模块创建独立测试用户，避免 kb_creation_lock 跨模块竞争。

    方案 A 实现：
        kb_creation_lock 是 MySQL GET_LOCK 实现的用户级互斥锁
        （见 app/services/quota_service.py）。
        锁名 = "kb_quota_user_{user_id}"，每个用户有独立的锁。

        通过为每个测试模块创建唯一的用户，确保不同模块之间不会
        争抢同一个 MySQL advisory lock，从根源消除锁竞争。

    重试策略：
        注册频率限制（REGISTER_RATE_LIMIT_MAX=10，窗口 3600s）可能在
        多次连续注册后返回 429。本 fixture 使用指数退避重试（最多 3 次，
        间隔 1s/2s/4s）来应对短暂的频率限制。

        仅在所有重试都失败后才回退到 admin 用户。
        此时测试仍可运行，但若多个模块同时使用 admin，可能触发
        kb_creation_lock 超时（10s）。

    注意：
        此修改仅影响测试环境。生产环境的配额锁逻辑（quota_service.py
        和 knowledge_bases.py）未被修改，QUOTA_ENABLED 仍从配置读取。
    """
    global _test_user_counter
    _test_user_counter += 1
    username = f"itest_{uuid.uuid4().hex[:8]}"
    password = "test1234"

    # ── 方案 A 核心：重试注册，避免回退到 admin ──
    # admin 用户可能被多个测试模块共享，导致 kb_creation_lock 竞争。
    # 优先使用独立用户，每个用户有自己的 MySQL advisory lock。
    resp = None
    for attempt in range(3):
        resp = await client.post("/api/v1/auth/register", json={
            "username": username, "password": password,
        })
        if resp.status_code == 201:
            break  # 注册成功

        if resp.status_code == 429:
            # 频率限制：指数退避重试
            if attempt < 2:
                wait = 2 ** attempt  # 1s, 2s
                logger.info(
                    "测试用户注册频率限制 (429)，%ds 后重试 (attempt %d/3)",
                    wait, attempt + 1,
                )
                await _asyncio.sleep(wait)
                continue
            # 3 次重试全部 429：回退到 admin
            logger.warning(
                "测试用户注册 3 次重试后仍被限频，回退到 admin 用户。"
                "若测试因 kb_creation_lock 超时失败，请等待 %d 秒后重试。",
                3600,
            )
            return {"username": "admin", "password": "admin123"}
        else:
            # 非 429 错误（如用户名已存在 - 可能是上次测试残留）
            break

    # 如果注册未返回 201（非限频错误），尝试直接登录
    if resp is not None and resp.status_code != 201:
        login_resp = await client.post("/api/v1/auth/login", json={
            "username": username, "password": password,
        })
        if login_resp.status_code == 200:
            logger.info("测试用户 %s 已存在，复用现有账号", username)
            return {"username": username, "password": password}
        # 登录也失败，回退到 admin
        logger.warning(
            "测试用户 %s 注册/登录均失败 (status=%d)，回退到 admin",
            username, resp.status_code,
        )
        return {"username": "admin", "password": "admin123"}

    logger.info("测试用户 %s 创建成功 (第 %d 个模块级用户)", username, _test_user_counter)
    return {"username": username, "password": password}


@pytest_asyncio.fixture(scope="function")
async def auth_header(client: httpx.AsyncClient, test_user: dict) -> dict[str, str]:
    """使用测试用户登录，返回 Authorization header。"""
    resp = await client.post("/api/v1/auth/login", json={
        "username": test_user["username"],
        "password": test_user["password"],
    })
    assert resp.status_code == 200, (
        f"Login failed for {test_user['username']}: {resp.status_code} {resp.text}"
    )
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── 方案 A（模块级 KB fixture）：每模块只创建一次 KB ──
# _kb_module (module scope) → test_kb_with_doc (function proxy)
# 消除同一模块内多次 KB 创建导致的 kb_creation_lock 残留锁问题。


@pytest_asyncio.fixture(scope="module")
async def _kb_module(
    client: httpx.AsyncClient, test_user: dict,
):
    """
    模块级内部 fixture：创建测试 KB + 上传文档 + 等待索引。

    每个测试模块只执行一次，同一模块内的所有 test_kb_with_doc
    调用共享同一个 KB。测试模块结束后自动清理。

    方案 A：通过模块级作用域消除同一模块内多次 KB 创建导致的
    kb_creation_lock（MySQL GET_LOCK）残留锁问题。
    """
    # 登录获取 token（内联，避免依赖 function-scoped auth_header）
    resp = await client.post("/api/v1/auth/login", json={
        "username": test_user["username"],
        "password": test_user["password"],
    })
    assert resp.status_code == 200, (
        f"_kb_module login failed: {resp.status_code} {resp.text}"
    )
    token = resp.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    kb_name = f"integration_test_{uuid.uuid4().hex[:8]}"
    kb_id = None

    try:
        # 1. 创建 KB
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": kb_name,
            "description": "Integration test KB — auto-created by fixture (方案 A: 模块级隔离)",
            "is_public": True,
        }, headers=headers)
        assert resp.status_code == 201, (
            f"_kb_module create KB failed: {resp.status_code} {resp.text}"
        )
        kb_id = resp.json()["data"]["id"]

        # 2. 上传测试文档
        doc_content = (
            "IntelliKB 是一个智能知识库平台，支持文档上传和 RAG 问答。\n"
            "它使用 Chroma 作为向量数据库，Ollama 作为本地大模型。\n"
            "知识库可以配置 chunk_size 和 chunk_overlap 参数。\n"
            "系统还支持 Agent 对话功能，可以调用工具搜索知识库。\n"
        )
        resp = await client.post("/api/v1/documents/upload", files={
            "file": ("integration_test_doc.md", doc_content.encode("utf-8"), "text/markdown"),
        }, data={"kb_id": str(kb_id)}, headers=headers)
        assert resp.status_code == 201, (
            f"_kb_module upload doc failed: {resp.status_code} {resp.text}"
        )
        doc_id = resp.json()["data"]["doc_id"]

        # 3. 等待文档索引完成（最多 60 秒）
        for _ in range(30):
            resp = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
            if resp.status_code != 200:
                break
            status = resp.json()["data"].get("status", "")
            if status in ("done", "indexed", "completed"):
                break
            if status in ("failed", "error"):
                break
            await _asyncio.sleep(2)

        logger.info("_kb_module: 创建测试 KB %d", kb_id)
        yield kb_id

    finally:
        # 4. 模块结束后清理
        if kb_id is not None:
            try:
                await client.delete(
                    f"/api/v1/knowledge-bases/{kb_id}",
                    headers=headers,
                    timeout=httpx.Timeout(30.0),
                )
                logger.info("_kb_module: 清理测试 KB %d", kb_id)
            except Exception:
                pass


@pytest_asyncio.fixture(scope="function")
async def test_kb_with_doc(
    _kb_module: int,
):
    """
    函数级 fixture：提供测试 KB（委托给模块级 _kb_module）。

    方案 A 说明：
        本 fixture 是模块级 _kb_module 的函数级代理。
        每个测试模块只创建一次 KB（由 _kb_module 负责），
        同一模块内的所有测试用例通过本 fixture 共享同一个 KB。

        这消除了同一模块内多次 KB 创建导致的 kb_creation_lock
        残留锁问题。不同模块使用独立用户 → 无跨模块竞争。

    返回: kb_id
    """
    return _kb_module
