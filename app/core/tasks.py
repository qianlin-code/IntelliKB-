"""
Step 6: 全局后台任务管理器 —— asyncio.create_task 包装

当 FastAPI BackgroundTasks 不可靠时，使用此模块手动管理后台任务生命周期。
"""
import asyncio
import logging

logger = logging.getLogger("app")

running_tasks: set[asyncio.Task] = set()


def create_background_task(coro) -> asyncio.Task:
    """
    创建后台 asyncio 任务并跟踪其生命周期。

    与 FastAPI BackgroundTasks 不同，此方法使用当前事件循环的 create_task，
    任务在事件循环的下一个 tick 开始执行，不依赖于响应的发送完成。
    """
    task = asyncio.create_task(coro)
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)
    task.add_done_callback(_log_task_result)
    logger.debug("Background task created: %s (active=%d)", task.get_name(), len(running_tasks))
    return task


def _log_task_result(task: asyncio.Task):
    """记录任务完成状态"""
    try:
        exc = task.exception()
        if exc:
            logger.error("Background task failed: %s", exc, exc_info=exc)
        else:
            logger.debug("Background task completed: %s", task.get_name())
    except (asyncio.CancelledError, Exception):
        pass
