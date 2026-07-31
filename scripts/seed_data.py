"""
种子数据 —— 仅开发环境创建默认管理员。

N6: init_seed_data(db: AsyncSession) 显式接收 db。
N17: 幂等检查 — 表已有任意用户则跳过种子。
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import hash_secret
from app.models.user import User

logger = logging.getLogger("app")


async def init_seed_data(db: AsyncSession) -> None:
    """
    幂等创建管理员用户。

    - ENVIRONMENT == "development" → admin / admin123
    - 否则 → admin / ADMIN_PASSWORD（环境变量）
    """
    # N17: 幂等检查 — 表已有任意用户则跳过种子
    try:
        result = await db.execute(select(User.id).limit(1))
        if result.scalar_one_or_none() is not None:
            logger.info("数据库已有用户，跳过种子数据")
            return
    except Exception as e:
        logger.warning(f"无法检查数据库状态，跳过种子数据: {e}")
        return

    # 确定管理员密码
    if settings.ENVIRONMENT == "development":
        password = "admin123"
    else:
        password = settings.ADMIN_PASSWORD
        if not password:
            raise RuntimeError("生产环境必须设置 ADMIN_PASSWORD 环境变量")
        if settings.is_weak_password(password):
            raise RuntimeError(
                f"ADMIN_PASSWORD '{password}' 在弱密码黑名单中，请更换。\n"
                f"可用的强密码示例: python -c \"import secrets; print(secrets.token_urlsafe(16))\""
            )

    # 幂等创建
    result = await db.execute(select(User).where(User.username == "admin"))
    existing_admin = result.scalar_one_or_none()
    if existing_admin:
        # Fix: 确保已有 admin 用户的 system_role 为 superadmin（幂等更新）
        if existing_admin.system_role != "superadmin":
            existing_admin.system_role = "superadmin"
            await db.commit()
            logger.info("已更新 admin 用户的 system_role → superadmin")
        else:
            logger.info("管理员用户已存在，跳过创建")
        return

    db.add(User(
        username="admin",
        password_hash=hash_secret(password),
        email="admin@intellikb.dev",
        is_active=True,
        system_role="superadmin",
    ))
    await db.commit()
    logger.info(f"管理员用户 admin 创建完成 (ENV={settings.ENVIRONMENT})")


async def main():
    from app.core.database import async_session_factory
    async with async_session_factory() as db:
        await init_seed_data(db)


if __name__ == "__main__":
    asyncio.run(main())
