"""
Agent 对话 API

POST /agent/chat       — 非流式对话
POST /agent/chat-stream — SSE 流式对话（兼容 EventSource）
GET /agent/cost        — 云端 LLM 成本统计

Phase 4: SSE 端点注入 BackgroundTasks 用于异步语义标题更新。
Phase 6: 新增 cost 和 llm-provider 端点。
"""
import json
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.response import APIResponse, make_trace_id
from app.depends.auth import get_current_user_cookie, get_current_user_or_api_key
from app.models.user import User
from app.schemas.agent import AgentChatRequest, AgentChatStreamRequest, AgentChatResponse
from app.services.agent_service import AgentService

logger = logging.getLogger("app")
router = APIRouter(prefix="/agent", tags=["Agent 对话"])


@router.post("/chat", summary="Agent 对话（非流式）")
async def agent_chat(
    request: Request,
    body: AgentChatRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Agent 对话（非流式）：含工具调用和引用来源"""
    trace_id = make_trace_id()
    service = AgentService(db)
    result = await service.chat(
        kb_id=body.kb_id,
        question=body.question,
        user_id=current_user.id,
        conv_id=body.conversation_id,
    )
    return APIResponse.success(data=result.model_dump(mode="json"), trace_id=trace_id)


@router.post("/chat-stream", summary="Agent 对话（流式 SSE）")
async def agent_chat_stream(
    request: Request,
    body: AgentChatStreamRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: User = Depends(get_current_user_cookie),
    db: AsyncSession = Depends(get_db),
):
    """
    Agent SSE 流式对话（兼容 EventSource）。

    Phase P0: POST + JSON body 传参，认证 token 仍通过 query param / Cookie 传递。
    事件序列: thought → tool_call → tool_result → sources → token... → done
    Phase 4: 对话标题在 done 事件后通过 BackgroundTasks 异步生成。
    """
    async def event_generator():
        service = AgentService(db)
        try:
            async for sse_frame in service.chat_stream(
                kb_id=body.kb_id,
                question=body.question,
                user_id=current_user.id,
                conv_id=body.conversation_id,
                background_tasks=background_tasks,
            ):
                if await request.is_disconnected():
                    break
                yield sse_frame
        except Exception as e:
            logger.exception("Agent SSE stream error")
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


@router.get("/cost", summary="云端 LLM 成本统计")
async def agent_cost(
    current_user: User = Depends(get_current_user_or_api_key),
):
    """返回当前日/月云端 LLM 用量和限额（仅登录用户可访问）"""
    from app.core.cost_tracker import get_usage_stats
    stats = await get_usage_stats()
    return APIResponse.success(data=stats)


@router.get("/llm-provider", summary="当前 LLM Provider 信息")
async def llm_provider_info():
    """返回当前 LLM provider 和模型名（无需登录，不含密钥）"""
    from app.core.llm_client import _get_model_name
    return {
        "provider": settings.LLM_PROVIDER,
        "model": _get_model_name("agent"),
    }


@router.post("/follow-up", summary="重新生成推荐问题")
async def regenerate_follow_up(
    question: str = Query(..., min_length=1, max_length=1000),
    answer: str = Query(..., min_length=1, max_length=4000),
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Phase 9 P1.4: 重新生成 3 个推荐后续问题（不依赖 session 持久化）"""
    from app.services.agent_service import AgentService
    service = AgentService(db)
    questions = await service._generate_follow_up_questions(question, answer)
    return APIResponse.success(data={"follow_up_questions": questions})
