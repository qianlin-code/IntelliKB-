"""
知识库模型
"""
from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class KnowledgeBase(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "sys_kb"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="所有者用户 ID")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="知识库名称")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否公开")
    chunk_size: Mapped[int] = mapped_column(Integer, default=500, comment="分块大小（字符）")
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50, comment="分块重叠（字符）")
    embedding_model: Mapped[str] = mapped_column(
        String(100), default="nomic-embed-text", comment="Embedding 模型名"
    )
    # Phase 9: Agent 自定义人设
    system_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="自定义 Agent 系统提示词"
    )
