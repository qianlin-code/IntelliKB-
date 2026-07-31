"""
云端 LLM 成本追踪单元测试
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import cost_tracker


@pytest.mark.asyncio
async def test_record_usage_pipelines_to_redis():
    """record_usage 应通过 pipeline 原子递增日/月计数器并设置 TTL。"""
    mock_pipe = MagicMock()
    mock_pipe.incrby = MagicMock(return_value=mock_pipe)
    mock_pipe.incr = MagicMock(return_value=mock_pipe)
    mock_pipe.expire = MagicMock(return_value=mock_pipe)
    mock_pipe.execute = AsyncMock(return_value=[True] * 10)

    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("app.core.cost_tracker.get_redis", new=AsyncMock(return_value=mock_redis)):
        await cost_tracker.record_usage(100, 50)

    assert mock_redis.pipeline.called
    assert mock_pipe.incrby.call_count == 4  # daily input/output + monthly input/output
    assert mock_pipe.incr.call_count == 2    # daily/monthly requests
    assert mock_pipe.expire.call_count == 6
    mock_pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_limits_unlimited_when_zero():
    """日/月限额均为 0 时不限制。"""
    with patch("app.core.cost_tracker.settings") as mock_settings:
        mock_settings.DAILY_TOKEN_LIMIT = 0
        mock_settings.MONTHLY_TOKEN_LIMIT = 0
        exceeded, reason = await cost_tracker.check_limits()
    assert exceeded is False
    assert reason == ""


@pytest.mark.asyncio
async def test_check_limits_daily_exceeded():
    """每日输入 token 达到上限时返回超限。"""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=b"1000")

    with patch("app.core.cost_tracker.get_redis", new=AsyncMock(return_value=mock_redis)):
        with patch("app.core.cost_tracker.settings") as mock_settings:
            mock_settings.DAILY_TOKEN_LIMIT = 1000
            mock_settings.MONTHLY_TOKEN_LIMIT = 0
            exceeded, reason = await cost_tracker.check_limits()

    assert exceeded is True
    assert "每日" in reason


@pytest.mark.asyncio
async def test_get_usage_stats_returns_structure():
    """get_usage_stats 返回日/月用量和限额结构。"""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=b"123")

    with patch("app.core.cost_tracker.get_redis", new=AsyncMock(return_value=mock_redis)):
        with patch("app.core.cost_tracker.settings") as mock_settings:
            mock_settings.DAILY_TOKEN_LIMIT = 1000
            mock_settings.MONTHLY_TOKEN_LIMIT = 10000
            stats = await cost_tracker.get_usage_stats()

    assert "daily" in stats
    assert "monthly" in stats
    assert stats["daily"]["used"] == 246  # input + output
    assert stats["daily"]["limit"] == 1000
    assert stats["monthly"]["requests"] == 123
