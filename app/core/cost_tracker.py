"""
云端 LLM 成本追踪（Phase 6 P1.1）

使用 Redis 计数器记录每日/每月 token 消耗和请求次数。
key 格式:
  llm:cost:daily:{YYYY-MM-DD}:input
  llm:cost:daily:{YYYY-MM-DD}:output
  llm:cost:daily:{YYYY-MM-DD}:requests
  llm:cost:monthly:{YYYY-MM}:input
  llm:cost:monthly:{YYYY-MM}:output
  llm:cost:monthly:{YYYY-MM}:requests

每日 key TTL = 48h，每月 key TTL = 62 天，避免无限堆积。
"""
import logging
from datetime import UTC, datetime

from app.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger("app")

DAILY_KEY_PREFIX = "llm:cost:daily"
MONTHLY_KEY_PREFIX = "llm:cost:monthly"
DAILY_TTL = 48 * 3600       # 48 小时
MONTHLY_TTL = 62 * 86400    # 62 天


def _daily_keys() -> tuple[str, str, str]:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return (
        f"{DAILY_KEY_PREFIX}:{today}:input",
        f"{DAILY_KEY_PREFIX}:{today}:output",
        f"{DAILY_KEY_PREFIX}:{today}:requests",
    )


def _monthly_keys() -> tuple[str, str, str]:
    month = datetime.now(UTC).strftime("%Y-%m")
    return (
        f"{MONTHLY_KEY_PREFIX}:{month}:input",
        f"{MONTHLY_KEY_PREFIX}:{month}:output",
        f"{MONTHLY_KEY_PREFIX}:{month}:requests",
    )


async def record_usage(input_tokens: int, output_tokens: int) -> None:
    """原子递增计数器。流式场景可在流结束后传入汇总值。"""
    try:
        r = await get_redis()
        di, do, dr = _daily_keys()
        mi, mo, mr = _monthly_keys()

        pipe = r.pipeline()
        pipe.incrby(di, input_tokens)
        pipe.expire(di, DAILY_TTL)
        pipe.incrby(do, output_tokens)
        pipe.expire(do, DAILY_TTL)
        pipe.incr(dr)
        pipe.expire(dr, DAILY_TTL)
        pipe.incrby(mi, input_tokens)
        pipe.expire(mi, MONTHLY_TTL)
        pipe.incrby(mo, output_tokens)
        pipe.expire(mo, MONTHLY_TTL)
        pipe.incr(mr)
        pipe.expire(mr, MONTHLY_TTL)
        await pipe.execute()
    except Exception as e:
        logger.warning("record_usage failed (non-blocking): %s", e)


async def check_limits() -> tuple[bool, str]:
    """返回 (是否超限, 原因)。

    上限为 0 表示不限制。
    在调用云端 LLM 之前调用此函数，若超限则阻止调用。
    """
    daily_limit = settings.DAILY_TOKEN_LIMIT
    monthly_limit = settings.MONTHLY_TOKEN_LIMIT

    if daily_limit == 0 and monthly_limit == 0:
        return False, ""

    try:
        r = await get_redis()
        # 日用量 = 输入 token（更准确地反映 API 消耗）
        di, _, _ = _daily_keys()
        daily_used = int(await r.get(di) or 0)

        if daily_limit > 0 and daily_used >= daily_limit:
            return True, f"每日 token 上限已达 ({daily_used}/{daily_limit})"

        mi, _, _ = _monthly_keys()
        monthly_used = int(await r.get(mi) or 0)

        if monthly_limit > 0 and monthly_used >= monthly_limit:
            return True, f"每月 token 上限已达 ({monthly_used}/{monthly_limit})"

        return False, ""
    except Exception as e:
        logger.warning("check_limits failed, allowing request: %s", e)
        return False, ""


async def get_usage_stats() -> dict:
    """返回当前日/月用量和限额。"""
    try:
        r = await get_redis()
        di, do, dr = _daily_keys()
        mi, mo, mr = _monthly_keys()

        daily_input = int(await r.get(di) or 0)
        daily_output = int(await r.get(do) or 0)
        daily_requests = int(await r.get(dr) or 0)
        monthly_input = int(await r.get(mi) or 0)
        monthly_output = int(await r.get(mo) or 0)
        monthly_requests = int(await r.get(mr) or 0)

        return {
            "daily": {
                "used": daily_input + daily_output,
                "limit": settings.DAILY_TOKEN_LIMIT,
                "input_tokens": daily_input,
                "output_tokens": daily_output,
                "requests": daily_requests,
            },
            "monthly": {
                "used": monthly_input + monthly_output,
                "limit": settings.MONTHLY_TOKEN_LIMIT,
                "input_tokens": monthly_input,
                "output_tokens": monthly_output,
                "requests": monthly_requests,
            },
        }
    except Exception as e:
        logger.warning("get_usage_stats failed: %s", e)
        return {
            "daily": {"used": 0, "limit": settings.DAILY_TOKEN_LIMIT},
            "monthly": {"used": 0, "limit": settings.MONTHLY_TOKEN_LIMIT},
        }
