from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.proactive.cooldown import CooldownGuard
from app.proactive.decider import ProactiveDecider, ProactiveDecision
from app.services.ltm_service import LTMService

logger = logging.getLogger(__name__)


class ProactiveMessage(BaseModel):
    """主动关怀/复盘提醒消息对象"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    topic: str  # weekly_review, blocker_followup, idle_checkin, okr_inspire
    title: str
    content: str
    reason: str
    score: float = 8.0
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = "unread"  # unread, read, dismissed
    channel: str = "all"  # web, astrbot, all


class ProactiveScheduler:
    """主动事件调度器 (Proactive Event Scheduler)
    负责定时心跳、状态巡检、防打扰准入拦截与主动消息生成与派发。
    """

    def __init__(
        self,
        cooldown_guard: CooldownGuard | None = None,
        decider: ProactiveDecider | None = None,
        ltm_service: LTMService | None = None,
        check_interval_seconds: int = 300,  # 默认 5 分钟巡检一次
    ) -> None:
        self.cooldown_guard = cooldown_guard or CooldownGuard()
        self.decider = decider or ProactiveDecider(ltm_service=ltm_service)
        self.ltm_service = ltm_service or LTMService()
        self.check_interval_seconds = check_interval_seconds

        # 消息存储: {user_id: [ProactiveMessage, ...]}
        self._user_messages: dict[str, list[ProactiveMessage]] = {}
        self._running = False
        self._loop_task: asyncio.Task[None] | None = None
        self._subscribers: list[Callable[[ProactiveMessage], Awaitable[None]]] = []

    def subscribe(self, callback: Callable[[ProactiveMessage], Awaitable[None]]) -> None:
        """注册主动消息推送回调"""
        self._subscribers.append(callback)

    async def _notify_subscribers(self, msg: ProactiveMessage) -> None:
        for cb in self._subscribers:
            try:
                await cb(msg)
            except Exception as e:
                logger.error(f"Error notifying proactive message subscriber: {e}")

    async def start(self) -> None:
        """启动后台主动轮询检查循环"""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._scheduler_loop())
        logger.info(f"ProactiveScheduler started with interval={self.check_interval_seconds}s")

    async def stop(self) -> None:
        """优雅关闭后台主动检查循环"""
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("ProactiveScheduler stopped.")

    async def _scheduler_loop(self) -> None:
        """后台轮巡检查逻辑"""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval_seconds)
                if not self._running:
                    break
                await self._run_periodic_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Exception in ProactiveScheduler loop: {e}", exc_info=True)

    async def _run_periodic_check(self) -> None:
        """巡检所有已知的活跃用户画像"""
        profiles = self.ltm_service.list_all_profiles()
        now = datetime.now()
        for profile in profiles:
            user_id = profile.user_id
            can, reason = self.cooldown_guard.can_contact(user_id, current_dt=now)
            if not can:
                logger.debug(f"User {user_id} skip proactive check: {reason}")
                continue

            # 评估是否触发
            await self.trigger_check(user_id=user_id, trigger_type="auto")

    async def trigger_check(
        self,
        user_id: str,
        trigger_type: str = "auto",
        force: bool = False,
    ) -> ProactiveMessage | None:
        """针对指定用户执行主动决策评估并生成主动消息"""
        now = datetime.now()

        # 1. 守卫拦截（若 force=True 则跳过防打扰校验，常用于测试或强制通知）
        if not force:
            can, reason = self.cooldown_guard.can_contact(user_id, current_dt=now)
            if not can:
                logger.info(f"Proactive contact blocked for user '{user_id}': {reason}")
                return None

        # 2. 策略判定
        decision: ProactiveDecision | None = None
        topic_title = "MaoWu 导师的主动关怀"

        if trigger_type == "weekly_review":
            decision = await self.decider.evaluate_weekly_review(user_id)
            topic_title = "周五技术复盘与周末充电关怀"
        elif trigger_type == "blocker_followup":
            decision = await self.decider.evaluate_blocker_followup(user_id)
            topic_title = "近期排障卡点与稳定性回访"
        else:
            # 自动探测策略：
            # 如果是周五且当前时间大于 15:00，优先发起周度技术复盘
            if now.weekday() == 4 and now.hour >= 15:
                decision = await self.decider.evaluate_weekly_review(user_id)
                topic_title = "周五技术复盘与周末充电关怀"
            else:
                # 否则优先探测是否有未关闭或近期的排障阻塞
                decision = await self.decider.evaluate_blocker_followup(user_id)
                topic_title = "近期排障卡点与稳定性回访"

        if not decision or not decision.should_trigger or decision.score < 6.0:
            logger.info(f"Proactive trigger score too low for user '{user_id}' (topic={trigger_type})")
            return None

        # 3. 生成并持久化主动消息
        msg = ProactiveMessage(
            user_id=user_id,
            topic=decision.topic,
            title=topic_title,
            content=decision.content,
            reason=decision.reason,
            score=decision.score,
        )

        if user_id not in self._user_messages:
            self._user_messages[user_id] = []
        self._user_messages[user_id].append(msg)

        # 记录主动触达时间，触发冷却
        self.cooldown_guard.record_contact(user_id)

        # 触发推送广播
        await self._notify_subscribers(msg)

        logger.info(f"Created proactive message '{msg.id}' for user '{user_id}' (topic={msg.topic})")
        return msg

    def get_messages(self, user_id: str, unread_only: bool = False) -> list[ProactiveMessage]:
        """获取指定用户的主动消息列表"""
        msgs = self._user_messages.get(user_id, [])
        if unread_only:
            return [m for m in msgs if m.status == "unread"]
        return list(reversed(msgs))

    def mark_message_read(self, user_id: str, message_id: str) -> bool:
        """将消息标记为已读"""
        msgs = self._user_messages.get(user_id, [])
        for m in msgs:
            if m.id == message_id:
                m.status = "read"
                return True
        return False

    def dismiss_message(self, user_id: str, message_id: str) -> bool:
        """关闭/移除消息"""
        msgs = self._user_messages.get(user_id, [])
        for m in msgs:
            if m.id == message_id:
                m.status = "dismissed"
                return True
        return False
