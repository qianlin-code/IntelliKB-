"""Phase 8: eval rewrite_strategy column

Revision ID: phase8_001
Revises: phase6_001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase8_001'
down_revision: Union[str, None] = 'phase6_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "sys_eval_run",
        sa.Column("rewrite_strategy", sa.String(10), nullable=True,
                  comment="Phase 8: 查询重写策略 A | B | C | null=current"),
    )


def downgrade():
    op.drop_column("sys_eval_run", "rewrite_strategy")
