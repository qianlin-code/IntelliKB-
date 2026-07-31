"""
文档 + 文档分块模型
"""
from sqlalchemy import Integer, String, Text, Enum, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class Document(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "sys_document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="所属知识库 ID")
    filename: Mapped[str] = mapped_column(String(500), nullable=False, comment="原始文件名")
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="文件类型: pdf/docx/md/txt")
    file_size: Mapped[int] = mapped_column(Integer, default=0, comment="文件大小（字节）")
    status: Mapped[str] = mapped_column(
        String(20), default="uploading",
        comment="处理状态: uploading/parsing/chunking/indexing/done/error"
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, comment="分块数量")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")


class DocumentChunk(Base, SoftDeleteMixin):
    """S3: chunk 与 Document 同步软删除，无 ON DELETE CASCADE"""
    __tablename__ = "sys_chunk"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="所属文档 ID")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="分块序号（从 0 开始）")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="分块文本内容")
    token_count: Mapped[int] = mapped_column(Integer, default=0, comment="Token 数量估算")
