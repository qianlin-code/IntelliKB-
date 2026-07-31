"""Phase 4: Agent checkpoint table

Revision ID: phase4_001
Revises: phase3_001
Create Date: 2026-07-29 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = 'phase4_001'
down_revision: Union[str, None] = 'phase3_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sys_agent_checkpoint",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("checkpoint_id", sa.String(128), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(128), nullable=True),
        sa.Column("checkpoint_ns", sa.String(256), nullable=False, server_default=""),
        sa.Column("type", sa.String(50), nullable=False,
                  comment="语义类型: checkpoint / pending_writes"),
        sa.Column("serde_type", sa.String(50), nullable=False,
                  comment="serde 序列化类型，如 json"),
        # checkpoint_json 为 msgpack 二进制数据，使用 MEDIUMBLOB（最大 16MB）
        sa.Column("checkpoint_json", mysql.MEDIUMBLOB(), nullable=False),
        # metadata_json 为 JSON 字符串，使用 MEDIUMTEXT
        sa.Column("metadata_json", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    # 唯一索引: (thread_id, checkpoint_ns, checkpoint_id)
    op.create_index(
        "idx_ckpt_thread_ns_id", "sys_agent_checkpoint",
        ["thread_id", "checkpoint_ns", "checkpoint_id"],
        unique=True,
    )
    # 优化 cleanup_expired() 删除性能
    op.create_index(
        "idx_ckpt_created_at", "sys_agent_checkpoint",
        ["created_at"],
    )


def downgrade() -> None:
    # 先删索引，再删表
    op.drop_index("idx_ckpt_thread_ns_id", table_name="sys_agent_checkpoint")
    op.drop_index("idx_ckpt_created_at", table_name="sys_agent_checkpoint")
    op.drop_table("sys_agent_checkpoint")
