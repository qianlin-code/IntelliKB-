"""
RAG 评测 API（Phase 5 P1）

所有端点均校验 KB 访问权限（非 KB 成员返回 403）。
RAG_EVAL_ENABLED=False 时，本路由不注册（请求返回 404）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import APIResponse
from app.depends.auth import get_current_user_or_api_key
from app.models.eval import EvalQuery, EvalResult, EvalRun
from app.models.user import User
from app.services.eval_service import EvalService
from app.services.kb_service import KBService

router = APIRouter(prefix="/eval", tags=["RAG 评测"])


async def _require_kb_access(kb_id: int, user: User, db: AsyncSession):
    """校验 KB 访问权限：非 owner/editor/viewer → 403"""
    kb_service = KBService(db)
    await kb_service.get_accessible(kb_id, user.id)


@router.post("/queries/synthesize", summary="自动合成评测查询集")
async def synthesize_queries(
    kb_id: int,
    count: int = 50,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """自动合成评测查询集（需 KB 访问权限）"""
    await _require_kb_access(kb_id, current_user, db)
    service = EvalService(db)
    generated = await service.synthesize_queries(kb_id, count)
    return APIResponse.success(data={"generated": generated})


@router.post("/run", summary="执行评测")
async def run_eval(
    kb_id: int,
    top_k: int = 5,
    provider: str | None = None,
    strategy: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """执行 RAG 评测（需 KB 访问权限）。

    Phase 6: 可选 provider=ollama|deepseek，用于跨 provider 对比评测。
    Phase 8: 可选 strategy=A|B|C，用于不同查询重写策略对比评测。
    """
    if provider and provider not in ("ollama", "deepseek"):
        raise HTTPException(
            status_code=422,
            detail={"code": 422, "message": "无效的 provider，可选值: ollama, deepseek"},
        )
    if strategy and strategy not in ("A", "B", "C"):
        raise HTTPException(
            status_code=422,
            detail={"code": 422, "message": "无效的 strategy，可选值: A, B, C"},
        )
    await _require_kb_access(kb_id, current_user, db)
    service = EvalService(db)
    result = await service.run_evaluation(kb_id, top_k, provider=provider, rewrite_strategy=strategy)
    # Phase 10: 审计日志
    from app.services.audit_service import log_event, AuditAction
    await log_event(db, current_user.id, AuditAction.EVAL_RUN, "kb", kb_id,
                    details={"run_id": result.get("run_id"), "query_count": result.get("query_count")})
    return APIResponse.success(data=result)


@router.get("/runs", summary="查询评测历史")
async def list_runs(
    kb_id: int,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """查询 KB 的评测历史（需 KB 访问权限）"""
    await _require_kb_access(kb_id, current_user, db)

    total = await db.scalar(
        select(func.count(EvalRun.id)).where(EvalRun.kb_id == kb_id)
    )
    result = await db.execute(
        select(EvalRun)
        .where(EvalRun.kb_id == kb_id)
        .order_by(EvalRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    runs = result.scalars().all()
    return APIResponse.success(data={
        "items": [
            {
                "id": r.id, "kb_id": r.kb_id, "provider": r.provider,
                "rewrite_strategy": r.rewrite_strategy,
                "query_count": r.query_count,
                "hit_rate_at_3": r.hit_rate_at_3, "hit_rate_at_5": r.hit_rate_at_5,
                "mrr": r.mrr, "recall_at_3": r.recall_at_3,
                "recall_at_5": r.recall_at_5, "created_at": str(r.created_at),
            }
            for r in runs
        ],
        "total": total,
    })


@router.get("/runs/{run_id}/badcases", summary="Badcase 详情")
async def list_badcases(
    run_id: int,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """获取某次评测的 Badcase 详情（rank=0 即未命中相关文档的查询）。

    返回每个 badcase 的问题文本、期望 chunk IDs、实际 top-5 检索结果。
    先校验 run 所属 KB 的访问权限。
    """
    run = await db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "评测记录不存在"})
    await _require_kb_access(run.kb_id, current_user, db)

    # 获取 rank=0 的结果（未命中）
    result = await db.execute(
        select(EvalResult)
        .where(EvalResult.run_id == run_id, EvalResult.rank == 0)
        .limit(200)
    )
    bad_results = result.scalars().all()

    items = []
    for br in bad_results:
        query = await db.get(EvalQuery, br.query_id)
        items.append({
            "result_id": br.id,
            "query_id": br.query_id,
            "question": query.question if query else "(已删除)",
            "expected_chunk_ids": query.relevant_chunk_ids if query else "[]",
            "expected_doc_ids": query.relevant_doc_ids if query else "[]",
            "retrieved_chunk_ids": br.retrieved_chunk_ids,
            "rank": br.rank,
            "hits_in_top_k": br.hits_in_top_k,
            "latency_ms": br.latency_ms,
        })

    return APIResponse.success(data={
        "run_id": run_id,
        "badcase_count": len(items),
        "items": items,
    })
