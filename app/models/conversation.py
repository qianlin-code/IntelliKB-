"""
对话/会话模型 —— 每个对话属于一个 KB 和一个用户
"""
from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class Conversation(Base, TimestampMixin, SoftDeleteMixin):
    """对话/会话"""
    __tablename__ = "sys_conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="知识库 ID")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="用户 ID")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="对话标题")
    message_count: Mapped[int] = mapped_column(Integer, default=0, comment="消息总数")
    # Phase 9: 收藏/置顶
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否置顶")
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否收藏")
