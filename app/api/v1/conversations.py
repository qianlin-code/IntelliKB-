"""
对话管理 API

所有端点支持 JWT Bearer + X-API-Key + Cookie 三种认证。
返回统一 APIResponse 格式（code/message/data/trace_id）。

Phase 9: 新增导出端点 GET /{id}/export。
"""
import json
import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.response import APIResponse, make_trace_id
from app.depends.auth import get_current_user_or_api_key
from app.models.user import User
from app.repositories.message import MessageRepository
from app.schemas.conversation import (
    ConversationCreate, ConversationListResponse,
    ConversationResponse, ConversationUpdate,
)
from app.schemas.message import MessageListResponse, MessageResponse
from app.services.conversation_service import ConversationService

logger = logging.getLogger("app")
router = APIRouter(prefix="/conversations", tags=["对话管理"])


@router.get("", summary="对话列表", response_class=APIResponse)
async def list_conversations(
    request: Request,
    kb_id: int = Query(default=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, description="搜索标题或消息内容"),
    start_date: str | None = Query(default=None, description="开始日期 (ISO 格式)"),
    end_date: str | None = Query(default=None, description="结束日期 (ISO 格式)"),
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """列出对话（按 updated_at DESC 分页）。

    Phase 9: kb_id=0 表示搜索所有 KB；支持 q/start_date/end_date 筛选。
    """
    trace_id = make_trace_id()
    service = ConversationService(db)
    items, total = await service.list(
        kb_id, current_user.id, page, page_size,
        search=q, start_date=start_date, end_date=end_date,
    )

    return APIResponse.success(data=ConversationListResponse(
        items=[
            ConversationResponse(
                id=conv.id,
                kb_id=conv.kb_id,
                user_id=conv.user_id,
                title=conv.title,
                message_count=conv.message_count,
                is_pinned=bool(conv.is_pinned),
                is_starred=bool(conv.is_starred),
                created_at=conv.created_at.isoformat() if conv.created_at else "",
                updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
            )
            for conv in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    ).model_dump(), trace_id=trace_id)


@router.post("", summary="创建对话", status_code=201, response_class=APIResponse)
async def create_conversation(
    request: Request,
    body: ConversationCreate,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """创建新对话，自动生成标题"""
    trace_id = make_trace_id()
    service = ConversationService(db)
    title = body.title or ConversationService.generate_title("新对话")
    conv = await service.create(body.kb_id, current_user.id, title)

    return APIResponse.created(data=ConversationResponse(
        id=conv.id,
        kb_id=conv.kb_id,
        user_id=conv.user_id,
        title=conv.title,
        message_count=conv.message_count,
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
    ).model_dump(), trace_id=trace_id)


@router.get("/{conv_id}", summary="对话详情", response_class=APIResponse)
async def get_conversation(
    request: Request,
    conv_id: int,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """对话详情"""
    trace_id = make_trace_id()
    service = ConversationService(db)
    conv = await service.get(conv_id, current_user.id)

    return APIResponse.success(data=ConversationResponse(
        id=conv.id,
        kb_id=conv.kb_id,
        user_id=conv.user_id,
        title=conv.title,
        message_count=conv.message_count,
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
    ).model_dump(), trace_id=trace_id)


@router.put("/{conv_id}", summary="更新对话", response_class=APIResponse)
async def update_conversation(
    request: Request,
    conv_id: int,
    body: ConversationUpdate,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """更新对话标题/置顶/收藏（仅自己创建的对话）"""
    trace_id = make_trace_id()
    service = ConversationService(db)
    conv = await service.update_meta(
        conv_id, current_user.id,
        title=body.title,
        is_pinned=body.is_pinned,
        is_starred=body.is_starred,
    )

    return APIResponse.success(data=ConversationResponse(
        id=conv.id,
        kb_id=conv.kb_id,
        user_id=conv.user_id,
        title=conv.title,
        message_count=conv.message_count,
        is_pinned=bool(conv.is_pinned),
        is_starred=bool(conv.is_starred),
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
    ).model_dump(), trace_id=trace_id)


@router.post("/{conv_id}/messages/{msg_id}/regenerate", summary="重新生成回答")
async def regenerate_message(
    request: Request,
    conv_id: int,
    msg_id: int,
    edited_question: str = Query(default="", alias="edited_question"),
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Phase 9 P1.1: 编辑用户消息并重新生成回答。

    从该消息位置截断后续消息和 checkpoint，用 edited_question 重新调用 Agent。
    """
    from app.services.agent_service import AgentService
    from app.repositories.message import MessageRepository

    service = ConversationService(db)
    conv = await service.get(conv_id, current_user.id)
    msg_repo = MessageRepository(db)
    target_msg = await msg_repo.get_by_id(msg_id)
    if target_msg is None or target_msg.conversation_id != conv_id:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("消息不存在")

    # 截断后续消息（硬删除 msg_id 及之后的所有消息）
    from app.models.message import Message
    from sqlalchemy import delete
    await db.execute(
        delete(Message).where(
            Message.conversation_id == conv_id,
            Message.id >= msg_id,
        )
    )

    # 清理 checkpoint
    try:
        from app.services.checkpoint_cleanup_service import CheckpointCleanupService
        cleanup = CheckpointCleanupService(db)
        await cleanup.cleanup_thread(f"conv:{conv_id}")
    except Exception:
        pass

    await db.flush()

    # 重新调用 Agent chat
    agent_service = AgentService(db)
    result = await agent_service.chat(
        kb_id=conv.kb_id,
        question=edited_question or (target_msg.content or ""),
        user_id=current_user.id,
        conv_id=conv_id,
    )
    return APIResponse.success(data=result.model_dump(mode="json"), trace_id=make_trace_id())


@router.delete("/{conv_id}", summary="删除对话", response_class=APIResponse)
async def delete_conversation(
    request: Request,
    conv_id: int,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """删除对话（先硬删除消息，再软删除对话）"""
    trace_id = make_trace_id()
    service = ConversationService(db)
    await service.delete(conv_id, current_user.id)

    return APIResponse.success(message="对话已删除", trace_id=trace_id)


@router.get("/{conv_id}/export", summary="导出对话为 Markdown")
async def export_conversation(
    request: Request,
    conv_id: int,
    fmt: str = Query(default="md", alias="format", regex="^(md|pdf)$"),
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """导出对话为 Markdown 文件（Phase 9 P0.1）。

    - format=md: 返回 Markdown 文本（可直接下载）
    - format=pdf: 暂返回纯文本（PDF 生成依赖较重，作为 P1 后续实现）
    """
    service = ConversationService(db)
    conv = await service.get(conv_id, current_user.id)
    msg_repo = MessageRepository(db)
    msgs, _ = await msg_repo.list_by_conversation(conv_id, None, 2000)

    # 构建 Markdown
    title = conv.title or "对话"
    created = conv.created_at.strftime("%Y-%m-%d %H:%M") if conv.created_at else ""
    lines = [
        f"# {title}",
        f"",
        f"> 导出时间: {created}",
        f"> 消息数: {len(msgs)}",
    ]

    if fmt == "pdf":
        lines.append(f"> 格式: PDF 导出暂未实现，请使用 format=md")
        lines.append("")

    lines.append("")
    lines.append("---")
    lines.append("")

    for i, msg in enumerate(msgs):
        role_label = "👤 **用户**" if msg.role == "user" else "🤖 **AI 助手**"
        ts = msg.created_at.strftime("%H:%M") if msg.created_at else ""
        lines.append(f"### {role_label}  _{ts}_")
        lines.append("")
        lines.append(msg.content or "(无内容)")
        lines.append("")

        # 解析 metadata 中的 sources
        if msg.metadata_json:
            try:
                meta = json.loads(msg.metadata_json)
                sources = meta.get("sources", [])
                if sources:
                    lines.append("> **参考来源:**")
                    for j, src in enumerate(sources):
                        doc_id = src.get("document_id", "?")
                        score = src.get("score", 0)
                        excerpt = (src.get("content", "") or "")[:150]
                        lines.append(f"> [{j+1}] 文档#{doc_id} (相关度: {score:.0%}) — {excerpt}")
                    lines.append("")
            except (json.JSONDecodeError, TypeError):
                pass

        lines.append("---")
        lines.append("")

    content = "\n".join(lines)
    return PlainTextResponse(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={title[:30]}.md",
        },
    )


@router.post("/{conv_id}/fork", summary="分叉对话")
async def fork_conversation(
    request: Request,
    conv_id: int,
    message_id: int = Query(default=0, alias="message_id"),
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Phase 9 P2.1: 基于某条消息创建分叉会话。

    复制原会话到 message_id 为止的历史，创建新 conversation。
    """
    service = ConversationService(db)
    conv = await service.get(conv_id, current_user.id)
    msg_repo = MessageRepository(db)

    # 获取原会话所有消息
    all_msgs, _ = await msg_repo.list_by_conversation(conv_id, None, 2000)

    # 截取到 message_id 为止（不含该消息）
    fork_msgs = []
    for m in all_msgs:
        if message_id > 0 and m.id >= message_id:
            break
        fork_msgs.append(m)

    # 创建新会话
    new_title = (conv.title or "对话") + " (分支)"
    new_conv = await service.create(conv.kb_id, current_user.id, new_title)

    # 复制消息到新会话
    if fork_msgs:
        copied = [
            {
                "conversation_id": new_conv.id,
                "role": m.role,
                "content": m.content,
                "metadata_json": m.metadata_json,
                "token_count": m.token_count,
            }
            for m in fork_msgs
        ]
        await msg_repo.create_batch(copied)
        # 更新新会话的消息计数
        for _ in copied:
            await service.conv_repo.increment_message_count(new_conv.id)

    return APIResponse.success(data={
        "forked_from": conv_id,
        "new_conversation_id": new_conv.id,
        "copied_messages": len(fork_msgs),
    }, trace_id=make_trace_id())


@router.get("/{conv_id}/messages", summary="消息列表", response_class=APIResponse)
async def list_messages(
    request: Request,
    conv_id: int,
    before_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """消息列表（游标分页：按 ID ASC 返回）"""
    trace_id = make_trace_id()
    service = ConversationService(db)
    items, has_more = await service.get_messages(
        conv_id, current_user.id, before_id, limit,
    )

    return APIResponse.success(data=MessageListResponse(
        items=[
            MessageResponse(
                id=msg.id,
                conversation_id=msg.conversation_id,
                role=msg.role,
                content=msg.content,
                metadata_json=json.loads(msg.metadata_json) if msg.metadata_json else None,
                token_count=msg.token_count,
                tool_call_id=msg.tool_call_id,
                created_at=msg.created_at.isoformat() if msg.created_at else "",
            )
            for msg in items
        ],
        has_more=has_more,
    ).model_dump(), trace_id=trace_id)
