"""
RAG 评测数据模型（Phase 5 P1）
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time_utils import utcnow
from app.models.base import Base


class EvalQuery(Base):
    """评测查询集（自动合成或人工标注）"""
    __tablename__ = "sys_eval_query"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_kb.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    relevant_chunk_ids: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON array: [1,2,3]")
    relevant_doc_ids: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON array: [1,2]")
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="synthetic",
        comment="synthetic | manual"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_eval_query_kb", "kb_id"),
    )


class EvalRun(Base):
    """评测执行记录"""
    __tablename__ = "sys_eval_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_kb.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ollama",
        comment="LLM provider: ollama | deepseek"
    )
    rewrite_strategy: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default=None,
        comment="Phase 8: 查询重写策略 A | B | C | null=current"
    )
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="评测配置快照")
    hit_rate_at_3: Mapped[float] = mapped_column(Float, nullable=True)
    hit_rate_at_5: Mapped[float] = mapped_column(Float, nullable=True)
    mrr: Mapped[float] = mapped_column(Float, nullable=True)
    recall_at_3: Mapped[float] = mapped_column(Float, nullable=True)
    recall_at_5: Mapped[float] = mapped_column(Float, nullable=True)
    query_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_eval_run_kb", "kb_id"),
        Index("idx_eval_run_kb_time", "kb_id", "created_at"),
    )


class EvalResult(Base):
    """单条查询的评测明细"""
    __tablename__ = "sys_eval_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_eval_run.id"), nullable=False, index=True)
    query_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_eval_query.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, comment="第一个相关文档的排名，0 表示未命中")
    hits_in_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retrieved_chunk_ids: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON array")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, server_default=func.now(),
    )
