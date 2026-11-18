from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskTicket:
    """异步子代理任务工单"""
    task_id: str = field(default_factory=lambda: str(uuid4()))
    task_type: str = "general"
    user_id: str = "default_user"
    payload: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class SubAgentDispatcher:
    """轻量级异步任务派发中心与事件总线 (Task Dispatcher & Event Bus)
    保证主 Agent 极轻交互秒回，重计算异步执行，并在完成后触发回调/通知回流。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskTicket] = {}
        self._handlers: dict[str, Callable[[TaskTicket], Coroutine[Any, Any, Any]]] = {}
        self._queue: asyncio.Queue[TaskTicket] = asyncio.Queue()
        self._worker_loop_task: asyncio.Task[None] | None = None
        self._running: bool = False

    def register_worker(
        self,
        task_type: str,
        handler: Callable[[TaskTicket], Coroutine[Any, Any, Any]],
    ) -> None:
        """注册处理特定类型任务的子代理工作器"""
        self._handlers[task_type] = handler
        logger.info(f"Registered sub-agent worker for task_type: {task_type}")

    async def start(self) -> None:
        """启动后台事件调度器任务"""
        if self._running:
            return
        self._running = True
        self._worker_loop_task = asyncio.create_task(self._event_loop())
        logger.info("SubAgentDispatcher started.")

    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._worker_loop_task and not self._worker_loop_task.done():
            self._worker_loop_task.cancel()
            try:
                await self._worker_loop_task
            except asyncio.CancelledError:
                pass
        logger.info("SubAgentDispatcher stopped.")

    async def submit_task(
        self,
        task_type: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> TaskTicket:
        """派发异步工单，立即返回 Ticket"""
        ticket = TaskTicket(
            task_type=task_type,
            user_id=user_id,
            payload=payload,
            status=TaskStatus.PENDING,
        )
        self._tasks[ticket.task_id] = ticket
        await self._queue.put(ticket)
        logger.info(f"Submitted task {ticket.task_id} of type '{task_type}' for user '{user_id}'")
        return ticket

    def get_task(self, task_id: str) -> TaskTicket | None:
        """查询任务状态与执行结果"""
        return self._tasks.get(task_id)

    async def _event_loop(self) -> None:
        """事件循环：持续消费任务队列并分发给对应子代理"""
        while self._running:
            try:
                ticket = await self._queue.get()
                handler = self._handlers.get(ticket.task_type)
                if not handler:
                    ticket.status = TaskStatus.FAILED
                    ticket.error = f"No worker registered for task_type '{ticket.task_type}'"
                    ticket.completed_at = datetime.now(UTC)
                    self._queue.task_done()
                    continue

                # 异步并发执行具体 Worker
                asyncio.create_task(self._execute_worker(ticket, handler))
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Error in SubAgentDispatcher event loop: %s", exc)

    async def _execute_worker(
        self,
        ticket: TaskTicket,
        handler: Callable[[TaskTicket], Coroutine[Any, Any, Any]],
    ) -> None:
        ticket.status = TaskStatus.RUNNING
        try:
            res = await handler(ticket)
            ticket.result = res
            ticket.status = TaskStatus.COMPLETED
            logger.info(f"Sub-agent task {ticket.task_id} completed successfully.")
        except Exception as exc:
            ticket.error = str(exc)
            ticket.status = TaskStatus.FAILED
            logger.exception(f"Sub-agent task {ticket.task_id} failed: %s", exc)
        finally:
            ticket.completed_at = datetime.now(UTC)


# 全局单例派发器
dispatcher = SubAgentDispatcher()
