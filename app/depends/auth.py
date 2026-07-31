"""
认证依赖注入 —— get_current_user / get_current_user_or_api_key

认证方式：
- Bearer Token:  Authorization: Bearer <access_token>      (Web 登录)
- X-API-Key:     X-API-Key: sk-intellikb-xxxxxxxx          (外部 API 调用)

T7 技术债: API Key 验证当前通过 prefix 缩小范围后遍历做 bcrypt 逐一比对，
Phase 0 用户量小可接受。大规模场景见 docs/adr/001-tech-debt.md。

N5: 所有认证路径均显式校验 is_active。
T17: 延迟导入已上移到模块顶部。
"""
import logging
import time

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.redis_client import get_redis
from app.core.security import decode_token, verify_secret_async
from app.core.time_utils import utcnow
from app.models.user import User
from app.repositories.user import UserRepository

logger = logging.getLogger("app")
security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """仅 Bearer Token (JWT) 认证"""
    if not credentials:
        raise UnauthorizedError("未提供认证凭证")
    return await _verify_jwt_and_get_user(credentials.credentials, db)


async def get_current_user_or_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    同时支持 Bearer Token 和 X-API-Key Header。

    - Bearer Token:  Authorization: Bearer <access_token>
    - X-API-Key:     X-API-Key: sk-intellikb-xxxxxxxx
    """
    if credentials:
        return await _verify_jwt_and_get_user(credentials.credentials, db)

    api_key = request.headers.get("X-API-Key")
    if api_key:
        return await _verify_api_key_and_get_user(api_key, db)

    raise UnauthorizedError("未提供认证凭证")


async def _verify_jwt_and_get_user(token: str, db: AsyncSession) -> User:
    try:
        payload = decode_token(token)
    except Exception:
        raise UnauthorizedError("Token 无效或已过期")

    # 黑名单检查（Redis 不可用时跳过）
    try:
        r = await get_redis()
        if await r.exists(f"blacklist:{payload['jti']}"):
            raise UnauthorizedError("Token 已失效，请重新登录")
    except UnauthorizedError:
        raise
    except Exception:
        pass

    if payload.get("type") != "access":
        raise UnauthorizedError("Token 类型错误，需要 access token")

    repo = UserRepository(db)
    user = await repo.get_by_id(int(payload["sub"]))
    return _validate_user_active(user)


async def _verify_api_key_and_get_user(api_key: str, db: AsyncSession) -> User:
    """
    T7: 技术债 — 当前用遍历匹配 prefix + bcrypt 逐一校验。

    阶段     策略
    Phase 0  遍历 enabled 用户（prefix 缩小范围）+ bcrypt 逐一比对
    Phase 2+ prefix.id.secret 三段式 或 api_key_hash 唯一索引

    见 docs/adr/001-tech-debt.md。
    """
    t_start = time.monotonic()
    _masked = api_key[:12] + "***"
    prefix = api_key[:12]

    # 查询 prefix 匹配且 API Key 已启用的用户
    result = await db.execute(
        select(User).where(
            User.api_key_enabled.is_(True),
            User.api_key_prefix == prefix,
        )
    )
    users = result.scalars().all()
    logger.debug("API Key prefix=%s matched %d users", prefix, len(users))

    now = utcnow()
    for user in users:
        # 防御: api_key_hash 可能为 None（用户从未生成过 API Key）
        if not user.api_key_hash:
            continue

        try:
            verified = await verify_secret_async(api_key, user.api_key_hash)
        except Exception:
            logger.warning("bcrypt verify failed for user %d", user.id, exc_info=True)
            continue

        if verified:
            # 过期检查（utcnow() 与 user.api_key_expires_at 均为 naive UTC）
            if user.api_key_expires_at is not None and user.api_key_expires_at < now:
                logger.warning("API Key expired for user %d", user.id)
                raise UnauthorizedError("API Key 已过期")

            user.api_key_last_used_at = now
            try:
                await db.flush()
            except Exception:
                logger.exception("Failed to flush api_key_last_used_at for user %d", user.id)

            elapsed_ms = (time.monotonic() - t_start) * 1000
            logger.info("API Key verified for user %d in %.1fms", user.id, elapsed_ms)
            return _validate_user_active(user)

    elapsed_ms = (time.monotonic() - t_start) * 1000
    logger.warning("API Key verification failed for prefix=%s (%.1fms)", prefix, elapsed_ms)
    raise UnauthorizedError("API Key 无效")


def _validate_user_active(user: User | None) -> User:
    """N5: 显式校验用户存在 + is_active"""
    if user is None:
        raise UnauthorizedError("用户不存在")
    if not user.is_active:
        raise UnauthorizedError("用户已被禁用，请联系管理员")
    return user


# ── Phase 2: Cookie-based 认证（SSE 端点用）──

async def get_current_user_cookie(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    S1: 用于 SSE 端点的多方式认证（EventSource / fetch 无法设置自定义 header）。

    优先级:
      1. access_token query param（前端 SSE 显式传递，避免陈旧 Cookie 干扰）
      2. Cookie access_token
      3. Authorization Bearer
      4. X-API-Key

    说明：query param 优先于 Cookie，是因为前端在 SSE 场景下显式通过 URL
    传递当前有效 token；若浏览器中存在同名陈旧 Cookie，按旧优先级会覆盖
    query param 导致 401。
    """
    # SSE 场景：EventSource / fetch 无法设置自定义 Header，允许通过 query param 传递 token
    token = request.query_params.get("access_token")
    if token:
        return await _verify_jwt_and_get_user(token, db)

    # Cookie 认证
    token = request.cookies.get("access_token")
    if token:
        return await _verify_jwt_and_get_user(token, db)

    # Fallback: 尝试 Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return await _verify_jwt_and_get_user(token, db)

    # Fallback: 尝试 API Key
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        return await _verify_api_key_and_get_user(api_key, db)

    raise UnauthorizedError("未提供认证凭证（Cookie/Bearer/API Key）")


# ═══════════════════════════════════════════════════════════
# Phase 10: RBAC 角色守卫（放在所有被依赖函数之后）
# ═══════════════════════════════════════════════════════════

async def require_superadmin(
    current_user: User = Depends(get_current_user_or_api_key),
) -> User:
    """要求 superadmin 角色"""
    if current_user.system_role != "superadmin":
        raise ForbiddenError("需要超级管理员权限")
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_user_or_api_key),
) -> User:
    """要求 admin 及以上角色"""
    if current_user.system_role not in ("admin", "superadmin"):
        raise ForbiddenError("需要管理员权限")
    return current_user


async def require_kb_owner(
    kb_id: int,
    current_user: User = Depends(get_current_user_or_api_key),
) -> User:
    """要求当前用户是 KB owner（具体 KB 的 owner 检查由 KBService 完成，此处仅返回用户）"""
    return current_user
