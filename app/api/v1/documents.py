"""
文档管理端点（Phase 10: 审计日志 + 配额检查）
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi import BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ForbiddenError
from app.core.redis_client import get_redis
from app.core.response import APIResponse
from app.depends.auth import get_current_user_or_api_key, get_current_user_cookie
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.repositories.knowledge_base import KBRepository
from app.schemas.document import DocumentResponse, DocumentUploadResponse, ChunkResponse
from app.services.doc_service import DocService
from app.services.kb_service import KBService
from app.services.progress_manager import progress_manager

logger = logging.getLogger("app")
router = APIRouter(prefix="/documents", tags=["文档管理"])


# ── Step 3: BackgroundTasks 测试端点 ──

async def _dummy_bg_task():
    """测试 BackgroundTasks 是否能正常执行"""
    logger.info("=== BACKGROUND TASK EXECUTED ===")
    # 写入 Redis 以确认后台任务在服务器线程中执行
    from app.core.redis_client import cache_set
    await cache_set("test:bg:last_run", "ok", ttl=60)


@router.post("/test-bg", summary="测试 BackgroundTasks 是否正常")
async def test_background(background_tasks: BackgroundTasks):
    """Step 3: 调用后应在服务器日志中看到 '=== BACKGROUND TASK EXECUTED ==='"""
    background_tasks.add_task(_dummy_bg_task)
    logger.info("test-bg: scheduled background task")
    return APIResponse.success(data={"status": "scheduled", "note": "检查服务器日志确认 BACKGROUND TASK EXECUTED"})


@router.post("/test-parse-bg/{doc_id}", summary="测试文档解析后台任务")
async def test_parse_background(doc_id: int, background_tasks: BackgroundTasks):
    """直接调度 _parse_doc_bg 测试是否执行。"""
    background_tasks.add_task(_parse_doc_bg, doc_id)
    logger.info("test-parse-bg: scheduled _parse_doc_bg doc_id=%d", doc_id)
    return APIResponse.success(data={"status": "scheduled", "doc_id": doc_id})


# ── 文档上传 ──

@router.post("/upload", summary="上传文档（Phase 2 异步版）")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    kb_id: int = Form(...),
    request: Request = None,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    上传文档到指定知识库。Phase 2: BackgroundTasks 异步解析。

    支持格式: PDF / DOCX / MD / TXT。
    上传后立即返回 doc_id，前端通过 GET /documents/{doc_id}/progress (SSE) 监听进度。
    """
    # Phase 10: 配额检查 — 文档数
    from app.services.quota_service import QuotaService
    quota = QuotaService(db)
    ok, reason = await quota.check_document_upload(kb_id)
    if not ok:
        raise HTTPException(status_code=429, detail={"code": "QUOTA_EXCEEDED", "message": reason})

    # Phase 10: 配额检查 — 存储空间
    storage_used = await quota.get_user_storage_usage(current_user.id)
    file_content = await file.read()
    file_size = len(file_content)
    await file.seek(0)  # reset for downstream reading
    storage_limit_bytes = settings.QUOTA_MAX_STORAGE_MB_PER_USER * 1024 * 1024
    if settings.QUOTA_ENABLED and storage_limit_bytes > 0 and (storage_used + file_size) > storage_limit_bytes:
        raise HTTPException(status_code=429, detail={
            "code": "QUOTA_EXCEEDED",
            "message": f"存储空间不足 ({storage_used / 1024 / 1024:.1f}MB / {settings.QUOTA_MAX_STORAGE_MB_PER_USER}MB)"
        })

    service = DocService(db)
    doc = await service.create_document_record(kb_id, file, current_user.id)

    # 必须显式提交，确保后台任务启动前 doc 记录已对其它 session 可见
    await db.commit()

    logger.info("Scheduling parse_document_async for doc_id=%d via BackgroundTasks", doc.id)
    background_tasks.add_task(_parse_doc_bg, doc.id)

    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    background_tasks.add_task(_audit_log_bg, current_user.id, AuditAction.DOCUMENT_UPLOAD,
                              "document", doc.id, {"kb_id": kb_id, "filename": doc.filename, "file_size": doc.file_size},
                              request.client.host if request and request.client else None,
                              request.headers.get("user-agent", "") if request else "")

    return APIResponse.created(data=DocumentUploadResponse(
        doc_id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status,
        message="文档已提交，正在后台解析",
    ).model_dump(mode="json"))


async def _parse_doc_bg(doc_id: int) -> None:
    """BackgroundTasks 兼容的文档解析包装函数（parse_document_async 自行管理 session）。"""
    from app.core.redis_client import cache_set
    from app.services.doc_service import DocService
    logger.info("[bg] _parse_doc_bg START doc_id=%d", doc_id)
    await cache_set(f"test:parse_bg:{doc_id}", "started", ttl=60)
    await DocService.parse_document_async_static(doc_id)
    await cache_set(f"test:parse_bg:{doc_id}", "done", ttl=60)
    logger.info("[bg] _parse_doc_bg END doc_id=%d", doc_id)


async def _audit_log_bg(
    user_id: int, action: str, resource_type: str, resource_id: int,
    details: dict, ip_address: str, user_agent: str,
):
    """BackgroundTasks 兼容的审计日志写入（独立 session）"""
    try:
        from app.core.database import async_session_factory
        from app.services.audit_service import log_event
        async with async_session_factory() as db:
            await log_event(db, user_id, action, resource_type, resource_id,
                            details=details, ip_address=ip_address, user_agent=user_agent)
            await db.commit()
    except Exception as e_log:
        logging.getLogger("app").warning("Background audit log failed: %s", e_log)


# ── SSE 进度 ──

@router.get("/{doc_id}/progress", summary="SSE 文档解析进度")
async def doc_parse_progress(
    doc_id: int,
    request: Request,
    current_user: User = Depends(get_current_user_cookie),
):
    """
    S1: SSE 端点，cookie-based 认证（兼容 EventSource）。
    O3: 首次立即读取 Redis，再进入轮询。
    """
    from app.core.database import async_session_factory
    async with async_session_factory() as db:
        doc_repo = DocumentRepository(db)
        doc = await doc_repo.get_by_id(doc_id)
        if doc is None:
            raise NotFoundError("文档不存在")

    async def event_generator():
        last_data = None
        sent_complete = False
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = await progress_manager.get(doc_id)
                if data and data != last_data:
                    last_data = data
                    stage = data.get("stage", "unknown")
                    if stage in ("done", "error"):
                        event_type = "complete" if stage == "done" else "error"
                        yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                        sent_complete = True
                        break
                    else:
                        yield f"event: progress\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                await asyncio.sleep(settings.SSE_PROGRESS_POLL_INTERVAL)
        except asyncio.CancelledError:
            pass
        finally:
            if not sent_complete:
                yield 'event: error\ndata: {"stage":"error","message":"连接已断开"}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ── Phase 3: Pub/Sub 版 SSE 进度 ──

@router.get("/{doc_id}/progress-pubsub", summary="SSE 文档解析进度（Pub/Sub 版）")
async def doc_parse_progress_pubsub(
    doc_id: int,
    request: Request,
    current_user: User = Depends(get_current_user_cookie),
):
    """
    Pub/Sub 版 SSE 进度推送（取代 key 轮询）。

    连接生命周期：
    - 每个 SSE 连接创建独立 PubSub 对象
    - 后台 asyncio.Event 检测客户端断开
    - try/finally 保证 unsubscribe + close
    """
    CHANNEL = f"doc:progress:{doc_id}"

    async def event_generator():
        r = await get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(CHANNEL)
        disconnect_event = asyncio.Event()

        async def _check_disconnect():
            while True:
                if await request.is_disconnected():
                    disconnect_event.set()
                    break
                await asyncio.sleep(1)

        check_task = asyncio.create_task(_check_disconnect())

        try:
            async for message in pubsub.listen():
                if disconnect_event.is_set():
                    break
                if message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield f"event: progress\ndata: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            check_task.cancel()
            await pubsub.unsubscribe()
            try:
                await pubsub.aclose()
            except AttributeError:
                await pubsub.close()  # fallback for older redis-py

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ── Phase 1 端点（保持不变）──

@router.get("", summary="文档列表")
async def list_documents(
    kb_id: int = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    kb_service = KBService(db)
    await kb_service.get_accessible(kb_id, current_user.id)
    doc_repo = DocumentRepository(db)
    skip = (page - 1) * page_size
    docs = await doc_repo.list_by_kb(kb_id, skip=skip, limit=page_size)
    total = await doc_repo.count_by_kb(kb_id)
    return APIResponse.success(data={
        "items": [DocumentResponse.model_validate(d).model_dump(mode="json") for d in docs],
        "total": total, "page": page, "page_size": page_size,
    })


@router.get("/{doc_id}", summary="文档详情")
async def get_document(
    doc_id: int,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    doc_repo = DocumentRepository(db)
    doc = await doc_repo.get_by_id(doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    kb_repo = KBRepository(db)
    kb = await kb_repo.get_by_id(doc.kb_id)
    if kb is None or kb.owner_id != current_user.id:
        raise ForbiddenError("无权访问该文档")
    return APIResponse.success(data=DocumentResponse.model_validate(doc).model_dump(mode="json"))


@router.delete("/{doc_id}", summary="删除文档")
async def delete_document(
    doc_id: int,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    service = DocService(db)
    doc = await service.doc_repo.get_by_id(doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    kb_id = doc.kb_id
    await service.delete_document(doc_id, current_user.id)
    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, current_user.id, AuditAction.DOCUMENT_DELETE, "document", doc_id,
                    details={"kb_id": kb_id, "filename": doc.filename},
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent", ""))
    return APIResponse.success(message="文档已删除")


@router.get("/{doc_id}/chunks", summary="文档分块列表")
async def list_chunks(
    doc_id: int,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    doc_repo = DocumentRepository(db)
    doc = await doc_repo.get_by_id(doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    kb_repo = KBRepository(db)
    kb = await kb_repo.get_by_id(doc.kb_id)
    if kb is None or kb.owner_id != current_user.id:
        raise ForbiddenError("无权访问该文档")
    chunks = await doc_repo.get_chunks_by_doc(doc_id)
    return APIResponse.success(data={
        "chunks": [ChunkResponse.model_validate(c).model_dump(mode="json") for c in chunks],
        "total": len(chunks),
    })
