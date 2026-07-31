"""
ORM 基类 —— 软删除 Mixin + 公共字段
"""
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """所有模型基类"""


class TimestampMixin:
    """创建时间 + 更新时间（Python-side default，兼容 flush 未提交场景）"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), comment="更新时间"
    )


class SoftDeleteMixin:
    """软删除 —— 所有 DELETE 操作改为标记删除"""
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None, comment="删除时间"
    )
