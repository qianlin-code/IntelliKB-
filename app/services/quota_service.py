"""
Phase 10: 资源配额服务
"""
import logging
from contextlib import asynccontextmanager

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.kb_member import KBMember

logger = logging.getLogger("app")


@asynccontextmanager
async def kb_creation_lock(db: AsyncSession, user_id: int, timeout: int = 10):
    """
    用户级知识库创建互斥锁（MySQL advisory lock）。

    在 MySQL 默认 REPEATABLE READ 隔离级别下，SELECT ... FOR UPDATE 只能锁定
    被读取的行，无法让跨表的 count 查询看到最新已提交数据。使用 GET_LOCK
    可以把「读 count → 判配额 → INSERT → commit」整个窗口串行化，从而真正
    消除并发竞态条件。
    """
    lock_name = f"kb_quota_user_{user_id}"
    acquired = (await db.execute(
        text("SELECT GET_LOCK(:lock_name, :timeout)"),
        {"lock_name": lock_name, "timeout": timeout},
    )).scalar()
    if not acquired:
        from app.core.exceptions import BusinessError
        raise BusinessError("系统繁忙，请稍后再试")
    try:
        yield
    finally:
        try:
            await db.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": lock_name},
            )
        except Exception:
            logger.warning("释放知识库配额锁失败 lock_name=%s", lock_name)


class QuotaService:
    """资源配额检查"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_kb_creation(self, user_id: int) -> tuple[bool, str]:
        """检查用户是否可以创建新 KB。返回 (ok, reason)。

        注意：此函数本身只做 count 检查，真正的并发串行化依赖调用方在
        kb_creation_lock 上下文内调用本函数，确保 count 与 INSERT 在同一
        互斥窗口内完成。
        """
        if not settings.QUOTA_ENABLED:
            return True, ""

        count = (await self.db.execute(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.owner_id == user_id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )).scalar() or 0

        limit = settings.QUOTA_MAX_KB_PER_USER
        if count >= limit:
            return False, f"知识库数量已达上限 ({count}/{limit})"
        return True, ""

    async def check_document_upload(self, kb_id: int) -> tuple[bool, str]:
        """检查 KB 是否可以继续上传文档。"""
        if not settings.QUOTA_ENABLED:
            return True, ""

        count = (await self.db.execute(
            select(func.count(Document.id)).where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
        )).scalar() or 0

        limit = settings.QUOTA_MAX_DOCUMENTS_PER_KB
        if count >= limit:
            return False, f"KB 文档数已达上限 ({count}/{limit})"
        return True, ""

    async def check_kb_member_add(self, kb_id: int) -> tuple[bool, str]:
        """检查 KB 是否可以继续添加成员。"""
        if not settings.QUOTA_ENABLED:
            return True, ""

        count = (await self.db.execute(
            select(func.count(KBMember.id)).where(
                KBMember.kb_id == kb_id,
            )
        )).scalar() or 0

        limit = settings.QUOTA_MAX_KB_MEMBERS_PER_KB
        if count >= limit:
            return False, f"KB 成员数已达上限 ({count}/{limit})"
        return True, ""

    async def get_user_storage_usage(self, user_id: int) -> int:
        """返回用户所有 KB 的文档总大小（bytes）"""
        try:
            total = (await self.db.execute(
                select(func.coalesce(func.sum(Document.file_size), 0)).select_from(Document).join(
                    KnowledgeBase, Document.kb_id == KnowledgeBase.id
                ).where(
                    KnowledgeBase.owner_id == user_id,
                    Document.deleted_at.is_(None),
                )
            )).scalar() or 0
            return int(total)
        except Exception:
            return 0
