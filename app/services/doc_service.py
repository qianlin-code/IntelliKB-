"""
文档服务 —— 上传、解析、分块、向量化全生命周期

实现细节 #3（事务保护）：整个流程在同一 session 中完成；
任何步骤失败时 Document.status='error' + error_message 写入。
"""
import io
import logging
import zipfile

from fastapi import UploadFile
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BusinessError
from app.models.document import Document, DocumentChunk
from app.repositories.document import DocumentRepository
from app.repositories.knowledge_base import KBRepository
from app.services.embedding_service import embedding_service
from app.services.vector_store import vector_store_service
from app.services.progress_manager import progress_manager
from app.services.bm25_service import bm25_service
from app.services.rag_cache_service import rag_cache_service
from app.services.progress_pubsub import progress_pubsub

logger = logging.getLogger("app")

SUPPORTED_EXTENSIONS = {"pdf", "docx", "md", "txt"}

# MIME → 扩展名映射
MIME_TO_EXT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/markdown": "md",
    "text/plain": "txt",
    "text/html": "txt",
}


class DocService:
    """文档生命周期管理"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.doc_repo = DocumentRepository(db)
        self.kb_repo = KBRepository(db)

    # ── 公开 API ──

    async def upload_and_process(
        self, kb_id: int, file: UploadFile, user_id: int
    ) -> Document:
        """完整流程：校验 → 解析 → 分块 → 嵌入 → 存储"""
        # 0. 校验知识库存在且 user 是 owner
        kb = await self.kb_repo.get_by_id(kb_id)
        if kb is None:
            raise BusinessError("知识库不存在")
        if kb.owner_id != user_id:
            raise BusinessError("仅知识库所有者可上传文档")

        filename = file.filename or "unknown"
        file_ext = self._get_extension(filename)
        content = await file.read()

        # 1. 校验文件大小
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(content) > max_bytes:
            raise BusinessError(
                f"文件大小 {len(content) / 1024 / 1024:.1f}MB 超过限制 {settings.MAX_UPLOAD_SIZE_MB}MB"
            )

        # 2. 校验文件类型
        if file_ext not in SUPPORTED_EXTENSIONS:
            raise BusinessError(f"不支持的文件类型: .{file_ext}，支持: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

        # 3. M1: 魔数校验
        self._validate_file_magic(file_ext, content)

        # 4. 创建 Document 记录
        doc = await self.doc_repo.create({
            "kb_id": kb_id,
            "filename": filename,
            "file_type": file_ext,
            "file_size": len(content),
            "status": "parsing",
        })
        logger.info("文档记录创建 id=%d filename=%s", doc.id, filename)

        try:
            # 5. 提取文本
            text = await self._extract_text(file_ext, content)
            if not text or not text.strip():
                raise BusinessError("文档内容为空，无法解析")

            # 6. 分块
            doc.status = "chunking"
            await self.doc_repo.update(doc)
            chunk_texts = self._split_chunks(
                text,
                chunk_size=kb.chunk_size,
                chunk_overlap=kb.chunk_overlap,
            )
            if not chunk_texts:
                raise BusinessError("文档分块结果为空")

            # 7. 写入 sys_chunk 表
            doc.status = "indexing"
            await self.doc_repo.update(doc)
            chunks_data = [
                {
                    "document_id": doc.id,
                    "chunk_index": i,
                    "content": ct,
                    "token_count": len(ct) // 2,  # 粗略估算：中文 ~2 chars/token
                }
                for i, ct in enumerate(chunk_texts)
            ]
            chunks: list[DocumentChunk] = await self.doc_repo.create_chunks_batch(chunks_data)
            logger.info("写入 %d 条 chunk (doc_id=%d)", len(chunks), doc.id)

            # 8. 批量生成 embeddings（实现细节 #1: batch_size=32）
            embeddings = await embedding_service.embed_batch(
                [c.content for c in chunks], batch_size=32
            )

            # 9. 写入 Chroma 向量库（M4: metadata 含 document_id + filename）
            await vector_store_service.add_chunks(
                kb_id=kb_id,
                chunk_ids=[c.id for c in chunks],
                embeddings=embeddings,
                documents=[c.content for c in chunks],
                metadatas=[
                    {"document_id": doc.id, "filename": filename, "chunk_index": c.chunk_index}
                    for c in chunks
                ],
            )

            # 10. 标记完成
            doc.status = "done"
            doc.chunk_count = len(chunks)
            await self.doc_repo.update(doc)
            logger.info("文档处理完成 id=%d chunks=%d", doc.id, len(chunks))

        except Exception as e:
            # 实现细节 #3: 事务保护 — 异常时记录错误，不残留
            doc.status = "error"
            doc.error_message = f"{type(e).__name__}: {str(e)}"
            await self.doc_repo.update(doc)
            logger.exception("文档处理失败 id=%d", doc.id)
            raise

        return doc

    async def delete_document(self, doc_id: int, user_id: int) -> None:
        """删除文档 + 清理向量 + S3 三层软删除"""
        doc = await self.doc_repo.get_by_id(doc_id)
        if doc is None:
            raise BusinessError("文档不存在")

        kb = await self.kb_repo.get_by_id(doc.kb_id)
        if kb is None or kb.owner_id != user_id:
            raise BusinessError("仅知识库所有者可删除文档")

        # 1. 清理向量
        chunk_ids = await self.doc_repo.get_chunk_ids_by_doc(doc_id)
        if chunk_ids:
            await vector_store_service.delete_chunks(doc.kb_id, chunk_ids)

        # 2. S3: 软删除所有 chunk
        await self.doc_repo.soft_delete_chunks_by_doc(doc_id)

        # 3. 软删除文档
        await self.doc_repo.soft_delete(doc)
        logger.info("文档已删除 id=%d chunks=%d", doc.id, len(chunk_ids))

        # O4: 异步失效缓存 + BM25 索引
        import asyncio as _asyncio
        _asyncio.create_task(rag_cache_service.invalidate(doc.kb_id))
        bm25_service.invalidate(doc.kb_id)

    # ── Phase 2: 异步解析 ──

    async def create_document_record(
        self, kb_id: int, file: UploadFile, user_id: int,
    ) -> Document:
        """Phase 2: 创建文档记录（status='uploading'），不解析。返回 Document 供 bg.add_task 使用。"""
        kb = await self.kb_repo.get_by_id(kb_id)
        if kb is None:
            raise BusinessError("知识库不存在")

        # Phase 2: 校验 owner 或 editor 权限
        from app.repositories.kb_member import KBMemberRepository
        member_repo = KBMemberRepository(self.db)
        if kb.owner_id != user_id:
            member = await member_repo.get_by_kb_and_user(kb_id, user_id)
            if member is None or member.role not in ("owner", "editor"):
                raise BusinessError("仅知识库所有者或编辑者可上传文档")

        filename = file.filename or "unknown"
        file_ext = self._get_extension(filename)
        content = await file.read()

        # 校验文件大小
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(content) > max_bytes:
            raise BusinessError(
                f"文件大小 {len(content) / 1024 / 1024:.1f}MB 超过限制 {settings.MAX_UPLOAD_SIZE_MB}MB"
            )

        # 校验文件类型
        if file_ext not in SUPPORTED_EXTENSIONS:
            raise BusinessError(f"不支持的文件类型: .{file_ext}")

        # M1: 魔数校验
        self._validate_file_magic(file_ext, content)

        # 保存文件到磁盘
        import os as _os
        _os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        file_path = _os.path.join(settings.UPLOAD_DIR, f"{kb_id}_{user_id}_{filename}")
        with open(file_path, "wb") as f:
            f.write(content)

        # 创建记录
        doc = await self.doc_repo.create({
            "kb_id": kb_id,
            "filename": filename,
            "file_type": file_ext,
            "file_size": len(content),
            "status": "uploading",
        })
        # 存储文件路径到 error_message 字段（临时方案，后续可加 file_path 列）
        doc.error_message = file_path  # 临时存储路径
        await self.doc_repo.update(doc)

        logger.info("文档记录创建（异步）id=%d filename=%s", doc.id, filename)
        return doc

    @staticmethod
    async def parse_document_async_static(doc_id: int) -> None:
        """
        BackgroundTasks 兼容的静态入口：独立 session，每阶段详细日志。
        """
        logger.info("[parse_document_async_static] START doc_id=%d", doc_id)

        from app.core.database import async_session_factory

        db = async_session_factory()
        try:
            logger.info("[parse_document_async] session acquired doc_id=%d", doc_id)

            doc_repo = DocumentRepository(db)
            kb_repo = KBRepository(db)

            doc = await doc_repo.get_by_id(doc_id)
            if doc is None:
                logger.error("[parse_document_async] doc_id=%d not found", doc_id)
                await db.close()
                return

            # 获取 KB 配置
            kb = await kb_repo.get_by_id(doc.kb_id)
            if kb is None:
                raise BusinessError("知识库不存在")

            # 读取文件内容
            file_path = doc.error_message
            logger.info("[parse_document_async] file_path=%s doc_id=%d", file_path, doc_id)
            if not file_path or not file_path.startswith(settings.UPLOAD_DIR):
                raise BusinessError(f"文件路径无效: {file_path}")

            import os as _os
            if not _os.path.exists(file_path):
                raise BusinessError(f"文件已被删除: {file_path}")

            with open(file_path, "rb") as f:
                content = f.read()
            logger.info("[parse_document_async] file read, size=%d doc_id=%d", len(content), doc_id)

            # uploading → parsing
            doc.status = "parsing"
            await doc_repo.update(doc)
            await progress_manager.set(doc_id, "parsing", 0.25, "正在提取文本...")
            await progress_pubsub.publish(doc_id, "parsing", 0.25, "正在提取文本...")
            logger.info("[parse_document_async] parsing doc_id=%d", doc_id)

            text = await DocService._extract_text(doc.file_type, content)
            if not text or not text.strip():
                raise BusinessError("文档内容为空，无法解析")
            logger.info("[parse_document_async] text extracted, len=%d doc_id=%d", len(text), doc_id)

            # parsing → chunking
            doc.status = "chunking"
            await doc_repo.update(doc)
            await progress_manager.set(doc_id, "chunking", 0.50, "正在分块...")
            await progress_pubsub.publish(doc_id, "chunking", 0.50, "正在分块...")
            logger.info("[parse_document_async] chunking doc_id=%d", doc_id)

            chunks_text = DocService._split_chunks(text, kb.chunk_size, kb.chunk_overlap)
            if not chunks_text:
                raise BusinessError("文档分块结果为空")
            logger.info("[parse_document_async] chunks=%d doc_id=%d", len(chunks_text), doc_id)

            # chunking → indexing
            doc.status = "indexing"
            await doc_repo.update(doc)
            await progress_manager.set(
                doc_id, "indexing", 0.75,
                f"已分 {len(chunks_text)} 块，正在生成向量...",
            )
            await progress_pubsub.publish(doc_id, "indexing", 0.75, f"已分 {len(chunks_text)} 块，正在生成向量...")
            logger.info("[parse_document_async] indexing doc_id=%d", doc_id)

            chunks_data = [
                {"document_id": doc.id, "chunk_index": i, "content": ct, "token_count": len(ct) // 2}
                for i, ct in enumerate(chunks_text)
            ]
            chunks: list[DocumentChunk] = await doc_repo.create_chunks_batch(chunks_data)
            logger.info("[parse_document_async] chunks written doc_id=%d", doc_id)

            # 生成 embeddings
            embeddings = await embedding_service.embed_batch(
                [c.content for c in chunks], batch_size=32
            )
            logger.info("[parse_document_async] embeddings done doc_id=%d", doc_id)

            # 写入 Chroma
            await vector_store_service.add_chunks(
                kb_id=doc.kb_id,
                chunk_ids=[c.id for c in chunks],
                embeddings=embeddings,
                documents=[c.content for c in chunks],
                metadatas=[
                    {"document_id": doc.id, "filename": doc.filename, "chunk_index": c.chunk_index}
                    for c in chunks
                ],
            )
            logger.info("[parse_document_async] chroma write done doc_id=%d", doc_id)

            # done
            doc.status = "done"
            doc.chunk_count = len(chunks)
            doc.error_message = None
            await doc_repo.update(doc)
            await progress_manager.set(doc_id, "done", 1.0, f"完成，共 {len(chunks)} 块")
            await progress_pubsub.publish_complete(doc_id, len(chunks))

            # O4: 异步失效缓存 + BM25
            import asyncio as _asyncio
            _asyncio.create_task(rag_cache_service.invalidate(doc.kb_id))
            bm25_service.invalidate(doc.kb_id)

            # Step 4 fix: 显式 commit（async_sessionmaker auto-rollback on close）
            await db.commit()
            logger.info("[parse_document_async] COMMITTED doc_id=%d chunks=%d", doc.id, len(chunks))

        except Exception as e:
            logger.exception("[parse_document_async] FAILED doc_id=%d: %s", doc_id, str(e))
            await db.rollback()
            # 尝试用独立 session 标记为 error
            try:
                async with async_session_factory() as err_db:
                    err_doc_repo = DocumentRepository(err_db)
                    err_doc = await err_doc_repo.get_by_id(doc_id)
                    if err_doc:
                        err_doc.status = "error"
                        err_doc.error_message = f"{type(e).__name__}: {str(e)}"
                        await err_doc_repo.update(err_doc)
                    await progress_manager.set(doc_id, "error", 0.0, f"解析失败: {str(e)}")
                    await progress_pubsub.publish_error(doc_id, str(e))
                    await err_db.commit()
            except Exception as e2:
                logger.exception("[parse_document_async] error handler also failed: %s", str(e2))
        finally:
            await db.close()

    # ── 私有方法 ──

    @staticmethod
    def _get_extension(filename: str) -> str:
        """从文件名提取扩展名（小写、去点）"""
        if "." not in filename:
            return ""
        return filename.rsplit(".", 1)[-1].lower()

    def _validate_file_magic(self, file_ext: str, content: bytes) -> None:
        """
        M1: 文件魔数校验，防止扩展名伪装。

        校验失败抛出 BusinessError("文件格式异常或已损坏")。
        """
        if file_ext == "pdf":
            if not content.startswith(b"%PDF"):
                raise BusinessError("文件格式异常或已损坏：PDF 文件头无效")
        elif file_ext == "docx":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    if "[Content_Types].xml" not in zf.namelist():
                        raise BusinessError("文件格式异常或已损坏：DOCX 缺少必要文件")
            except zipfile.BadZipFile:
                raise BusinessError("文件格式异常或已损坏：DOCX 不是有效 ZIP 文件")
        elif file_ext in ("txt", "md"):
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                raise BusinessError("文件格式异常或已损坏：TXT/MD 无法以 UTF-8 解码")

    @staticmethod
    async def _extract_text(file_ext: str, content: bytes) -> str:
        """按文件类型异步提取文本"""
        import asyncio

        if file_ext == "pdf":
            # Phase 8 P2.1: PDF 提取已包含 OCR 回退，直接 await
            return await DocService._extract_pdf(content)
        elif file_ext == "docx":
            return await asyncio.to_thread(DocService._extract_docx, content)
        else:
            # md / txt
            return content.decode("utf-8")

    @classmethod
    async def _extract_pdf(cls, content: bytes) -> str:
        """Phase 8 P2.1: pdfplumber 提取 PDF 文本 + OCR 图片页回退"""
        return await cls._extract_pdf_with_ocr(content)

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        """python-docx 提取 DOCX 文本"""
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

    @staticmethod
    def _extract_image_text(image_bytes: bytes) -> str:
        """Phase 8 P2.1: OCR 图片文字提取。

        根据 OCR_ENGINE 配置选择引擎：
        - paddleocr: PaddleOCR（推荐，中英混合，无需系统依赖）
        - tesseract: pytesseract（需安装 Tesseract 系统包）

        返回提取的文字，失败返回空字符串。
        """
        if not settings.OCR_ENABLED:
            return ""

        engine = settings.OCR_ENGINE
        try:
            if engine == "paddleocr":
                from paddleocr import PaddleOCR
                import numpy as np
                from PIL import Image

                ocr = PaddleOCR(lang=settings.OCR_LANGUAGE, show_log=False)
                image = Image.open(io.BytesIO(image_bytes))
                img_array = np.array(image)
                result = ocr.ocr(img_array)
                if result and result[0]:
                    lines = [line[1][0] for line in result[0]]
                    return "\n".join(lines)
                return ""

            elif engine == "tesseract":
                import pytesseract
                from PIL import Image

                image = Image.open(io.BytesIO(image_bytes))
                lang = "chi_sim+eng" if settings.OCR_LANGUAGE == "ch" else settings.OCR_LANGUAGE
                text = pytesseract.image_to_string(image, lang=lang)
                return text.strip()

        except ImportError as e:
            logger.warning("OCR engine '%s' not installed: %s. Install: pip install %s",
                           engine, e, engine)
            return ""
        except Exception as e:
            logger.warning("OCR extraction failed: %s", e)
            return ""

    @classmethod
    async def _extract_pdf_with_ocr(cls, content: bytes) -> str:
        """Phase 8 P2.1: PDF 文本提取 + OCR 图片页回退。

        先尝试 pdfplumber 提取文本；若页面无文字，则渲染为图片后 OCR。
        """
        import asyncio
        import pdfplumber

        texts: list[str] = []
        needs_ocr_pages: list[int] = []

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text()
                if t and t.strip():
                    texts.append(t)
                else:
                    needs_ocr_pages.append(i)

        # OCR 扫描页
        if needs_ocr_pages and settings.OCR_ENABLED:
            logger.info("PDF has %d pages without text, attempting OCR", len(needs_ocr_pages))
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(stream=content, filetype="pdf")
                for page_idx in needs_ocr_pages:
                    page = doc[page_idx]
                    pix = page.get_pixmap(dpi=200)
                    img_bytes = pix.tobytes("png")
                    ocr_text = cls._extract_image_text(img_bytes)
                    if ocr_text:
                        texts.insert(page_idx, ocr_text) if page_idx < len(texts) else texts.append(ocr_text)
                doc.close()
            except ImportError:
                logger.warning("PyMuPDF not installed, skipping image-based OCR for PDF pages")
            except Exception as e:
                logger.warning("PDF OCR failed: %s", e)

        return "\n\n".join(texts)

    @classmethod
    def _split_chunks(
        cls,
        text: str, chunk_size: int = 500, chunk_overlap: int = 50,
        strategy: str | None = None,
    ) -> list[str]:
        """分块入口：根据 CHUNKING_STRATEGY 分发到不同策略。

        Phase 8: 支持 fixed（RecursiveCharacterTextSplitter）和 semantic（按标题/段落）。
        """
        strategy = strategy or settings.CHUNKING_STRATEGY
        if strategy == "semantic":
            return cls._split_chunks_semantic(text, chunk_size, chunk_overlap)
        # 默认: fixed（向后兼容）
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " ", ""],
            length_function=len,
        )
        return splitter.split_text(text)

    @staticmethod
    def _split_chunks_semantic(
        text: str, max_chunk_size: int = 500, overlap: int = 50,
    ) -> list[str]:
        """Phase 8: 语义分块 —— 按 Markdown 标题 → 空行 → 句子边界切分。

        优先级：
        1. Markdown 标题（# ## ### ####）分割为节
        2. 节内按空行（\\n\\n+）分割为段落
        3. 段落超过 max_chunk_size 时按句子边界（。；！？. ; ! ?）切分
        4. 过短的 chunk 与相邻 chunk 合并

        返回的每个 chunk 长度不超过 max_chunk_size（容忍 20% 超出）。
        """
        import re

        if not text or not text.strip():
            return []

        # Step 1: 按 Markdown 标题分割
        # 匹配行首的 # 标题（保留标题文本在 chunk 中）
        sections = re.split(r'\n(?=#{1,4}\s)', text)
        # 过滤空 sections
        sections = [s.strip() for s in sections if s.strip()]

        # Step 2: 每节按空行分割为段落
        all_paragraphs: list[str] = []
        for section in sections:
            paragraphs = re.split(r'\n\s*\n', section)
            for p in paragraphs:
                p = p.strip()
                if p:
                    all_paragraphs.append(p)

        # Step 3: 段落超长时按句子拆分
        max_len = max_chunk_size
        chunks: list[str] = []
        for para in all_paragraphs:
            if len(para) <= max_len * 1.2:  # 容忍 20% 超出
                chunks.append(para)
            else:
                # 按句子边界拆分
                sentences = re.split(r'(?<=[。；！？.!;?])\s*', para)
                current = ""
                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    if len(current) + len(sent) <= max_len:
                        current += sent
                    else:
                        if current.strip():
                            chunks.append(current.strip())
                        # 单句超长：强制截断
                        if len(sent) > max_len * 1.2:
                            for i in range(0, len(sent), max_len - overlap):
                                chunks.append(sent[i:i + max_len])
                        else:
                            current = sent
                if current.strip():
                    chunks.append(current.strip())

        # Step 4: 合并过短的 chunk
        min_len = max(50, max_chunk_size // 4)
        merged: list[str] = []
        for chunk in chunks:
            if merged and len(merged[-1]) < min_len:
                merged[-1] = merged[-1] + "\n" + chunk
            else:
                merged.append(chunk)

        # 再次检查合并后是否超长
        final: list[str] = []
        for chunk in merged:
            if len(chunk) > max_len * 1.5:
                # 按句子再拆一次
                sentences = re.split(r'(?<=[。；！？.!;?])\s*', chunk)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) <= max_len:
                        current += sent
                    else:
                        if current.strip():
                            final.append(current.strip())
                        current = sent
                if current.strip():
                    final.append(current.strip())
            else:
                final.append(chunk)

        return final if final else [text[:max_len]]
