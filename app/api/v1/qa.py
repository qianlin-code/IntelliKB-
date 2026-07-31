"""
RAG 问答端点
"""
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.response import APIResponse
from app.depends.auth import get_current_user_or_api_key, get_current_user_cookie
from app.models.user import User
from app.schemas.qa import (
    SearchRequest, SearchResponse, AskRequest, AskStreamRequest, AskResponse,
    HybridSearchRequest, HybridSearchResponse,
)
from app.services.rag_service import RAGService
from app.services.hybrid_search_service import HybridSearchService

logger = logging.getLogger("app")
router = APIRouter(prefix="/qa", tags=["RAG 问答"])


# ── Phase 1 端点（保持向后兼容）──

@router.post("/search", summary="向量检索")
async def search_chunks(
    body: SearchRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """纯检索：返回 Top-K 相似文档片段（不含 LLM 生成）"""
    service = RAGService(db)
    results = await service.search(body.kb_id, body.question, current_user, body.top_k)
    return APIResponse.success(data=SearchResponse(results=results).model_dump(mode="json"))


@router.post("/ask", summary="RAG 问答")
async def ask_question(
    body: AskRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """RAG 问答：检索 + LLM 生成。S4: LLM 不可用时降级返回检索结果 + llm_error=true。"""
    service = RAGService(db)
    result = await service.ask(body.kb_id, body.question, current_user, body.top_k)
    return APIResponse.success(data=result.model_dump(mode="json"))


# ── Phase 2: 混合检索 ──

@router.post("/hybrid-search", summary="BM25 + 向量混合检索")
async def hybrid_search(
    body: HybridSearchRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    BM25 + 向量混合检索 → RRF 融合 → [可选] Cross-encoder Rerank。
    支持 Query Rewrite（多轮对话时）+ Redis 缓存。
    """
    service = HybridSearchService(db)
    results, rewritten = await service.search(
        kb_id=body.kb_id,
        question=body.question,
        user=current_user,
        top_k=body.top_k,
        use_rerank=body.use_rerank,
        history=body.history,
    )
    return APIResponse.success(data=HybridSearchResponse(
        results=results,
        rewritten_query=rewritten,
    ).model_dump(mode="json"))


# ── Phase P0: SSE 流式问答（POST + body，解决 URL 长度限制）──

@router.post("/ask-stream", summary="SSE 流式问答")
async def ask_stream(
    request: Request,
    body: AskStreamRequest,
    current_user: User = Depends(get_current_user_cookie),
    db: AsyncSession = Depends(get_db),
):
    """
    Phase P0: POST + JSON body 传参，cookie-based 认证（兼容 EventSource）。
    认证 token 仍可通过 query param / Cookie 传递，业务参数放在 body 中，
    避免长问题超出 URL 长度限制。
    """
    async def event_generator():
        service = RAGService(db)
        try:
            async for sse_frame in service.ask_stream(
                kb_id=body.kb_id, question=body.question,
                user=current_user, top_k=body.top_k,
                conversation_id=body.conversation_id,
            ):
                if await request.is_disconnected():
                    break
                yield sse_frame
        except Exception as e:
            logger.exception("SSE ask-stream error")
            yield f"event: error\ndata: {json.dumps({'code': 'STREAM_ERROR', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
