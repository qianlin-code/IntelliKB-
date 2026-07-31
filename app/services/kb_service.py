"""
知识库业务逻辑
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ForbiddenError
from app.models.knowledge_base import KnowledgeBase
from app.repositories.knowledge_base import KBRepository
from app.repositories.document import DocumentRepository
from app.schemas.knowledge_base import KBCreate, KBUpdate, KBStats
from app.services.vector_store import vector_store_service

logger = logging.getLogger("app")


class KBService:
    """知识库 CRUD"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = KBRepository(db)
        self.doc_repo = DocumentRepository(db)

    async def create(self, user_id: int, data: KBCreate) -> KnowledgeBase:
        """创建知识库 + 初始化 Chroma Collection + 自动添加 owner 为 KBMember"""
        kb = await self.repo.create({
            "owner_id": user_id,
            "name": data.name,
            "description": data.description,
            "is_public": data.is_public,
            "chunk_size": data.chunk_size,
            "chunk_overlap": data.chunk_overlap,
        })
        # Phase 2: 自动添加 owner 为 KBMember
        from app.repositories.kb_member import KBMemberRepository
        member_repo = KBMemberRepository(self.db)
        await member_repo.create({"kb_id": kb.id, "user_id": user_id, "role": "owner"})
        # 初始化 Chroma Collection
        await vector_store_service.get_or_create_collection(kb.id)
        logger.info("知识库创建成功 id=%d name=%s", kb.id, kb.name)
        return kb

    async def list_my(
        self, user_id: int, skip: int = 0, limit: int = 20
    ) -> tuple[list[KnowledgeBase], int]:
        """我的知识库列表"""
        kbs = await self.repo.list_by_owner(user_id, skip=skip, limit=limit)
        total = await self.repo.count_by_owner(user_id)
        return kbs, total

    async def get(self, kb_id: int) -> KnowledgeBase:
        """获取知识库，不存在则抛 NotFoundError"""
        kb = await self.repo.get_by_id(kb_id)
        if kb is None:
            raise NotFoundError("知识库不存在")
        return kb

    async def get_accessible(self, kb_id: int, user_id: int) -> KnowledgeBase:
        """Phase 4: 获取知识库并校验权限（owner / public / KBMember 缓存 + 否定缓存）"""
        kb = await self.get(kb_id)
        if kb.owner_id == user_id:
            return kb
        if kb.is_public:
            return kb

        # Phase 4: 先查缓存
        from app.services.kb_member_cache import kb_member_cache
        role = await kb_member_cache.get_role(kb_id, user_id)
        if role:
            return kb
        if await kb_member_cache.is_negative(kb_id, user_id):
            # 否定缓存命中 — 该用户在 60s 内已被确认无权限
            raise ForbiddenError("无权访问该知识库")

        # miss → 查 DB → 回填
        from app.repositories.kb_member import KBMemberRepository
        member_repo = KBMemberRepository(self.db)
        member = await member_repo.get_by_kb_and_user(kb_id, user_id)
        if member is not None:
            # 回填整个 KB 的成员缓存（一次 DB 查询缓存整组）
            members = await member_repo.list_by_kb(kb_id)
            member_dict = {str(m.user_id): m.role for m in members}
            await kb_member_cache.set_members(kb_id, member_dict)
            return kb

        # DB miss → 设置否定缓存（60s TTL），避免无权限用户反复穿透到 DB
        await kb_member_cache.set_negative(kb_id, user_id)
        raise ForbiddenError("无权访问该知识库")

    async def get_owned(self, kb_id: int, user_id: int) -> KnowledgeBase:
        """获取知识库并校验 owner 权限"""
        kb = await self.get(kb_id)
        if kb.owner_id != user_id:
            raise ForbiddenError("仅知识库所有者可执行此操作")
        return kb

    async def get_editable(self, kb_id: int, user_id: int) -> KnowledgeBase:
        """Phase 4: 获取知识库并校验编辑权限（owner 或 editor），含缓存"""
        kb = await self.get(kb_id)
        if kb.owner_id == user_id:
            return kb

        # Phase 4: 先查缓存
        from app.services.kb_member_cache import kb_member_cache, ROLE_EDITOR, ROLE_OWNER
        role = await kb_member_cache.get_role(kb_id, user_id)
        if role and role in (ROLE_OWNER, ROLE_EDITOR):
            return kb
        # miss 或 缓存的角色无编辑权限 → 查 DB

        from app.repositories.kb_member import KBMemberRepository
        member_repo = KBMemberRepository(self.db)
        member = await member_repo.get_by_kb_and_user(kb_id, user_id)
        if member and member.role in (ROLE_OWNER, ROLE_EDITOR):
            # 回填缓存
            members = await member_repo.list_by_kb(kb_id)
            member_dict = {str(m.user_id): m.role for m in members}
            await kb_member_cache.set_members(kb_id, member_dict)
            return kb

        raise ForbiddenError("无权编辑该知识库")

    # ── Phase 2: 成员管理 ──

    async def add_member(self, kb_id: int, owner_id: int, user_id: int, role: str):
        """添加成员（仅 owner 可操作）"""
        kb = await self.get_owned(kb_id, owner_id)  # 校验 owner
        from app.repositories.kb_member import KBMemberRepository
        from app.models.user import User
        from sqlalchemy import select
        from app.services.kb_member_cache import kb_member_cache
        member_repo = KBMemberRepository(self.db)
        # 校验用户存在
        result = await self.db.execute(select(User).where(User.id == user_id))
        if result.scalar_one_or_none() is None:
            raise NotFoundError("用户不存在")
        # 校验不重复
        existing = await member_repo.get_by_kb_and_user(kb_id, user_id)
        if existing is not None:
            from app.core.exceptions import ConflictError
            raise ConflictError("该用户已是知识库成员")
        member = await member_repo.create({"kb_id": kb_id, "user_id": user_id, "role": role})
        # Phase 4: 主动失效缓存
        await kb_member_cache.invalidate(kb_id)
        logger.info("添加成员 kb=%d user=%d role=%s", kb_id, user_id, role)
        return member

    async def list_members(self, kb_id: int, user_id: int):
        """成员列表（owner 或成员可查看）"""
        await self.get_accessible(kb_id, user_id)
        from app.repositories.kb_member import KBMemberRepository
        from app.models.user import User
        from sqlalchemy import select
        member_repo = KBMemberRepository(self.db)
        members = await member_repo.list_by_kb(kb_id)
        # 填充 username
        result = []
        for m in members:
            user_result = await self.db.execute(select(User.username).where(User.id == m.user_id))
            username = user_result.scalar_one_or_none() or ""
            result.append({
                "user_id": m.user_id,
                "username": username,
                "role": m.role,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            })
        return result

    async def update_member(self, kb_id: int, owner_id: int, target_user_id: int, role: str):
        """修改成员角色（仅 owner 可操作，不能修改自己的 role）"""
        await self.get_owned(kb_id, owner_id)
        if owner_id == target_user_id:
            from app.core.exceptions import BusinessError
            raise BusinessError("不能修改自己的角色")
        from app.repositories.kb_member import KBMemberRepository
        from app.services.kb_member_cache import kb_member_cache
        member_repo = KBMemberRepository(self.db)
        member = await member_repo.get_by_kb_and_user(kb_id, target_user_id)
        if member is None:
            raise NotFoundError("成员不存在")
        member.role = role
        result = await member_repo.update(member)
        # Phase 4: 主动失效缓存
        await kb_member_cache.invalidate(kb_id)
        return result

    async def remove_member(self, kb_id: int, owner_id: int, target_user_id: int):
        """移除成员（仅 owner 可操作，不能移除自己）"""
        await self.get_owned(kb_id, owner_id)
        if owner_id == target_user_id:
            from app.core.exceptions import BusinessError
            raise BusinessError("不能移除自己")
        from app.repositories.kb_member import KBMemberRepository
        from app.services.kb_member_cache import kb_member_cache
        member_repo = KBMemberRepository(self.db)
        member = await member_repo.get_by_kb_and_user(kb_id, target_user_id)
        if member is None:
            raise NotFoundError("成员不存在")
        await member_repo.delete(member)
        # Phase 4: 主动失效缓存
        await kb_member_cache.invalidate(kb_id)
        logger.info("移除成员 kb=%d user=%d", kb_id, target_user_id)

    async def update(self, kb_id: int, user_id: int, data: KBUpdate) -> KnowledgeBase:
        """
        更新知识库元信息。

        M3: 修改 chunk_size/chunk_overlap 仅影响后续上传文档，已有文档不会自动重分块。
        """
        kb = await self.get_owned(kb_id, user_id)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(kb, field, value)
        return await self.repo.update(kb)

    async def delete(self, kb_id: int, user_id: int) -> None:
        """
        软删除知识库 + 删除 Chroma Collection + 清理文档。

        S3: chunk 同步软删除 — KB → Document → DocumentChunk 三层软删除。
        """
        kb = await self.get_owned(kb_id, user_id)

        # 1. 软删除所有 chunk（S3）
        chunk_count = await self.doc_repo.soft_delete_chunks_by_kb(kb_id)
        logger.info("软删除 %d 条 chunk (kb_id=%d)", chunk_count, kb_id)

        # 2. 软删除所有文档
        doc_count = await self.doc_repo.soft_delete_by_kb(kb_id)
        logger.info("软删除 %d 个文档 (kb_id=%d)", doc_count, kb_id)

        # 3. 删除 Chroma Collection
        await vector_store_service.delete_collection(kb_id)

        # 4. 软删除知识库
        await self.repo.soft_delete(kb)
        logger.info("知识库已删除 id=%d name=%s", kb.id, kb.name)

    async def get_stats(self, kb_id: int, user_id: int) -> KBStats:
        """知识库统计"""
        kb = await self.get_accessible(kb_id, user_id)
        doc_count = await self.doc_repo.count_by_kb(kb_id)
        chunk_count = await self.doc_repo.count_chunks_by_kb(kb_id)
        total_size = await self.doc_repo.total_size_by_kb(kb_id)
        return KBStats(
            kb_id=kb_id,
            document_count=doc_count,
            chunk_count=chunk_count,
            total_size_bytes=total_size or 0,
        )
