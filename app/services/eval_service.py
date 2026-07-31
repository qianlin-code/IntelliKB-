"""
RAG 评测服务（Phase 5 P1）

- 自动合成查询集（从文档段落 → LLM 生成问题）
- 执行评测（遍历查询集 → 调检索管线 → 计算指标）
- 指标查询（按 KB 查历史评测结果）

依赖: HybridSearchService.search(kb_id, question, user, top_k, use_rerank, use_cache)
      返回 tuple[list[SearchResult], str | None]
"""
import json
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm_client import get_llm_client

logger = logging.getLogger("app")


class EvalService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm_client, self.llm_model = get_llm_client(purpose="default")

    async def synthesize_queries(self, kb_id: int, count: int = 50) -> int:
        """自动合成评测查询集

        1. 随机抽取 count 个 chunk
        2. 对每个 chunk 用 LLM 生成对应问题
        3. 写入 sys_eval_query
        返回生成的查询数量。
        """
        from sqlalchemy import func
        from app.models.document import Document, DocumentChunk

        # MySQL: func.rand() 是 MySQL 专属随机排序函数
        # 若后续迁移到 PostgreSQL，需改为 func.random()
        # DocumentChunk 通过 document_id 关联 Document.kb_id
        result = await self.db.execute(
            select(DocumentChunk.id, DocumentChunk.content, DocumentChunk.document_id)
            .select_from(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.kb_id == kb_id)
            .order_by(func.rand())
            .limit(count)
        )
        chunks = result.all()

        generated = 0
        from app.models.eval import EvalQuery

        for chunk in chunks:
            try:
                response = await self.llm_client.chat.completions.create(
                    model=self.llm_model,
                    messages=[{
                        "role": "system",
                        "content": (
                            "根据以下文档段落生成一个用户可能提出的问题。"
                            "问题应自然、具体。只返回问题本身，不要引号或额外文字。"
                        ),
                    }, {
                        "role": "user",
                        "content": f"段落内容：{chunk.content[:500]}",
                    }],
                    max_tokens=100,
                    temperature=0.7,
                )
                question = response.choices[0].message.content.strip()

                query = EvalQuery(
                    kb_id=kb_id,
                    question=question,
                    relevant_chunk_ids=json.dumps([chunk.id]),
                    relevant_doc_ids=json.dumps([chunk.document_id]),
                    source="synthetic",
                )
                self.db.add(query)
                generated += 1
            except Exception as e:
                logger.warning("合成 query 失败 chunk=%d: %s", chunk.id, e)
                continue

        await self.db.commit()
        return generated

    async def run_evaluation(self, kb_id: int, top_k: int = 5,
                             provider: str | None = None,
                             rewrite_strategy: str | None = None) -> dict:
        """执行评测

        依赖 HybridSearchService.search() 接口。

        Phase 6: provider 参数用于标记本次评测使用的 LLM（不修改全局配置）。
        Phase 8: rewrite_strategy 参数用于 A/B 对比不同查询重写策略。
        """
        actual_provider = provider or settings.LLM_PROVIDER
        from app.models.eval import EvalQuery, EvalRun, EvalResult
        from app.models.knowledge_base import KnowledgeBase
        from app.services.hybrid_search_service import HybridSearchService
        from app.repositories.user import UserRepository

        result = await self.db.execute(
            select(EvalQuery).where(EvalQuery.kb_id == kb_id)
        )
        queries = result.scalars().all()

        if not queries:
            raise ValueError(f"知识库 {kb_id} 无评测查询，请先执行 synthesize_queries")

        user_repo = UserRepository(self.db)
        kb_result = await self.db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
        kb = kb_result.scalar_one_or_none()
        if kb is None:
            raise ValueError(f"知识库 {kb_id} 不存在")
        user = await user_repo.get_by_id(kb.owner_id)

        hybrid_service = HybridSearchService(self.db)

        run = EvalRun(kb_id=kb_id, query_count=len(queries),
                      provider=actual_provider,
                      rewrite_strategy=rewrite_strategy)
        self.db.add(run)
        await self.db.flush()

        total_rank_sum = 0.0
        hit_count_3 = 0
        hit_count_5 = 0
        relevent_3_sum = 0.0
        relevent_5_sum = 0.0

        for query in queries:
            relevant_docs = set(json.loads(query.relevant_doc_ids))

            t0 = time.perf_counter()
            try:
                results, _ = await hybrid_service.search(
                    kb_id=kb_id,
                    question=query.question,
                    user=user,
                    top_k=top_k,
                    use_rerank=True,
                    use_cache=False,
                )
            except Exception as e:
                logger.warning("评测 search 失败 query=%d: %s", query.id, e)
                results = []
            latency_ms = int((time.perf_counter() - t0) * 1000)

            retrieved_doc_ids = [r.document_id for r in results]

            first_rank = 0
            for i, doc_id in enumerate(retrieved_doc_ids, 1):
                if doc_id in relevant_docs:
                    first_rank = i
                    break

            if first_rank > 0:
                total_rank_sum += 1.0 / first_rank
                if first_rank <= 3:
                    hit_count_3 += 1
                if first_rank <= 5:
                    hit_count_5 += 1

            hits_3 = len(set(retrieved_doc_ids[:3]) & relevant_docs)
            hits_5 = len(set(retrieved_doc_ids[:5]) & relevant_docs)
            relevent_3_sum += hits_3 / max(len(relevant_docs), 1)
            relevent_5_sum += hits_5 / max(len(relevant_docs), 1)

            detail = EvalResult(
                run_id=run.id,
                query_id=query.id,
                rank=first_rank,
                hits_in_top_k=len(set(retrieved_doc_ids[:top_k]) & relevant_docs),
                retrieved_chunk_ids=json.dumps([r.chunk_id for r in results]),
                latency_ms=latency_ms,
            )
            self.db.add(detail)

        n = len(queries)
        run.hit_rate_at_3 = round(hit_count_3 / n, 4) if n > 0 else 0.0
        run.hit_rate_at_5 = round(hit_count_5 / n, 4) if n > 0 else 0.0
        run.mrr = round(total_rank_sum / n, 4) if n > 0 else 0.0
        run.recall_at_3 = round(relevent_3_sum / n, 4) if n > 0 else 0.0
        run.recall_at_5 = round(relevent_5_sum / n, 4) if n > 0 else 0.0

        await self.db.commit()

        return {
            "run_id": run.id,
            "provider": actual_provider,
            "rewrite_strategy": rewrite_strategy,
            "query_count": n,
            "hit_rate@3": run.hit_rate_at_3,
            "hit_rate@5": run.hit_rate_at_5,
            "mrr": run.mrr,
            "recall@3": run.recall_at_3,
            "recall@5": run.recall_at_5,
        }
