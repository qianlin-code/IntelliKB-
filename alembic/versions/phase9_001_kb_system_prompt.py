"""Phase 9: KB system_prompt + conversation is_pinned/is_starred

Revision ID: phase9_001
Revises: phase8_001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase9_001'
down_revision: Union[str, None] = 'phase8_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # KB 自定义 Agent 人设
    op.add_column(
        "sys_kb",
        sa.Column("system_prompt", sa.Text, nullable=True,
                  comment="Phase 9: 自定义 Agent 系统提示词"),
    )
    # 会话收藏/置顶
    op.add_column(
        "sys_conversation",
        sa.Column("is_pinned", sa.Boolean, nullable=False,
                  server_default="0", comment="Phase 9: 是否置顶"),
    )
    op.add_column(
        "sys_conversation",
        sa.Column("is_starred", sa.Boolean, nullable=False,
                  server_default="0", comment="Phase 9: 是否收藏"),
    )


def downgrade():
    op.drop_column("sys_kb", "system_prompt")
    op.drop_column("sys_conversation", "is_pinned")
    op.drop_column("sys_conversation", "is_starred")
