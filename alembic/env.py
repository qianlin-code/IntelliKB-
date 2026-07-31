"""
alembic env.py — T18: Phase 0 使用 sync 模式（command.upgrade）。

由 main.py lifespan 通过 run_in_executor 调用。
Phase 1 引入大量异步模型后可切换为异步 migration。
"""
import sys
import os
from logging.config import fileConfig

from sqlalchemy import create_engine
from sqlalchemy import pool

from alembic import context

# 确保项目根在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings
from app.models.base import Base
from app.models.user import User  # noqa: F401 确保模型被导入

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置 target_metadata
target_metadata = Base.metadata

# F8: 从 settings 读取同步 URL，未配置则自动转换
SYNC_URL = settings.ALEMBIC_SYNC_URL or settings.database_url.replace(
    "+aiomysql", "+pymysql"
)


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本"""
    context.configure(
        url=SYNC_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移"""
    connectable = create_engine(SYNC_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
