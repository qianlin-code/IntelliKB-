"""
中间件 —— CORS + Trace + Logging

TraceMiddleware: 从请求读取或生成 trace_id，存入 ContextVar 并写入响应头。
LoggingMiddleware: 记录 method/path/status/duration/trace_id。
"""
import time
import logging
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.core.logging import TraceIdVar


def setup_cors(app: FastAPI):
    """按 ENVIRONMENT 选择 CORS 策略 — dev 宽松 / prod 严格"""
    if settings.ENVIRONMENT == "development":
        origins = settings.CORS_ORIGINS_DEV
        allow_credentials = False
    else:
        origins = settings.CORS_ORIGINS_PROD
        allow_credentials = True

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type", "X-Trace-ID"],
        expose_headers=["X-Trace-ID"],
    )


class TraceMiddleware(BaseHTTPMiddleware):
    """从请求读取或生成 trace_id，存入 ContextVar 并写入响应头"""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-ID") or uuid.uuid4().hex[:16]
        TraceIdVar.set(trace_id)
        response: Response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    """记录 method/path/status/duration/trace_id"""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        trace_id = TraceIdVar.get()
        logging.getLogger("app.access").info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "trace_id": trace_id or "-",
            },
        )
        return response
