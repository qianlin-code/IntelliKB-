"""时间工具 —— 统一 UTC 时间源（naive，与 MySQL DATETIME 兼容）"""
from datetime import UTC, datetime


def utcnow() -> datetime:
    """
    返回 naive UTC 时间（不带 tzinfo）。

    设计理由:
      MySQL DATETIME 列不存储时区信息，SQLAlchemy 读写均为 naive datetime。
      若 utcnow() 返回 aware datetime，与 DB 值比较会触发:
        TypeError: can't compare offset-naive and offset-aware datetimes
      PyJWT 对 naive datetime 的 iat/exp 同样按 UTC 时间戳处理。
    """
    return datetime.now(UTC).replace(tzinfo=None)
