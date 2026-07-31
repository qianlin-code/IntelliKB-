"""
知识库 CRUD 端点（Phase 10: 审计日志 + 配额检查）
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import async_session_factory, get_db
from app.core.response import APIResponse
from app.depends.auth import get_current_user_or_api_key
from app.models.user import User
from app.schemas.knowledge_base import KBCreate, KBUpdate, KBResponse, KBStats, AgentConfigUpdate
from app.schemas.member import MemberAdd, MemberUpdate
from app.services.kb_service import KBService
from app.services.quota_service import QuotaService, kb_creation_lock

router = APIRouter(prefix="/knowledge-bases", tags=["知识库管理"])


@router.post("", summary="创建知识库")
async def create_kb(
    body: KBCreate,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
):
    """创建知识库，自动初始化 Chroma Collection。

    使用独立 session 并在 MySQL advisory lock 保护下完成配额检查与 INSERT，
    确保事务在获得锁之后才启动，避免 REPEATABLE READ 快照导致 count 读到旧值。
    """
    async with async_session_factory() as db:
        async with kb_creation_lock(db, current_user.id):
            quota = QuotaService(db)
            ok, reason = await quota.check_kb_creation(current_user.id)
            if not ok:
                raise HTTPException(status_code=429, detail={"code": "QUOTA_EXCEEDED", "message": reason})

            service = KBService(db)
            kb = await service.create(current_user.id, body)
            # Phase 10: 审计日志
            from app.services.audit_service import log_event, AuditAction
            await log_event(db, current_user.id, AuditAction.KB_CREATE, "kb", kb.id,
                            ip_address=request.client.host if request.client else None,
                            user_agent=request.headers.get("user-agent", ""))
            # 在锁内提交：释放锁之前让其他并发请求看到最新已提交数量
            await db.commit()
    return APIResponse.created(data=KBResponse.model_validate(kb).model_dump(mode="json"))


@router.get("", summary="我的知识库列表")
async def list_kb(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户创建的知识库列表"""
    service = KBService(db)
    skip = (page - 1) * page_size
    kbs, total = await service.list_my(current_user.id, skip=skip, limit=page_size)
    return APIResponse.success(data={
        "items": [KBResponse.model_validate(k).model_dump(mode="json") for k in kbs],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/{kb_id}", summary="知识库详情")
async def get_kb(
    kb_id: int,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """获取知识库详情（owner 或公开 KB 可访问）"""
    service = KBService(db)
    kb = await service.get_accessible(kb_id, current_user.id)
    return APIResponse.success(data=KBResponse.model_validate(kb).model_dump(mode="json"))


@router.put("/{kb_id}", summary="更新知识库")
async def update_kb(
    kb_id: int,
    body: KBUpdate,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """更新知识库元信息（仅 owner）。M3: chunk_size/chunk_overlap 仅影响后续上传。"""
    service = KBService(db)
    kb = await service.update(kb_id, current_user.id, body)
    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, current_user.id, AuditAction.KB_UPDATE, "kb", kb_id,
                    details={"name": body.name or kb.name},
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent", ""))
    return APIResponse.success(data=KBResponse.model_validate(kb).model_dump(mode="json"))


@router.delete("/{kb_id}", summary="删除知识库")
async def delete_kb(
    kb_id: int,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """软删除知识库 + 清理 Chroma Collection + 文档同步软删除（S3）"""
    service = KBService(db)
    await service.delete(kb_id, current_user.id)
    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, current_user.id, AuditAction.KB_DELETE, "kb", kb_id,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent", ""))
    return APIResponse.success(message="知识库已删除")


# ── Phase 2: 成员管理 ──

@router.get("/{kb_id}/members", summary="成员列表")
async def list_members(
    kb_id: int,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """获取知识库成员列表（owner 或成员可查看）"""
    service = KBService(db)
    members = await service.list_members(kb_id, current_user.id)
    return APIResponse.success(data={"members": members})


@router.post("/{kb_id}/members", summary="添加成员")
async def add_member(
    kb_id: int,
    body: MemberAdd,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """添加知识库成员（仅 owner）"""
    # Phase 10: 配额检查
    from app.services.quota_service import QuotaService
    quota = QuotaService(db)
    ok, reason = await quota.check_kb_member_add(kb_id)
    if not ok:
        raise HTTPException(status_code=429, detail={"code": "QUOTA_EXCEEDED", "message": reason})

    service = KBService(db)
    member = await service.add_member(kb_id, current_user.id, body.user_id, body.role)
    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, current_user.id, AuditAction.KB_MEMBER_ADD, "kb", kb_id,
                    details={"added_user_id": body.user_id, "role": body.role},
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent", ""))
    return APIResponse.created(data={
        "user_id": member.user_id,
        "role": member.role,
        "created_at": member.created_at.isoformat(),
    })


@router.put("/{kb_id}/members/{user_id}", summary="修改成员角色")
async def update_member(
    kb_id: int,
    user_id: int,
    body: MemberUpdate,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """修改成员角色（仅 owner，不能修改自己的 role）"""
    service = KBService(db)
    member = await service.update_member(kb_id, current_user.id, user_id, body.role)
    return APIResponse.success(data={"user_id": member.user_id, "role": member.role})


@router.delete("/{kb_id}/members/{user_id}", summary="移除成员")
async def remove_member(
    kb_id: int,
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """移除成员（仅 owner，不能移除自己）"""
    service = KBService(db)
    await service.remove_member(kb_id, current_user.id, user_id)
    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, current_user.id, AuditAction.KB_MEMBER_REMOVE, "kb", kb_id,
                    details={"removed_user_id": user_id},
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent", ""))
    return APIResponse.success(message="成员已移除")


@router.post("/{kb_id}/transfer-owner", summary="转让 KB 所有者")
async def transfer_kb_owner(
    kb_id: int,
    new_owner_id: int = Query(..., alias="new_owner_id"),
    request: Request = None,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Phase 10: 转让 KB 所有权（仅 owner 可操作）"""
    service = KBService(db)
    kb = await service.get_accessible(kb_id, current_user.id)
    if kb.owner_id != current_user.id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("仅知识库所有者可转让")

    from app.repositories.user import UserRepository
    from app.core.exceptions import NotFoundError
    user_repo = UserRepository(db)
    new_owner = await user_repo.get_by_id(new_owner_id)
    if new_owner is None:
        raise NotFoundError("目标用户不存在")

    kb.owner_id = new_owner_id
    from app.repositories.knowledge_base import KBRepository
    repo = KBRepository(db)
    await repo.update(kb)

    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, current_user.id, AuditAction.KB_TRANSFER, "kb", kb_id,
                    details={"from_user_id": current_user.id, "to_user_id": new_owner_id},
                    ip_address=request.client.host if request and request.client else None,
                    user_agent=request.headers.get("user-agent", "") if request else "")

    return APIResponse.success(data={"kb_id": kb_id, "new_owner_id": new_owner_id})


@router.get("/{kb_id}/stats", summary="知识库统计")
async def kb_stats(
    kb_id: int,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """知识库统计（owner 或公开 KB 可访问）"""
    service = KBService(db)
    stats = await service.get_stats(kb_id, current_user.id)
    return APIResponse.success(data=stats.model_dump(mode="json"))


@router.patch("/{kb_id}/agent-config", summary="Agent 人设配置")
async def update_agent_config(
    kb_id: int,
    body: AgentConfigUpdate,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Phase 9: 配置知识库的 Agent 系统提示词和人设"""
    service = KBService(db)
    kb = await service.get_accessible(kb_id, current_user.id)
    if kb.owner_id != current_user.id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("仅知识库所有者可配置 Agent 人设")

    if body.system_prompt is not None:
        kb.system_prompt = body.system_prompt if body.system_prompt.strip() else None
    from app.repositories.knowledge_base import KBRepository
    repo = KBRepository(db)
    await repo.update(kb)

    return APIResponse.success(data={
        "kb_id": kb.id,
        "system_prompt": kb.system_prompt,
    })
