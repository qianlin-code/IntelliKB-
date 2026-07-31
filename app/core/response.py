"""
统一响应格式 —— 所有 API 返回值走这个格式

{
    "code": 200,
    "message": "success",
    "data": {...},
    "trace_id": "uuid-string"
}
"""
import uuid
from typing import Any

from fastapi.responses import JSONResponse


class APIResponse(JSONResponse):
    """统一响应构造器

    继承 JSONResponse 以便在 route 中作为 response_class 使用时，
    FastAPI 生成 OpenAPI  schema 能正确读取 media_type。
    """

    media_type = "application/json"

    @staticmethod
    def success(
        data: Any = None,
        message: str = "success",
        code: int = 200,
        trace_id: str | None = None,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=code,
            content={
                "code": code,
                "message": message,
                "data": data,
                "trace_id": trace_id or "",
            },
        )

    @staticmethod
    def error(
        message: str = "internal server error",
        code: int = 500,
        data: Any = None,
        trace_id: str | None = None,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=code,
            content={
                "code": code,
                "message": message,
                "data": data,
                "trace_id": trace_id or "",
            },
        )

    @staticmethod
    def created(
        data: Any = None,
        message: str = "created",
        trace_id: str | None = None,
    ) -> JSONResponse:
        return APIResponse.success(data=data, message=message, code=201, trace_id=trace_id)


def make_trace_id() -> str:
    """生成请求追踪 ID"""
    return uuid.uuid4().hex[:16]
