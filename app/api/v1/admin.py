"""
Admin 管理 API（Phase 10）

所有端点需要 admin 及以上权限。
"""
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.response import APIResponse, make_trace_id
from app.depends.auth import get_current_user_or_api_key, require_admin, require_superadmin
from app.models.user import User

logger = logging.getLogger("app")
router = APIRouter(prefix="/admin", tags=["系统管理"])


# ── 用户管理（superadmin）──

@router.get("/users", summary="用户列表")
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, description="搜索用户名或邮箱"),
    role: str | None = Query(default=None, description="按系统角色筛选"),
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """列出所有用户（superadmin 专属）"""
    conditions = []
    if q:
        conditions.append(User.username.contains(q) | User.email.contains(q))
    if role:
        conditions.append(User.system_role == role)

    total_q = select(func.count(User.id))
    items_q = select(User).order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    if conditions:
        total_q = total_q.where(*conditions)
        items_q = items_q.where(*conditions)

    total = (await db.execute(total_q)).scalar() or 0
    result = await db.execute(items_q)
    users = result.scalars().all()

    return APIResponse.success(data={
        "items": [
            {
                "id": u.id, "username": u.username, "email": u.email,
                "system_role": u.system_role, "is_active": u.is_active,
                "created_at": str(u.created_at),
            }
            for u in users
        ],
        "total": total,
    }, trace_id=make_trace_id())


@router.patch("/users/{user_id}/role", summary="修改用户角色")
async def update_user_role(
    user_id: int,
    role: str = Query(..., regex="^(superadmin|admin|user)$"),
    request: Request = None,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """修改用户系统角色（superadmin 专属）"""
    await db.execute(
        update(User).where(User.id == user_id).values(system_role=role)
    )
    await db.commit()
    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, _admin.id, AuditAction.USER_ROLE_CHANGE, "user", user_id,
                    details={"new_role": role},
                    ip_address=request.client.host if request and request.client else None,
                    user_agent=request.headers.get("user-agent", "") if request else "")
    return APIResponse.success(data={"user_id": user_id, "system_role": role}, trace_id=make_trace_id())


# ── 系统统计（admin+）──

@router.get("/stats", summary="系统统计")
async def system_stats(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """返回系统统计信息"""
    from app.models.conversation import Conversation
    from app.models.document import Document
    from app.models.knowledge_base import KnowledgeBase

    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    kb_count = (await db.execute(select(func.count(KnowledgeBase.id)))).scalar() or 0
    doc_count = (await db.execute(select(func.count(Document.id)))).scalar() or 0
    conv_count = (await db.execute(select(func.count(Conversation.id)))).scalar() or 0

    return APIResponse.success(data={
        "user_count": user_count,
        "kb_count": kb_count,
        "document_count": doc_count,
        "conversation_count": conv_count,
        "llm_provider": settings.LLM_PROVIDER,
        "app_version": settings.APP_VERSION,
    }, trace_id=make_trace_id())


# ── 审计日志（admin+）──

@router.get("/audit-logs", summary="审计日志")
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user_id: int | None = Query(default=None),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """分页查询审计日志"""
    from app.models.audit_log import AuditLog

    conditions = []
    if user_id:
        conditions.append(AuditLog.user_id == user_id)
    if action:
        conditions.append(AuditLog.action == action)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if start_date:
        conditions.append(AuditLog.created_at >= start_date)
    if end_date:
        conditions.append(AuditLog.created_at <= end_date + "T23:59:59")

    total_q = select(func.count(AuditLog.id))
    items_q = select(AuditLog).order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    if conditions:
        total_q = total_q.where(*conditions)
        items_q = items_q.where(*conditions)

    total = (await db.execute(total_q)).scalar() or 0
    result = await db.execute(items_q)
    logs = result.scalars().all()

    return APIResponse.success(data={
        "items": [
            {
                "id": l.id, "user_id": l.user_id, "action": l.action,
                "resource_type": l.resource_type, "resource_id": l.resource_id,
                "details": l.details, "ip_address": l.ip_address,
                "created_at": str(l.created_at),
            }
            for l in logs
        ],
        "total": total,
    }, trace_id=make_trace_id())


# ── LLM 成本统计（admin+）──

@router.get("/llm-cost", summary="云端 LLM 成本统计")
async def llm_cost_stats(
    _admin: User = Depends(require_admin),
):
    """返回当前日/月 token 消耗和限额（基于 Redis 计数器）。"""
    from app.core.cost_tracker import get_usage_stats

    stats = await get_usage_stats()
    return APIResponse.success(data={
        "daily": stats["daily"],
        "monthly": stats["monthly"],
        "provider": settings.LLM_PROVIDER,
    }, trace_id=make_trace_id())


# ── 系统配置（superadmin）──

@router.get("/system-config", summary="系统配置")
async def get_system_config(
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """返回当前系统配置"""
    from app.models.system_config import SystemConfig
    result = await db.execute(select(SystemConfig))
    configs = result.scalars().all()
    return APIResponse.success(data={
        "items": [
            {"key": c.key, "value": c.value, "description": c.description, "updated_at": str(c.updated_at)}
            for c in configs
        ],
        "static_config": {
            "QUOTA_ENABLED": settings.QUOTA_ENABLED,
            "LLM_PROVIDER": settings.LLM_PROVIDER,
            "RERANK_ENABLED": settings.RERANK_ENABLED,
        },
    }, trace_id=make_trace_id())


@router.patch("/system-config/{key}", summary="更新系统配置")
async def update_system_config(
    key: str,
    value: str = Query(..., min_length=1),
    request: Request = None,
    _admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """热更新系统配置（superadmin 专属），修改后刷新内存缓存。"""
    from app.models.system_config import SystemConfig
    from app.core.time_utils import utcnow

    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = SystemConfig(key=key, value=value, description="", updated_by=_admin.id)
        db.add(cfg)
    else:
        cfg.value = value
        cfg.updated_by = _admin.id
        cfg.updated_at = utcnow()
    await db.commit()

    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, _admin.id, AuditAction.SYSTEM_CONFIG_UPDATE, "system_config", cfg.id,
                    details={"key": key, "value": value[:200]},
                    ip_address=request.client.host if request and request.client else None,
                    user_agent=request.headers.get("user-agent", "") if request else "")

    # Refresh in-memory cache
    try:
        from app.services.config_cache_service import refresh_config_cache
        await refresh_config_cache()
    except Exception:
        pass

    return APIResponse.success(data={"key": key, "value": value}, trace_id=make_trace_id())
