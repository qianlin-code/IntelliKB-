"""
Phase 10: 系统配置模型（热更新）
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base, TimestampMixin


class SystemConfig(Base, TimestampMixin):
    """可热更新的系统配置"""
    __tablename__ = "sys_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="配置键")
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="配置值")
    description: Mapped[str] = mapped_column(String(500), default="", comment="配置说明")
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="修改人 ID")
