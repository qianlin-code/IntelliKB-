"""Phase 6: eval provider column

Revision ID: phase6_001
Revises: phase5_001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase6_001'
down_revision: Union[str, None] = 'phase5_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "sys_eval_run",
        sa.Column("provider", sa.String(20), nullable=False,
                  server_default="ollama",
                  comment="LLM provider: ollama | deepseek"),
    )


def downgrade():
    op.drop_column("sys_eval_run", "provider")
