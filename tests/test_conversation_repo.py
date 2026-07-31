"""测试 ConversationRepository CRUD

Windows 事件循环修复:
    pytest-asyncio 为每个测试模块创建独立事件循环。
    engine.dispose() 在模块结束时释放数据库连接池，
    避免跨模块 "Task got Future attached to a different loop" 错误。

    移除自定义 event_loop fixture，使用 pytest-asyncio 默认的事件循环管理
    （pytest.ini 中 asyncio_default_fixture_loop_scope=module），
    避免手动事件循环与 pytest-asyncio 的冲突。
"""
import logging
import pytest

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

pytestmark = pytest.mark.asyncio

logger = logging.getLogger("unit_test")


@pytest.fixture(scope="module")
async def db_engine():
    """模块级数据库引擎（当前模块事件循环）。

    teardown 中释放连接池，防止连接残留影响下一个测试模块。
    """
    engine = create_async_engine(
        settings.database_url,
        echo=False, pool_size=5, max_overflow=10,
        pool_recycle=3600, pool_pre_ping=True,
    )
    yield engine
    # 释放连接池，防止跨模块事件循环冲突
    try:
        await engine.dispose()
        logger.debug("db_engine fixture: 已释放数据库连接池")
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            logger.debug("db_engine fixture: 事件循环已关闭（Windows已知问题）")
        else:
            raise


@pytest.fixture
async def db_session(db_engine):
    """函数级数据库会话，自动回滚不提交任何更改。

    Windows 事件循环修复:
        session.rollback() 需要向 MySQL 发送 ROLLBACK 命令。
        在 teardown 阶段，Windows ProactorEventLoop 可能已处于关闭过程中，
        此时发送命令会触发 "Event loop is closed" RuntimeError。
        捕获此异常并降级为 debug 日志。
    """
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        # 回滚测试更改（Windows 安全：捕获事件循环关闭异常）
        try:
            await session.rollback()
        except RuntimeError as e:
            if "Event loop is closed" in str(e) or "different loop" in str(e):
                logger.debug("db_session fixture: 事件循环已关闭，跳过 rollback（Windows已知问题）")
            else:
                raise


class TestConversationRepository:
    async def test_create_conversation(self, db_session):
        from app.repositories.conversation import ConversationRepository
        repo = ConversationRepository(db_session)

        conv = await repo.create({
            "kb_id": 1, "user_id": 1,
            "title": "测试对话", "message_count": 0,
        })
        assert conv.id is not None
        assert conv.title == "测试对话"
        assert conv.kb_id == 1
        assert conv.user_id == 1

    async def test_list_by_kb_and_user(self, db_session):
        from app.repositories.conversation import ConversationRepository
        repo = ConversationRepository(db_session)

        # Create test data
        await repo.create({"kb_id": 1, "user_id": 1, "title": "C1", "message_count": 0})
        await repo.create({"kb_id": 1, "user_id": 1, "title": "C2", "message_count": 0})
        await repo.create({"kb_id": 2, "user_id": 1, "title": "C3", "message_count": 0})

        items, total = await repo.list_by_kb_and_user(1, 1, 0, 10)
        # Should contain our test items + any existing data
        assert len(items) >= 2
        assert total >= 2

    async def test_get_by_id(self, db_session):
        from app.repositories.conversation import ConversationRepository
        repo = ConversationRepository(db_session)

        conv = await repo.create({"kb_id": 1, "user_id": 1, "title": "GetTest", "message_count": 0})
        fetched = await repo.get_by_id(conv.id)
        assert fetched is not None
        assert fetched.title == "GetTest"

    async def test_soft_delete(self, db_session):
        from app.repositories.conversation import ConversationRepository
        repo = ConversationRepository(db_session)

        conv = await repo.create({"kb_id": 1, "user_id": 1, "title": "DelTest", "message_count": 0})
        await repo.soft_delete(conv)

        # After soft delete, get_by_id should return None
        fetched = await repo.get_by_id(conv.id)
        assert fetched is None

    async def test_update(self, db_session):
        from app.repositories.conversation import ConversationRepository
        repo = ConversationRepository(db_session)

        conv = await repo.create({"kb_id": 1, "user_id": 1, "title": "OldTitle", "message_count": 0})
        conv.title = "NewTitle"
        await repo.update(conv)
        assert conv.title == "NewTitle"

    async def test_increment_message_count(self, db_session):
        from app.repositories.conversation import ConversationRepository
        repo = ConversationRepository(db_session)

        conv = await repo.create({"kb_id": 1, "user_id": 1, "title": "CountTest", "message_count": 0})
        await repo.increment_message_count(conv.id)
        # Re-fetch to verify
        conv2 = await repo.get_by_id(conv.id)
        assert conv2.message_count == 1
