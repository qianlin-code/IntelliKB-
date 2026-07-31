"""
RAG 服务 —— 检索 + 生成

Phase 4: 使用共享 LLM 客户端工厂 (get_llm_client)。
"""
import asyncio
import json
import logging

import openai

from app.config import settings
from app.core.llm_client import get_llm_client
from app.models.user import User
from app.schemas.qa import SearchResult, AskResponse
from app.services.embedding_service import embedding_service
from app.services.vector_store import vector_store_service
from app.services.kb_service import KBService

logger = logging.getLogger("app")


class RAGService:
    """RAG 检索 + 生成"""

    def __init__(self, db):
        self.db = db
        self.llm_client, self.llm_model = get_llm_client(purpose="default")

    async def search(
        self, kb_id: int, question: str, user: User, top_k: int = 5
    ) -> list[SearchResult]:
        """纯检索：embedding → Chroma 相似度 → 返回 SearchResult 列表"""
        kb_service = KBService(self.db)
        await kb_service.get_accessible(kb_id, user.id)

        query_embedding = await embedding_service.embed(question)
        results = await vector_store_service.search(
            kb_id, query_embedding, top_k,
            score_threshold=settings.SEARCH_SCORE_THRESHOLD,
        )

        return [
            SearchResult(
                chunk_id=r["chunk_id"],
                document_id=r["document_id"],
                content=r["content"],
                score=r["score"],
            )
            for r in results
        ]

    async def ask(
        self, kb_id: int, question: str, user: User, top_k: int = 5,
        conversation_id: int | None = None,
    ) -> AskResponse:
        """RAG 问答：检索 + LLM 生成"""
        sources = await self.search(kb_id, question, user, top_k)

        if not sources:
            answer = "未找到相关文档片段，请尝试更换问题或上传更多文档。"
            await self._persist_qa_messages(conversation_id, question, answer, sources, 0)
            return AskResponse(answer=answer, sources=[], llm_error=False)

        prompt = self._build_prompt(question, sources)

        try:
            response = await self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个智能知识库助手。请根据参考资料回答用户问题。用中文回答。如果参考资料不足以回答问题，请明确说明。回答时引用来源编号。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1024,
            )
            answer = response.choices[0].message.content or ""
            await self._persist_qa_messages(
                conversation_id, question, answer, sources,
                token_count=len(answer) // 2,
            )
            return AskResponse(answer=answer, sources=sources, llm_error=False)

        except (asyncio.TimeoutError, openai.APITimeoutError, openai.APIConnectionError) as e:
            logger.warning("LLM 调用失败（超时/连接），降级返回检索结果: %s", str(e))
            answer = "LLM 服务暂时超时，已返回检索到的相关片段，请自行参考。"
            await self._persist_qa_messages(
                conversation_id, question, answer, sources,
                token_count=len(answer) // 2,
            )
            return AskResponse(answer=answer, sources=sources, llm_error=True)
        except Exception as e:
            logger.warning("LLM 调用失败，降级返回检索结果: %s", str(e))
            answer = "LLM 服务暂时不可用，已返回检索到的相关片段，请自行参考。"
            await self._persist_qa_messages(
                conversation_id, question, answer, sources,
                token_count=len(answer) // 2,
            )
            return AskResponse(answer=answer, sources=sources, llm_error=True)

    @staticmethod
    def _build_prompt(question: str, sources: list[SearchResult]) -> str:
        """构建 RAG prompt 模板，要求 LLM 使用 [source:N] 格式标注引用"""
        context_parts = []
        for i, s in enumerate(sources):
            title = f" (文档:{s.document_id})" if s.document_id else ""
            context_parts.append(f"[来源 {i+1}]{title}\n{s.content}")
        context = "\n\n---\n\n".join(context_parts)

        return f"""参考资料：
{context}

用户问题：{question}

请用中文回答。如果参考资料不足以回答问题，请明确说明。
重要：回答时使用 [source:N] 格式标注引用来源（N 为来源编号）。"""

    async def _persist_qa_messages_background(
        self,
        conversation_id: int | None,
        question: str,
        answer: str,
        sources: list[SearchResult],
        token_count: int,
    ) -> None:
        """后台任务：使用独立 session 持久化 RAG 问答消息。

        StreamingResponse 在客户端断开时会取消当前任务，后台任务使用新的 session
        可以避免取消影响，确保 user/assistant 消息完整保存到数据库。
        """
        if not conversation_id:
            return

        from app.core.database import async_session_factory
        async with async_session_factory() as db:
            try:
                service = RAGService(db)
                await service._persist_qa_messages(
                    conversation_id, question, answer, sources, token_count,
                )
            except Exception as e:
                logger.error("RAG 后台消息持久化失败 conversation=%s: %s", conversation_id, e)

    async def _persist_qa_messages(
        self,
        conversation_id: int | None,
        question: str,
        answer: str,
        sources: list[SearchResult],
        token_count: int,
    ) -> None:
        """将 RAG 问答的 user/assistant 消息持久化到对话中。

        注意：本方法依赖调用方保证 session 事务。流式场景请通过
        `_persist_qa_messages_background` 使用独立 session 调用，避免任务取消导致丢失。
        """
        if not conversation_id:
            return

        from app.repositories.conversation import ConversationRepository
        from app.repositories.message import MessageRepository
        from app.services.conversation_service import ConversationService

        msg_repo = MessageRepository(self.db)
        conv_repo = ConversationRepository(self.db)

        try:
            await msg_repo.create({
                "conversation_id": conversation_id,
                "role": "user",
                "content": question,
                "token_count": len(question) // 2,
            })
            await conv_repo.increment_message_count(conversation_id)

            metadata = {
                "sources": [s.model_dump(mode="json") for s in sources],
            }
            await msg_repo.create({
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": answer,
                "token_count": token_count,
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
            })
            await conv_repo.increment_message_count(conversation_id)

            # 如果标题还是默认的，用问题生成标题
            conv = await conv_repo.get_by_id(conversation_id)
            if conv and conv.title in (None, "", "新对话"):
                conv.title = ConversationService.generate_title(question)
                await conv_repo.update(conv)

            await self.db.commit()
        except Exception as e:
            logger.error("RAG 消息持久化失败 conversation=%s: %s", conversation_id, e)
            try:
                await self.db.rollback()
            except Exception:
                pass

    async def ask_stream(
        self, kb_id: int, question: str, user: User, top_k: int = 5,
        conversation_id: int | None = None,
    ):
        """Phase 2: SSE 流式问答生成器"""
        import asyncio as _asyncio
        import json as _json

        sources = await self.search(kb_id, question, user, top_k)

        sources_data = _json.dumps({
            "sources": [s.model_dump(mode="json") for s in sources],
        }, ensure_ascii=False)
        yield f"event: sources\ndata: {sources_data}\n\n"

        if not sources:
            answer = "未找到相关文档片段，请尝试更换问题。"
            yield f"data: {_json.dumps(answer, ensure_ascii=False)}\n\n"
            yield f'event: done\ndata: {_json.dumps({"total_tokens": 0})}\n\n'
            # 使用后台任务持久化，避免客户端断开后当前任务被取消导致保存失败
            _asyncio.create_task(self._persist_qa_messages_background(
                conversation_id, question, answer, sources, 0,
            ))
            return

        prompt = self._build_prompt(question, sources)

        token_queue: _asyncio.Queue[str | None] = _asyncio.Queue()

        async def _generate_to_queue():
            try:
                stream = await self.llm_client.chat.completions.create(
                    model=self.llm_model,
                    messages=[
                        {"role": "system", "content": "你是一个智能知识库助手。用中文回答。回答时引用来源编号。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=1024,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        await token_queue.put(delta.content)
            except Exception as e:
                logger.warning("LLM stream failed: %s", str(e))
            finally:
                await token_queue.put(None)

        gen_task = _asyncio.create_task(_generate_to_queue())
        token_count = 0
        answer_parts: list[str] = []
        try:
            while True:
                token = await token_queue.get()
                if token is None:
                    break
                token_count += 1
                answer_parts.append(token)
                yield f"data: {_json.dumps(token, ensure_ascii=False)}\n\n"
        finally:
            if not gen_task.done():
                gen_task.cancel()
            answer = "".join(answer_parts)
            try:
                yield f"event: done\ndata: {_json.dumps({'total_tokens': token_count})}\n\n"
            except Exception:
                # 客户端已断开，done 事件发送失败不影响后续持久化
                pass
            # 使用独立后台任务持久化：StreamingResponse 在客户端断开时会取消当前任务，
            # 后台任务使用新的 session，不受取消影响，确保消息完整保存。
            _asyncio.create_task(self._persist_qa_messages_background(
                conversation_id, question, answer, sources,
                token_count=token_count,
            ))
