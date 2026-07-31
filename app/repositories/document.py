"""
文档数据访问层
"""
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.models.document import Document, DocumentChunk


class DocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Document ──

    async def get_by_id(self, doc_id: int) -> Document | None:
        result = await self.db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_kb(
        self, kb_id: int, skip: int = 0, limit: int = 50
    ) -> list[Document]:
        result = await self.db.execute(
            select(Document)
            .where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_kb(self, kb_id: int) -> int:
        result = await self.db.execute(
            select(func.count(Document.id)).where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def total_size_by_kb(self, kb_id: int) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.sum(Document.file_size), 0)).where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def create(self, data: dict) -> Document:
        now = utcnow()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        doc = Document(**data)
        self.db.add(doc)
        await self.db.flush()
        return doc

    async def update(self, doc: Document) -> Document:
        doc.updated_at = utcnow()
        await self.db.flush()
        return doc

    async def soft_delete(self, doc: Document) -> None:
        now = utcnow()
        doc.deleted_at = now
        doc.updated_at = now
        await self.db.flush()

    async def soft_delete_by_kb(self, kb_id: int) -> int:
        """软删除知识库下所有文档，返回受影响行数"""
        now = utcnow()
        result = await self.db.execute(
            update(Document)
            .where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )
        return result.rowcount

    # ── DocumentChunk ──

    async def create_chunks_batch(
        self, chunks_data: list[dict]
    ) -> list[DocumentChunk]:
        """批量创建分块，flush 后返回含 id 的 chunk 列表"""
        chunks = [DocumentChunk(**data) for data in chunks_data]
        self.db.add_all(chunks)
        await self.db.flush()
        return chunks

    async def get_chunks_by_doc(self, doc_id: int) -> list[DocumentChunk]:
        result = await self.db.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == doc_id,
                DocumentChunk.deleted_at.is_(None),
            )
            .order_by(DocumentChunk.chunk_index)
        )
        return list(result.scalars().all())

    async def get_chunk_ids_by_doc(self, doc_id: int) -> list[int]:
        result = await self.db.execute(
            select(DocumentChunk.id).where(
                DocumentChunk.document_id == doc_id,
                DocumentChunk.deleted_at.is_(None),
            )
        )
        return [row[0] for row in result.all()]

    async def count_chunks_by_kb(self, kb_id: int) -> int:
        result = await self.db.execute(
            select(func.count(DocumentChunk.id))
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(
                Document.kb_id == kb_id,
                DocumentChunk.deleted_at.is_(None),
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def soft_delete_chunks_by_doc(self, doc_id: int) -> int:
        """S3: 软删除文档下所有分块"""
        now = utcnow()
        result = await self.db.execute(
            update(DocumentChunk)
            .where(
                DocumentChunk.document_id == doc_id,
                DocumentChunk.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        return result.rowcount

    async def soft_delete_chunks_by_kb(self, kb_id: int) -> int:
        """S3: 软删除知识库下所有分块"""
        now = utcnow()
        # subquery: all document IDs in this KB
        doc_subq = (
            select(Document.id).where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
        ).scalar_subquery()
        result = await self.db.execute(
            update(DocumentChunk)
            .where(
                DocumentChunk.document_id.in_(doc_subq),
                DocumentChunk.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        return result.rowcount
