"""
Phase 10: 审计日志服务

异步写入审计日志，不阻塞主流程。
"""
import json
import logging

from app.models.audit_log import AuditLog

logger = logging.getLogger("app")


async def log_event(
    db,
    user_id: int | None,
    action: str,
    resource_type: str | None = None,
    resource_id: int | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """写入一条审计日志。

    异步写入，异常时仅记录 warning 不影响主流程。
    """
    try:
        log = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details, ensure_ascii=False, default=str) if details else None,
            ip_address=ip_address or "",
            user_agent=(user_agent or "")[:500],
        )
        db.add(log)
        # 不调用 flush/commit——由调用方的 db session 统一提交
    except Exception as e:
        logger.warning("Audit log write failed (non-blocking): %s", e)


# 标准 action 枚举
class AuditAction:
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    API_KEY_CREATE = "API_KEY_CREATE"
    API_KEY_DELETE = "API_KEY_DELETE"
    KB_CREATE = "KB_CREATE"
    KB_UPDATE = "KB_UPDATE"
    KB_DELETE = "KB_DELETE"
    KB_MEMBER_ADD = "KB_MEMBER_ADD"
    KB_MEMBER_REMOVE = "KB_MEMBER_REMOVE"
    KB_TRANSFER = "KB_TRANSFER"
    DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
    DOCUMENT_DELETE = "DOCUMENT_DELETE"
    AGENT_CHAT = "AGENT_CHAT"
    EVAL_RUN = "EVAL_RUN"
    USER_ROLE_CHANGE = "USER_ROLE_CHANGE"
    SYSTEM_CONFIG_UPDATE = "SYSTEM_CONFIG_UPDATE"
