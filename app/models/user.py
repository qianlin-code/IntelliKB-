"""
用户模型
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="用户名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 哈希")
    email: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="邮箱")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    # Phase 10: 系统角色
    system_role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user",
        comment="系统角色: superadmin | admin | user"
    )

    # API Key
    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="bcrypt 哈希")
    api_key_prefix: Mapped[str | None] = mapped_column(String(12), nullable=True, comment="展示用前缀 sk-intellikb")
    api_key_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="过期时间")
    api_key_last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="最后使用时间")
    api_key_enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    # Phase 10: API Key 扩展
    api_key_name: Mapped[str | None] = mapped_column(String(100), nullable=True, default="default", comment="Key 名称/用途")
    api_key_monthly_quota: Mapped[int] = mapped_column(Integer, default=0, comment="月 token 配额，0=无限制")
