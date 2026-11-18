from __future__ import annotations

import asyncio
from typing import Any
import pytest

from app.subagents.dispatcher import SubAgentDispatcher, TaskStatus, TaskTicket


@pytest.mark.asyncio
async def test_dispatcher_lifecycle_and_submission():
    """测试任务派发器的启动、任务分发与异步执行全生命周期"""
    dispatcher = SubAgentDispatcher()

    # 注册一个模拟 Worker
    async def mock_worker(ticket: TaskTicket) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"processed": True, "input": ticket.payload.get("data")}

    dispatcher.register_worker("test_task", mock_worker)

    # 启动调度器
    await dispatcher.start()

    # 提交工单
    ticket = await dispatcher.submit_task(
        task_type="test_task",
        user_id="user_test_001",
        payload={"data": "hello subagent"},
    )

    assert ticket.status in [TaskStatus.PENDING, TaskStatus.RUNNING]

    # 等待 Worker 执行完成
    await asyncio.sleep(0.15)

    queried = dispatcher.get_task(ticket.task_id)
    assert queried is not None
    assert queried.status == TaskStatus.COMPLETED
    assert queried.result == {"processed": True, "input": "hello subagent"}
    assert queried.completed_at is not None

    # 关闭调度器
    await dispatcher.stop()


@pytest.mark.asyncio
async def test_dispatcher_unregistered_worker():
    """测试未注册 worker 时的失败兜底机制"""
    dispatcher = SubAgentDispatcher()
    await dispatcher.start()

    ticket = await dispatcher.submit_task(
        task_type="non_existent_type",
        user_id="user_test_002",
        payload={},
    )

    await asyncio.sleep(0.05)

    queried = dispatcher.get_task(ticket.task_id)
    assert queried is not None
    assert queried.status == TaskStatus.FAILED
    assert "No worker registered" in str(queried.error)

    await dispatcher.stop()
