"""Phase 3: 对话 + 消息表

Revision ID: phase3_001
Revises: df17e0a41ea1
Create Date: 2026-07-29 02:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase3_001'
down_revision: Union[str, None] = 'df17e0a41ea1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # sys_conversation 表
    op.create_table('sys_conversation',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('kb_id', sa.Integer(), nullable=False, comment='知识库 ID'),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户 ID'),
        sa.Column('title', sa.String(length=200), nullable=True, comment='对话标题'),
        sa.Column('message_count', sa.Integer(), nullable=False, server_default='0', comment='消息总数'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True, comment='删除时间'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_conv_kb_user', 'sys_conversation', ['kb_id', 'user_id'])
    op.create_index('idx_conv_user', 'sys_conversation', ['user_id'])

    # sys_message 表
    op.create_table('sys_message',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False, comment='对话 ID'),
        sa.Column('role', sa.String(length=20), nullable=False, comment='角色: user/assistant/system/tool_call/tool_result'),
        sa.Column('content', sa.Text(), nullable=False, comment='消息内容'),
        sa.Column('metadata_json', sa.Text(), nullable=True, comment='元数据 JSON'),
        sa.Column('token_count', sa.Integer(), nullable=False, server_default='0', comment='token 估算数'),
        sa.Column('tool_call_id', sa.String(length=100), nullable=True, comment='工具调用 ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_msg_conv', 'sys_message', ['conversation_id'])
    op.create_index('idx_msg_conv_id', 'sys_message', ['conversation_id', 'id'])


def downgrade() -> None:
    op.drop_table('sys_message')
    op.drop_table('sys_conversation')
