"""
LangGraph Checkpointer 持久化模型

语义说明：
- type: 语义类型，如 "checkpoint" / "pending_writes"
- serde_type: serde 序列化类型字符串（如 "json"），由 dumps_typed 返回
"""
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.dialects.mysql import MEDIUMBLOB, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time_utils import utcnow
from app.models.base import Base


class AgentCheckpoint(Base):
    """LangGraph checkpointer 持久化"""
    __tablename__ = "sys_agent_checkpoint"
    __table_args__ = (
        Index("idx_ckpt_thread_ns_id", "thread_id", "checkpoint_ns", "checkpoint_id", unique=True),
        Index("idx_ckpt_created_at", "created_at"),  # 优化 cleanup_expired() 删除性能
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    checkpoint_ns: Mapped[str] = mapped_column(
        String(256), nullable=False, default="", server_default="",
        comment="检查点命名空间"
    )
    checkpoint_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="语义类型: checkpoint / pending_writes"
    )
    serde_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="serde 序列化类型，如 json"
    )
    checkpoint_json: Mapped[bytes] = mapped_column(MEDIUMBLOB, nullable=False)  # msgpack 二进制序列化
    metadata_json: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=utcnow, server_default=func.now(),
    )
