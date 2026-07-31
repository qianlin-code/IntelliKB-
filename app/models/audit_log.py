"""
Phase 10: 审计日志模型
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class AuditLog(Base):
    """审计日志"""
    __tablename__ = "sys_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="操作用户 ID")
    action: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="操作类型: LOGIN, KB_CREATE, DOCUMENT_UPLOAD, etc."
    )
    resource_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="资源类型: kb, document, user, etc."
    )
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="资源 ID")
    details: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON 详情")
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now(), server_default=func.now(),
    )
