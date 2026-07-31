"""
结构化日志 —— JSON 格式 + trace_id 注入 + 敏感信息脱敏

TraceIdVar 是全局 ContextVar，由 middleware.TraceMiddleware 写入，
TraceIdFilter 从 ContextVar 读取并注入到每条日志记录中。
"""
import contextvars
import logging
import re
import sys

from app.config import settings

# 全局 TraceId ContextVar — 由 middleware 写入，logging 读取
TraceIdVar: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


class SensitiveDataFilter(logging.Filter):
    """脱敏 password/api_key/token/authorization/secret"""
    SENSITIVE_KEYS = {"password", "api_key", "token", "authorization", "secret"}

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "msg") and isinstance(record.msg, str):
            for key in self.SENSITIVE_KEYS:
                record.msg = re.sub(
                    rf'("{key}"\s*:\s*)"[^"]*"',
                    r'\1"***REDACTED***"',
                    record.msg,
                    flags=re.IGNORECASE,
                )
        return True


class TraceIdFilter(logging.Filter):
    """从 ContextVar 读取 trace_id 注入到日志记录"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = TraceIdVar.get() or "-"
        return True


class SafeJsonFormatter(logging.Formatter):
    """安全 JSON 格式化器 — 缺失字段默认 '-' 而不会崩溃"""

    def format(self, record: logging.LogRecord) -> str:
        # 确保 trace_id 存在（若 TraceIdFilter 未覆盖）
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return super().format(record)


def setup_logging():
    """初始化结构化 JSON 日志"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        SafeJsonFormatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "trace_id": "%(trace_id)s", '
            '"message": "%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.addFilter(SensitiveDataFilter())
    root.addFilter(TraceIdFilter())

    # 抑制 alembic 日志
    logging.getLogger("alembic").setLevel(logging.WARNING)
