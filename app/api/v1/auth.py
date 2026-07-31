"""
认证路由 —— 注册/登录/刷新/登出/API Key 管理

N9: register IP 限流 — 10 次/小时
     login IP 限流 — 5 次失败锁定 15 分钟
T6: register 先 incr 后业务（与 login 一致，防并发绕过）
"""
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.response import APIResponse
from app.core.exceptions import UnauthorizedError
from app.core.redis_client import get_redis
from app.depends.auth import get_current_user, get_current_user_or_api_key
from app.models.user import User
from app.schemas.user import (
    UserRegister, UserLogin, RefreshRequest, UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["用户认证"])


@router.post("/register", summary="用户注册")
async def register(
    body: UserRegister,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    注册新用户。N9: IP 限流 — 每 IP 每小时最多 10 次。
    T6: 先 incr 后业务（防并发绕过）。
    """
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"rate_limit:register:{client_ip}"

    # T6: 先 incr 占名额（Redis 不可用时跳过限流）
    try:
        r = await get_redis()
        count = await r.incr(rate_key)
        if count == 1:
            await r.expire(rate_key, settings.REGISTER_RATE_LIMIT_WINDOW)
        if count > settings.REGISTER_RATE_LIMIT_MAX:
            ttl = await r.ttl(rate_key)
            raise HTTPException(
                status_code=429,
                detail=f"注册次数过多，请 {max(1, ttl // 60)} 分钟后重试",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # Redis 不可用时跳过限流

    service = AuthService(db)
    user = await service.register(
        username=body.username, password=body.password, email=body.email,
    )

    return APIResponse.created(
        data=UserResponse.model_validate(user).model_dump(mode="json"),
        message="注册成功",
    )


@router.post("/login", summary="用户登录")
async def login(
    body: UserLogin, request: Request, db: AsyncSession = Depends(get_db),
):
    """登录 — Redis 计数器限流: 5 次失败锁定 15 分钟"""
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"rate_limit:login:{client_ip}"

    # 限流检查（Redis 不可用时跳过）
    try:
        r = await get_redis()
        attempts = await r.get(rate_key)
        if attempts and int(attempts) >= settings.LOGIN_RATE_LIMIT_MAX:
            ttl = await r.ttl(rate_key)
            raise HTTPException(
                status_code=429,
                detail=f"登录失败次数过多，请 {max(1, ttl // 60)} 分钟后重试",
            )
    except HTTPException:
        raise
    except Exception:
        r = None  # Redis 不可用

    service = AuthService(db)
    try:
        tokens = await service.login(body.username, body.password)
    except UnauthorizedError:
        if r is not None:
            try:
                count = await r.incr(rate_key)
                if count == 1:
                    await r.expire(rate_key, settings.LOGIN_RATE_LIMIT_WINDOW)
                remaining = max(0, settings.LOGIN_RATE_LIMIT_MAX - count)
            except Exception:
                remaining = "?"
        raise HTTPException(
            status_code=401,
            detail=f"用户名或密码错误，剩余尝试次数: {remaining}",
        )

    if r is not None:
        try:
            await r.delete(rate_key)
        except Exception:
            pass

    # Phase 10: 审计日志 — 登录
    user = await service.repo.get_by_username(body.username)
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, user.id, AuditAction.LOGIN, "user", user.id,
                    ip_address=request.client.host if request.client else None)

    return APIResponse.success(data=tokens, message="登录成功")


@router.post("/refresh", summary="刷新 Token")
async def refresh_token(
    body: RefreshRequest, db: AsyncSession = Depends(get_db),
):
    """N4: 刷新双 token，可选传入 current_access_token 以撤销旧 access。"""
    service = AuthService(db)
    tokens = await service.refresh_token(
        body.refresh_token, body.current_access_token,
    )
    return APIResponse.success(data=tokens, message="Token 刷新成功")


@router.post("/logout", summary="退出登录")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """登出 — access + refresh token 加入黑名单"""
    auth_header = request.headers.get("Authorization", "")
    access_token = auth_header.replace("Bearer ", "")
    refresh_token = request.headers.get("X-Refresh-Token")

    service = AuthService(db)
    await service.logout(current_user.id, access_token, refresh_token)
    return APIResponse.success(message="已退出登录")


@router.get("/me", summary="获取当前用户信息")
async def get_me(current_user: User = Depends(get_current_user_or_api_key)):
    """
    获取当前登录用户信息。

    认证方式：同时支持以下两种
    - Bearer Token:  Authorization: Bearer <access_token>   (Web 登录)
    - X-API-Key:     X-API-Key: sk-intellikb-xxxxxxxx       (外部 API 调用)
    """
    return APIResponse.success(
        data=UserResponse.model_validate(current_user).model_dump(mode="json"),
    )


@router.post("/api-key", summary="生成 API Key")
async def generate_api_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """生成 API Key — 原始值仅返回一次"""
    service = AuthService(db)
    raw = await service.generate_user_api_key(current_user.id)
    info = await service.get_api_key_info(current_user.id)
    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, current_user.id, AuditAction.API_KEY_CREATE, "user", current_user.id)
    return APIResponse.success(data={
        "api_key": raw,
        "prefix": info["prefix"],
        "expires_at": info["expires_at"],
    }, message="API Key 已生成，请立即保存")


@router.delete("/api-key", summary="吊销 API Key")
async def revoke_api_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    await service.revoke_api_key(current_user.id)
    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, current_user.id, AuditAction.API_KEY_DELETE, "user", current_user.id)
    return APIResponse.success(message="API Key 已吊销")


@router.get("/api-key/info", summary="查看 API Key 状态")
async def get_api_key_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    info = await service.get_api_key_info(current_user.id)
    return APIResponse.success(data=info)


@router.patch("/api-key", summary="更新 API Key 配置")
async def update_api_key(
    name: str | None = None,
    enabled: bool | None = None,
    monthly_quota: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 10: 更新 API Key 的名称、启用状态、月配额"""
    if name is not None:
        current_user.api_key_name = name[:100]
    if enabled is not None:
        current_user.api_key_enabled = enabled
    if monthly_quota is not None:
        current_user.api_key_monthly_quota = monthly_quota
    await db.flush()
    return APIResponse.success(data={
        "api_key_enabled": current_user.api_key_enabled,
        "api_key_name": current_user.api_key_name,
        "api_key_monthly_quota": current_user.api_key_monthly_quota,
    })


@router.get("/me/usage", summary="用户用量统计")
async def get_me_usage(
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Phase 10 P1.3: 返回当前用户的资源使用情况"""
    from app.services.quota_service import QuotaService
    from app.core.cost_tracker import get_usage_stats
    from sqlalchemy import func, select
    from app.models.knowledge_base import KnowledgeBase
    from app.models.document import Document

    quota_service = QuotaService(db)

    kb_count = (await db.execute(
        select(func.count(KnowledgeBase.id)).where(
            KnowledgeBase.owner_id == current_user.id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )).scalar() or 0

    doc_count = (await db.execute(
        select(func.count(Document.id)).join(
            KnowledgeBase, Document.kb_id == KnowledgeBase.id
        ).where(
            KnowledgeBase.owner_id == current_user.id,
            Document.deleted_at.is_(None),
        )
    )).scalar() or 0

    storage_bytes = await quota_service.get_user_storage_usage(current_user.id)
    token_stats = await get_usage_stats()

    return APIResponse.success(data={
        "kb_count": kb_count,
        "kb_limit": settings.QUOTA_MAX_KB_PER_USER if settings.QUOTA_ENABLED else "unlimited",
        "document_count": doc_count,
        "storage_bytes": storage_bytes,
        "storage_limit_mb": settings.QUOTA_MAX_STORAGE_MB_PER_USER if settings.QUOTA_ENABLED else "unlimited",
        "token_usage": token_stats,
        "api_key": {
            "enabled": current_user.api_key_enabled,
            "name": current_user.api_key_name or "default",
            "prefix": current_user.api_key_prefix,
            "last_used_at": str(current_user.api_key_last_used_at) if current_user.api_key_last_used_at else None,
            "monthly_quota": current_user.api_key_monthly_quota,
        },
        "system_role": current_user.system_role,
    })
