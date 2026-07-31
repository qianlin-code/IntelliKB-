"""phase2: sys_kb_member table

Revision ID: df17e0a41ea1
Revises: 68834020afef
Create Date: 2026-07-29 01:36:24.640611
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'df17e0a41ea1'
down_revision: Union[str, None] = '68834020afef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('sys_kb_member',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('kb_id', sa.Integer(), nullable=False, comment='知识库 ID'),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户 ID'),
        sa.Column('role', sa.String(length=20), nullable=False, comment='角色: owner / editor / viewer'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kb_id', 'user_id', name='idx_kbm_kb_user'),
    )
    op.create_index('idx_kbm_user', 'sys_kb_member', ['user_id'])
    op.create_foreign_key('fk_kbm_kb', 'sys_kb_member', 'sys_kb', ['kb_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_kbm_user', 'sys_kb_member', 'sys_user', ['user_id'], ['id'], ondelete='CASCADE')

    # Data migration: 为已有 KB 的 owner 创建 KBMember 记录
    op.execute("""
        INSERT INTO sys_kb_member (kb_id, user_id, role, created_at, updated_at)
        SELECT id, owner_id, 'owner', NOW(), NOW()
        FROM sys_kb
        WHERE deleted_at IS NULL
    """)


def downgrade() -> None:
    # M4: 先清理 data migration 创建的 owner 记录，再删表
    op.execute("""
        DELETE FROM sys_kb_member
        WHERE role = 'owner'
        AND (kb_id, user_id) IN (
            SELECT id, owner_id FROM sys_kb WHERE deleted_at IS NULL
        )
    """)
    op.drop_table('sys_kb_member')
