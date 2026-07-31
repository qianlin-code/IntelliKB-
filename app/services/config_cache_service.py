"""
Phase 10: 系统配置内存缓存

启动时加载 SystemConfig 表到内存，热更新时刷新。
"""
import logging

from sqlalchemy import select

logger = logging.getLogger("app")

# 内存缓存
_config_cache: dict[str, str] = {}


async def load_config_cache() -> None:
    """启动时加载所有 SystemConfig 到内存"""
    from app.core.database import async_session_factory
    from app.models.system_config import SystemConfig

    try:
        async with async_session_factory() as db:
            result = await db.execute(select(SystemConfig))
            configs = result.scalars().all()
            _config_cache.clear()
            for c in configs:
                _config_cache[c.key] = c.value
        logger.info("Config cache loaded: %d entries", len(_config_cache))
    except Exception as e:
        logger.warning("Failed to load config cache: %s", e)


async def refresh_config_cache() -> None:
    """热刷新缓存"""
    await load_config_cache()


def get_config(key: str, default: str = "") -> str:
    """读取配置缓存值，不存在时返回 default"""
    return _config_cache.get(key, default)
