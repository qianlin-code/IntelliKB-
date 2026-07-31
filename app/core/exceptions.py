"""
全局异常处理 —— 所有异常统一格式返回，不暴露内部细节
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.response import make_trace_id

logger = logging.getLogger("app")


class AppException(Exception):
    """应用自定义异常基类"""

    def __init__(self, message: str, code: int = 400, data: dict | None = None):
        self.message = message
        self.code = code
        self.data = data


class NotFoundError(AppException):
    """资源不存在"""
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message=message, code=404)


class UnauthorizedError(AppException):
    """未认证"""
    def __init__(self, message: str = "未登录或 Token 已过期"):
        super().__init__(message=message, code=401)


class ForbiddenError(AppException):
    """无权限"""
    def __init__(self, message: str = "无权限访问"):
        super().__init__(message=message, code=403)


class ConflictError(AppException):
    """资源冲突"""
    def __init__(self, message: str = "资源冲突，请重试"):
        super().__init__(message=message, code=409)


class BusinessError(AppException):
    """业务逻辑错误"""
    def __init__(self, message: str, code: int = 400):
        super().__init__(message=message, code=code)


# ── 全局异常处理器 ──

async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", make_trace_id())
    return JSONResponse(
        status_code=exc.code,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": exc.data,
            "trace_id": trace_id,
        },
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", make_trace_id())
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.detail,
            "data": None,
            "trace_id": trace_id,
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 参数校验失败 —— 中文错误提示"""
    trace_id = getattr(request.state, "trace_id", make_trace_id())
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        msg = error["msg"]
        errors.append(f"字段 {field}: {msg}")
    detail_message = "; ".join(errors)
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": f"参数校验失败: {detail_message}",
            "data": None,
            "trace_id": trace_id,
        },
    )


async def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """429 Rate Limit 处理"""
    trace_id = getattr(request.state, "trace_id", make_trace_id())
    return JSONResponse(
        status_code=429,
        content={
            "code": 429,
            "message": str(exc) if str(exc) else "请求过于频繁，请稍后重试",
            "data": None,
            "trace_id": trace_id,
        },
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    未预期异常兜底 — 打印完整堆栈便于排查。

    安全: 对外仅返回 "服务器内部错误" + trace_id，
         完整堆栈仅写入日志（不暴露给客户端）。
    """
    trace_id = getattr(request.state, "trace_id", make_trace_id())
    logger.exception(
        "Unhandled exception: %s | path=%s method=%s trace_id=%s",
        repr(exc),
        request.url.path,
        request.method,
        trace_id,
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "服务器内部错误",
            "data": None,
            "trace_id": trace_id,
        },
    )


def register_exception_handlers(app: FastAPI):
    """向 FastAPI app 注册所有异常处理器"""
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
