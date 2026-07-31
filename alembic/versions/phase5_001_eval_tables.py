"""Phase 5: RAG 评测表

Revision ID: phase5_001
Revises: phase4_001
Create Date: 2026-07-29 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase5_001'
down_revision: Union[str, None] = 'phase4_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 评测查询集
    op.create_table(
        "sys_eval_query",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kb_id", sa.Integer(), sa.ForeignKey("sys_kb.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("relevant_chunk_ids", sa.Text(), nullable=False, comment="JSON array"),
        sa.Column("relevant_doc_ids", sa.Text(), nullable=False, comment="JSON array"),
        sa.Column("source", sa.String(20), nullable=False, server_default="synthetic"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_eval_query_kb", "sys_eval_query", ["kb_id"])

    # 评测执行记录
    op.create_table(
        "sys_eval_run",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kb_id", sa.Integer(), sa.ForeignKey("sys_kb.id"), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=True, comment="评测配置快照"),
        sa.Column("hit_rate_at_3", sa.Float(), nullable=True),
        sa.Column("hit_rate_at_5", sa.Float(), nullable=True),
        sa.Column("mrr", sa.Float(), nullable=True),
        sa.Column("recall_at_3", sa.Float(), nullable=True),
        sa.Column("recall_at_5", sa.Float(), nullable=True),
        sa.Column("query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_eval_run_kb", "sys_eval_run", ["kb_id"])
    op.create_index("idx_eval_run_kb_time", "sys_eval_run", ["kb_id", "created_at"])

    # 评测明细
    op.create_table(
        "sys_eval_result",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("sys_eval_run.id"), nullable=False),
        sa.Column("query_id", sa.Integer(), sa.ForeignKey("sys_eval_query.id"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, comment="第一个相关文档的排名，0=未命中"),
        sa.Column("hits_in_top_k", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieved_chunk_ids", sa.Text(), nullable=False, comment="JSON array"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_eval_result_run", "sys_eval_result", ["run_id"])


def downgrade():
    op.drop_table("sys_eval_result")
    op.drop_table("sys_eval_run")
    op.drop_table("sys_eval_query")
