"""
FastAPI 应用入口 —— 生命周期 + 中间件 + 路由挂载

Phase 4: 集成 checkpoint 周期清理任务到 lifespan。
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from alembic.config import Config as AlembicConfig
from alembic import command

from app.api.v1 import router as v1_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import setup_cors, TraceMiddleware, LoggingMiddleware
from app.core.redis_client import get_redis, close_redis


async def _periodic_checkpoint_cleanup():
    """每小时清理过期 checkpoint（带异常保护，单次失败不影响下一周期）"""
    from app.core.database import async_session_factory
    while True:
        try:
            async with async_session_factory() as db:
                from app.services.checkpoint_cleanup_service import CheckpointCleanupService
                service = CheckpointCleanupService(db)
                deleted = await service.cleanup_expired()
                if deleted:
                    logging.getLogger("app").info("Periodic checkpoint cleanup: deleted %d", deleted)
        except asyncio.CancelledError:
            break  # 优雅退出
        except Exception as e:
            logging.getLogger("app").exception("Checkpoint periodic cleanup error: %s", e)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期（Phase 3 alembic + Phase 4 checkpoint 清理）"""
    setup_logging()
    logger = logging.getLogger("app")

    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")

    # Phase 1: 确保上传目录 + Chroma 持久化目录存在
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)

    # N2: alembic 升级到最新
    try:
        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_cfg.attributes["configure_logger"] = False
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: command.upgrade(alembic_cfg, "head")
        )
        logger.info("Database migrations applied")
    except Exception as e:
        logger.error(f"Database migration failed: {e}", exc_info=True)
        raise

    # Redis 预热
    try:
        r = await get_redis()
        await r.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis not available: {e}")

    # Phase 1: Embedding 模型预热（后台，不阻塞启动）
    try:
        from app.services.embedding_service import embedding_service
        asyncio.create_task(embedding_service.warmup())
    except Exception as e:
        logger.warning(f"Embedding warmup skipped: {e}")

    # Phase 10: 加载系统配置缓存
    try:
        from app.services.config_cache_service import load_config_cache
        await load_config_cache()
    except Exception as e:
        logger.warning(f"Config cache load skipped: {e}")

    # Phase 4: 启动 checkpoint 周期清理任务（挂在 app.state 上，便于单元测试隔离）
    logger.info("Starting checkpoint cleanup background task")
    checkpoint_cleanup_task = asyncio.create_task(_periodic_checkpoint_cleanup())
    app.state.checkpoint_cleanup_task = checkpoint_cleanup_task

    # 种子数据（仅 dev 环境）
    if settings.ENVIRONMENT == "development":
        try:
            from app.core.database import get_db
            async for db in get_db():
                from scripts.seed_data import init_seed_data
                await init_seed_data(db)
                break
        except Exception as e:
            logger.warning(f"Seed data skipped: {e}")

    yield

    # 关闭：取消周期任务
    task = getattr(app.state, "checkpoint_cleanup_task", None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # 预期取消
        except Exception as e:
            logger.exception("Checkpoint cleanup task shutdown error: %s", e)
    logger.info("Checkpoint cleanup background task stopped")

    await close_redis()
    logger.info("IntelliKB shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

# 中间件
setup_cors(app)
app.add_middleware(TraceMiddleware)
app.add_middleware(LoggingMiddleware)

# 异常处理器
register_exception_handlers(app)

# 路由
app.include_router(v1_router)

# Phase 5: RAG 评测路由（RAG_EVAL_ENABLED=False 时不注册，请求返回 404）
if settings.RAG_EVAL_ENABLED:
    from app.api.v1.eval import router as eval_router
    app.include_router(eval_router, prefix="/api/v1")

# Phase 10: 管理后台路由
from app.api.v1.admin import router as admin_router
app.include_router(admin_router, prefix="/api/v1")

@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse(content={
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    })
