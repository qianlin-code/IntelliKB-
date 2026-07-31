"""
健康检查端点 —— Phase 7 统一路径（已废弃 /health/liveness + /health/readiness）
"""
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.database import check_db_connection
from app.core.redis_client import check_redis_connection

router = APIRouter(tags=["健康检查"])

# ── Phase 7: Ollama 就绪检查缓存（15 秒，多 worker 各独立缓存）──
_ollama_cache: dict = {"ts": 0.0, "ok": False}


async def _check_ollama_cached() -> bool:
    """Ollama 连通性检查（15 秒缓存，避免每次探针调用 Ollama）"""
    now = time.monotonic()
    if now - _ollama_cache["ts"] < 15:
        return _ollama_cache["ok"]
    _ollama_cache["ts"] = now
    _ollama_cache["ok"] = await _check_ollama_connection()
    return _ollama_cache["ok"]


async def _check_ollama_connection() -> bool:
    """检查 Ollama 是否可达（5s 超时，不重试）"""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            base_url=settings.OLLAMA_BASE_URL.rstrip("/"),
            api_key="ollama",
            timeout=5.0,
            max_retries=0,
        )
        await client.models.list()
        return True
    except Exception:
        return False


@router.get("/health", summary="存活检查")
async def health():
    """GET /api/v1/health — 进程存活探测，始终返回 200"""
    return {"status": "ok", "version": settings.APP_VERSION}


@router.get("/ready", summary="就绪探针")
async def ready():
    """GET /api/v1/ready — 检查 MySQL + Redis + Ollama（若 LLM_PROVIDER=ollama）

    全部可用 → 200 {"status": "ready"}
    任一异常 → 503 {"status": "not_ready", "details": {...}}
    """
    db_ok = await check_db_connection()
    redis_ok = await check_redis_connection()

    checks = {"db": db_ok, "redis": redis_ok}

    if settings.LLM_PROVIDER == "ollama":
        checks["ollama"] = await _check_ollama_cached()

    all_ok = all(checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status": "ready" if all_ok else "not_ready",
            "details": checks,
        },
    )
