"""Phase 10: RBAC + Audit Log + System Config + API Key extension

Revision ID: phase10_001
Revises: phase9_001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase10_001'
down_revision: Union[str, None] = 'phase9_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # ── user.system_role ──
    op.add_column(
        "sys_user",
        sa.Column("system_role", sa.String(20), nullable=False,
                  server_default="user",
                  comment="系统角色: superadmin | admin | user"),
    )
    # ── user API Key 扩展 ──
    op.add_column(
        "sys_user",
        sa.Column("api_key_name", sa.String(100), nullable=True,
                  server_default=sa.text("'default'"),
                  comment="Key 名称/用途"),
    )
    op.add_column(
        "sys_user",
        sa.Column("api_key_monthly_quota", sa.Integer, nullable=False,
                  server_default="0",
                  comment="月 token 配额，0=无限制"),
    )

    # ── sys_audit_log ──
    op.create_table(
        "sys_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=True),
        sa.Column("action", sa.String(50), nullable=False, index=True),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.Integer, nullable=True),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.func.now()),
    )

    # ── sys_config ──
    op.create_table(
        "sys_config",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(100), unique=True, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("description", sa.String(500), default=""),
        sa.Column("updated_by", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade():
    op.drop_column("sys_user", "system_role")
    op.drop_column("sys_user", "api_key_name")
    op.drop_column("sys_user", "api_key_monthly_quota")
    op.drop_table("sys_audit_log")
    op.drop_table("sys_config")
