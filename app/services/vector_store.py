"""
向量存储服务 —— ChromaDB 封装

实现细节 #2：所有 Chroma PersistentClient 的同步操作通过 asyncio.to_thread() 包装。
"""
import asyncio
import logging
from typing import Any

import chromadb
from chromadb.api.types import Embedding as ChromaEmbedding

from app.config import settings

logger = logging.getLogger("app")


class VectorStoreService:
    """ChromaDB 向量存储，每知识库独立 Collection（kb_{kb_id}）"""

    def __init__(self):
        self._client: chromadb.PersistentClient | None = None
        self._persist_dir = settings.CHROMA_PERSIST_DIR

    @property
    def client(self) -> chromadb.PersistentClient:
        if self._client is None:
            self._client = chromadb.PersistentClient(path=self._persist_dir)
        return self._client

    @staticmethod
    def _collection_name(kb_id: int) -> str:
        return f"kb_{kb_id}"

    def _get_or_create_sync(self, kb_id: int):
        """同步方法：获取或创建 Collection"""
        return self.client.get_or_create_collection(
            name=self._collection_name(kb_id),
            metadata={"hnsw:space": "cosine"},
        )

    async def get_or_create_collection(self, kb_id: int):
        """异步包装"""
        return await asyncio.to_thread(self._get_or_create_sync, kb_id)

    async def add_chunks(
        self,
        kb_id: int,
        chunk_ids: list[int],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """批量写入向量（M4: metadatas 含 document_id + filename）"""
        collection = await self.get_or_create_collection(kb_id)
        await asyncio.to_thread(
            collection.add,
            ids=[str(cid) for cid in chunk_ids],
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info(
            "Chroma 写入 %d 条向量 → collection=%s",
            len(chunk_ids),
            self._collection_name(kb_id),
        )

    async def search(
        self,
        kb_id: int,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        向量相似度检索。

        返回:
            [{chunk_id, document_id, content, score}, ...]

        score_threshold: 若提供，则过滤掉 score 低于阈值的结果。
        阈值基于 cosine similarity（1 - distance），范围 [0, 1]。
        """
        try:
            collection = self.client.get_collection(self._collection_name(kb_id))
        except Exception:
            logger.warning("Collection kb_%d 不存在，返回空结果", kb_id)
            return []

        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        # Chroma 返回: {ids: [[...]], documents: [[...]], metadatas: [[...]], distances: [[...]]}
        items: list[dict[str, Any]] = []
        if not results["ids"] or not results["ids"][0]:
            return items

        ids = results["ids"][0]
        docs = results.get("documents", [[""]])[0]
        metas = results.get("metadatas", [[{}]])[0]
        distances = results.get("distances", [[0.0]])[0]

        threshold = score_threshold if score_threshold is not None else 0.0

        for i, chunk_id_str in enumerate(ids):
            # cosine distance → similarity score: 1 - distance
            score = 1.0 - distances[i] if i < len(distances) else 0.0
            if score < threshold:
                continue
            meta = metas[i] if i < len(metas) else {}
            items.append({
                "chunk_id": int(chunk_id_str),
                "document_id": meta.get("document_id", 0),
                "content": docs[i] if i < len(docs) else "",
                "score": round(score, 4),
            })

        return items

    async def delete_chunks(self, kb_id: int, chunk_ids: list[int]) -> None:
        """删除指定 chunk 向量"""
        try:
            collection = self.client.get_collection(self._collection_name(kb_id))
        except Exception:
            return
        await asyncio.to_thread(
            collection.delete,
            ids=[str(cid) for cid in chunk_ids],
        )
        logger.info("Chroma 删除 %d 条向量 ← collection=%s", len(chunk_ids), self._collection_name(kb_id))

    async def delete_collection(self, kb_id: int) -> None:
        """删除知识库 Collection（删除 KB 时调用）"""
        await asyncio.to_thread(
            self.client.delete_collection,
            self._collection_name(kb_id),
        )
        logger.info("Chroma 删除 Collection: %s", self._collection_name(kb_id))


# 模块级单例
vector_store_service = VectorStoreService()
