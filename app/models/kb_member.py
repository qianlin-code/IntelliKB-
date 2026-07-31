"""
知识库成员模型
"""
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KBMember(Base, TimestampMixin):
    """知识库成员（不可软删除，删除 KB 时 CASCADE 清除）"""
    __tablename__ = "sys_kb_member"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="知识库 ID")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="用户 ID")
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="viewer",
        comment="角色: owner / editor / viewer"
    )
