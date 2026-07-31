"""
对话服务 —— 对话生命周期管理 + 权限校验 + 语义标题（Phase 4）
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.conversation import Conversation
from app.repositories.conversation import ConversationRepository
from app.repositories.message import MessageRepository
from app.services.kb_service import KBService

logger = logging.getLogger("app")


class ConversationService:
    """对话生命周期管理"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.conv_repo = ConversationRepository(db)
        self.msg_repo = MessageRepository(db)

    async def list(
        self, kb_id: int, user_id: int, page: int, page_size: int,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[list[Conversation], int]:
        """列出某知识库的对话（按 updated_at DESC）。

        Phase 9: 支持搜索（标题 + 消息内容）和时间范围筛选。
        """
        from datetime import datetime

        skip = (page - 1) * page_size
        start_dt = datetime.fromisoformat(start_date) if start_date else None
        end_dt = datetime.fromisoformat(end_date) if end_date else None

        items, total = await self.conv_repo.list_by_kb_and_user(
            kb_id, user_id, skip, page_size,
            search=search,
            start_date=start_dt,
            end_date=end_dt,
        )
        return items, total

    async def create(self, kb_id: int, user_id: int, title: str | None = None) -> Conversation:
        """创建新对话"""
        # 校验 KB 访问权限
        kb_service = KBService(self.db)
        await kb_service.get_accessible(kb_id, user_id)

        conv = await self.conv_repo.create({
            "kb_id": kb_id,
            "user_id": user_id,
            "title": title or "新对话",
            "message_count": 0,
        })
        logger.info("对话已创建 id=%d kb=%d user=%d", conv.id, kb_id, user_id)
        return conv

    async def get(self, conv_id: int, user_id: int) -> Conversation:
        """对话详情"""
        conv = await self.conv_repo.get_by_id(conv_id)
        if conv is None:
            raise NotFoundError("对话不存在")
        # 只能操作自己的对话
        if conv.user_id != user_id:
            raise ForbiddenError("无权访问该对话")
        return conv

    async def update_title(self, conv_id: int, user_id: int, title: str) -> Conversation:
        """更新标题"""
        conv = await self.get(conv_id, user_id)
        conv.title = title
        return await self.conv_repo.update(conv)

    async def update_meta(
        self, conv_id: int, user_id: int,
        title: str | None = None,
        is_pinned: bool | None = None,
        is_starred: bool | None = None,
    ) -> Conversation:
        """Phase 9: 更新对话元数据（标题/置顶/收藏）"""
        conv = await self.get(conv_id, user_id)
        if title is not None:
            conv.title = title
        if is_pinned is not None:
            conv.is_pinned = is_pinned
        if is_starred is not None:
            conv.is_starred = is_starred
        return await self.conv_repo.update(conv)

    async def delete(self, conv_id: int, user_id: int) -> None:
        """
        删除对话：
        1. 先清理 checkpoint（Phase 4）
        2. 再硬删除所有关联消息
        3. 最后软删除对话
        """
        conv = await self.get(conv_id, user_id)

        # Phase 4: 清理 checkpoint
        try:
            from app.services.checkpoint_cleanup_service import CheckpointCleanupService
            cleanup_service = CheckpointCleanupService(self.db)
            await cleanup_service.cleanup_thread(f"conv:{conv_id}")
        except Exception as e:
            logger.warning("Checkpoint cleanup failed for conv=%d: %s", conv_id, str(e))

        # 硬删除消息
        deleted_count = await self.msg_repo.hard_delete_by_conversation(conv_id)
        logger.info("硬删除 %d 条消息 (conversation=%d)", deleted_count, conv_id)

        # 软删除对话
        await self.conv_repo.soft_delete(conv)
        logger.info("对话已删除 id=%d", conv_id)

    async def get_messages(
        self, conv_id: int, user_id: int, before_id: int | None, limit: int,
    ) -> tuple[list, bool]:
        """消息列表（游标分页）"""
        conv = await self.get(conv_id, user_id)  # 权限校验
        items, has_more = await self.msg_repo.list_by_conversation(conv_id, before_id, limit)
        return items, has_more

    @staticmethod
    def generate_title(question: str) -> str:
        """自动生成标题（取前 N 字 + '...'）"""
        max_len = settings.CONVERSATION_TITLE_LENGTH
        if len(question) <= max_len:
            return question
        return question[:max_len] + "..."

    # ── Phase 4: 语义标题 ──

    @staticmethod
    async def generate_semantic_title(question: str, answer: str, llm_client) -> str:
        """使用 LLM 生成对话标题（≤12 字）"""
        try:
            response = await llm_client.chat.completions.create(
                model=settings.AGENT_MODEL,
                messages=[
                    {"role": "system", "content": "为以下对话生成一个简洁的标题（不超过12个汉字）。只返回标题本身，不要引号或额外文字。"},
                    {"role": "user", "content": f"问题：{question[:200]}\n回答摘要：{answer[:200]}"},
                ],
                max_tokens=20,
                temperature=0.3,
            )
            title = response.choices[0].message.content.strip()
            return title[:12]  # 与提示词"不超过12个汉字"保持一致，防止模型超长
        except Exception:
            return ConversationService.generate_title(question)  # fallback
