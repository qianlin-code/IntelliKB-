"""
pytest 配置 + 异步 HTTP 客户端 fixture

Phase 0: 使用 httpx.ASGITransport 在进程中测试 FastAPI app。
        依赖真实 MySQL（无需额外 mock），Redis 不可用时优雅降级。

使用方式:
    pytest tests/ -v

前置条件:
    - MySQL 可访问（通过 .env 或环境变量配置）
    - 已安装: pip install pytest pytest-asyncio httpx

Windows 事件循环修复:
    Python 3.13 的 Windows ProactorEventLoop 与 aiomysql 在 ASGITransport
    测试中存在底层兼容性问题：proactor 在连接 I/O 中途变为 None，
    触发 "AttributeError: 'NoneType' object has no attribute 'send'"。

    修复方案:
    1. 全局设置 WindowsSelectorEventLoopPolicy，避免 Proactor 的 I/O 竞态。
    2. client fixture 使用 session 作用域，确保 lifespan 只启动一次。
    3. engine.dispose() 在 session 结束时释放连接池。

    注意: SelectorEventLoop 在 Windows 上对子进程支持有限，
    但测试中不涉及子进程操作，不受影响。

已知限制:
    此修复仅适用于测试环境。生产环境不受影响。
"""
import asyncio
import logging
import sys
from typing import AsyncGenerator

import pytest_asyncio
import httpx

# ── Windows 事件循环修复 ──
# Python 3.13 的 ProactorEventLoop + aiomysql + ASGITransport 组合存在
# 底层 IOCP 竞态：DB 连接的 _proactor 在 I/O 操作中途变为 None。
# 切换到 SelectorEventLoop 避免此问题。
# 必须在任何 asyncio 操作之前设置，包括 pytest-asyncio 初始化。
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        logging.getLogger("unit_test").info("Windows: 已设置 SelectorEventLoop 策略")
    except Exception:
        pass  # 已被设置过则忽略

from app.main import app

logger = logging.getLogger("unit_test")


async def _lifespan_startup(app) -> None:
    """
    发送 ASGI lifespan.startup 事件，等待 startup.complete 即返回。

    lifespan 在后台持续运行（直到测试套件结束由 asyncio 清理），
    确保 alembic migration + seed_data 在测试期间只执行一次。
    """
    scope = {"type": "lifespan", "asgi": {"version": "3.0"}}

    startup_event = asyncio.Event()

    async def receive():
        if not startup_event.is_set():
            return {"type": "lifespan.startup"}
        # 启动完成后一直阻塞（等待模块 teardown）
        await asyncio.Event().wait()
        return {"type": "lifespan.shutdown"}

    async def send(message):
        if message["type"] == "lifespan.startup.complete":
            startup_event.set()
        elif message["type"] == "lifespan.startup.failed":
            raise RuntimeError(
                f"Lifespan startup failed: {message.get('message', '')}"
            )

    asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(startup_event.wait(), timeout=30.0)


@pytest_asyncio.fixture(scope="session")
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    基于 ASGITransport 的异步 HTTP 客户端。

    scope="session": 所有测试模块共享同一个客户端和事件循环。
    这确保 app/core/database.py 的 engine（模块级单例）只在一个
    事件循环中创建连接池，避免跨模块 "Task got Future attached to
    a different loop" RuntimeError。

    前置: pytest.ini 中 asyncio_default_fixture_loop_scope = session
    """
    await _lifespan_startup(app)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=httpx.Timeout(10.0),
    ) as ac:
        try:
            yield ac
        finally:
            # 释放数据库连接池（session 结束时清理）
            try:
                from app.core.database import engine
                await engine.dispose()
                logger.debug("client fixture: 已释放数据库连接池")
            except RuntimeError as e:
                if "Event loop is closed" in str(e):
                    logger.debug("client fixture: 事件循环已关闭（Windows已知问题），跳过连接池释放")
                else:
                    raise


# ── M6: Phase 1 mock fixtures ──

@pytest_asyncio.fixture(scope="module")
async def auth_header(client: httpx.AsyncClient) -> dict[str, str]:
    """注册 + 登录，返回 Authorization header（模块级复用）"""
    import uuid
    username = f"test_kb_{uuid.uuid4().hex[:8]}"
    await client.post("/api/v1/auth/register", json={
        "username": username, "password": "test1234",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "username": username, "password": "test1234",
    })
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="function")
async def mock_embedding_and_vector(monkeypatch):
    """
    M6: 绕过 EmbeddingService + VectorStoreService 的真实网络调用。

    用 monkeypatch 替换为哑实现（返回固定向量 / 空操作），
    避免测试依赖 Ollama 和 ChromaDB 真实服务。
    """
    # Mock embedding_service.embed → 返回固定 768 维向量 (nomic-embed-text)
    async def mock_embed(text: str) -> list[float]:
        return [0.0] * 768

    async def mock_embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]

    # Mock vector_store_service methods → 空操作或预设结果
    async def mock_add_chunks(kb_id, chunk_ids, embeddings, documents, metadatas):
        pass

    async def mock_search(kb_id, query_embedding, top_k=5):
        return []

    async def mock_delete_chunks(kb_id, chunk_ids):
        pass

    async def mock_delete_collection(kb_id):
        pass

    async def mock_get_or_create(kb_id):
        pass

    from app.services import embedding_service as es
    from app.services import vector_store as vs

    monkeypatch.setattr(es.embedding_service, "embed", mock_embed)
    monkeypatch.setattr(es.embedding_service, "embed_batch", mock_embed_batch)
    monkeypatch.setattr(vs.vector_store_service, "add_chunks", mock_add_chunks)
    monkeypatch.setattr(vs.vector_store_service, "search", mock_search)
    monkeypatch.setattr(vs.vector_store_service, "delete_chunks", mock_delete_chunks)
    monkeypatch.setattr(vs.vector_store_service, "delete_collection", mock_delete_collection)
    monkeypatch.setattr(vs.vector_store_service, "get_or_create_collection", mock_get_or_create)


# ── Redis 频率限制清理 ──
# 注册/登录端点使用 Redis 滑动窗口限频（key = rate_limit:register:{ip}）。
# 测试过程中多次注册会快速耗尽配额，导致后续测试返回 429。
# 本 fixture 在 session 启动时清除所有 rate_limit key，
# 确保测试运行不受历史限频数据影响。


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _clear_rate_limits():
    """清除 Redis 频率限制计数器（session 级，自动执行）。

    单元测试通过 ASGITransport 在进程中运行，客户端 IP 固定为
    "127.0.0.1"。多次测试的注册请求共享同一个 rate_limit key，
    在默认配置下（REGISTER_RATE_LIMIT_MAX=100）一小时内最多
    100 次注册。清除计数器确保每次测试 session 从头开始计数。

    仅影响测试环境。Redis 不可用时静默跳过。
    """
    try:
        from app.core.redis_client import get_redis
        r = await get_redis()
        keys = await r.keys("rate_limit:*")
        if keys:
            deleted = await r.delete(*keys)
            logger.info("清除了 %d 个 Redis rate_limit key", deleted)
    except Exception:
        logger.debug("Redis 限频清理失败（Redis 不可用？），跳过")
    yield
