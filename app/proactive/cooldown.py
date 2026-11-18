from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any

from app.models.memory import UserProfile
from app.services.ltm_service import LTMService

logger = logging.getLogger(__name__)


class CooldownGuard:
    """防打扰与冷却守卫 (Cooldown & Anti-Disturbance Guard)
    严格执行：
    1. 夜间免扰时段（默认 23:00 - 08:30 禁止任何主动唤醒）；
    2. 每日主动触达频次熔断（默认每个用户每日最多 1 次）；
    3. 两次主动唤醒之间的硬性冷却间隔（默认至少 12 小时）。
    """

    def __init__(
        self,
        quiet_hours_start: int = 23,
        quiet_hours_end: int = 8,
        quiet_minutes_end: int = 30,
        max_daily_contacts: int = 1,
        cooldown_hours: float = 12.0,
    ) -> None:
        self.quiet_hours_start = quiet_hours_start
        self.quiet_hours_end = quiet_hours_end
        self.quiet_minutes_end = quiet_minutes_end
        self.max_daily_contacts = max_daily_contacts
        self.cooldown_hours = cooldown_hours

        # 记录用户最近主动触达历史: {user_id: [datetime, ...]}
        self._contact_history: dict[str, list[datetime]] = {}

    def is_quiet_hours(self, current_dt: datetime | None = None) -> bool:
        """检查当前时刻是否处于夜间静默时段"""
        dt = current_dt or datetime.now()
        cur_time = dt.time()

        # 夜间时段：例如 23:00 到次日 08:30
        start_time = time(self.quiet_hours_start, 0)
        end_time = time(self.quiet_hours_end, self.quiet_minutes_end)

        if start_time > end_time:
            # 跨午夜区间：当前时间 >= 23:00 或 当前时间 < 08:30
            return cur_time >= start_time or cur_time < end_time
        else:
            return start_time <= cur_time < end_time

    def can_contact(self, user_id: str, current_dt: datetime | None = None) -> tuple[bool, str]:
        """综合评估是否允许向该用户发起主动问候/复盘"""
        now = current_dt or datetime.now(UTC)

        # 1. 检查静默时段
        # 将 UTC 转为本地时间或按当前机器时间判断
        local_now = datetime.now() if current_dt is None else current_dt
        if self.is_quiet_hours(local_now):
            return False, f"处于静默免扰时段 ({self.quiet_hours_start}:00 - {self.quiet_hours_end}:{self.quiet_minutes_end:02d})"

        history = self._contact_history.get(user_id, [])
        if not history:
            return True, "允许触达 (首触达)"

        # 2. 检查冷却间隔
        last_contact = history[-1]
        elapsed = (now - last_contact).total_seconds() / 3600.0
        if elapsed < self.cooldown_hours:
            return False, f"仍处于冷却期中 (已过 {elapsed:.1f}h / 需冷却 {self.cooldown_hours}h)"

        # 3. 检查过去 24 小时内的频次上限
        one_day_ago = now - timedelta(days=1)
        recent_contacts = [t for t in history if t >= one_day_ago]
        if len(recent_contacts) >= self.max_daily_contacts:
            return False, f"已达 24 小时最大频次上限 ({len(recent_contacts)}/{self.max_daily_contacts})"

        return True, "允许触达"

    def record_contact(self, user_id: str, contact_dt: datetime | None = None) -> None:
        """记录一次成功的主动触达时间"""
        now = contact_dt or datetime.now(UTC)
        if user_id not in self._contact_history:
            self._contact_history[user_id] = []
        self._contact_history[user_id].append(now)
        logger.info(f"Recorded proactive contact for user {user_id} at {now.isoformat()}")

    def reset_history(self, user_id: str | None = None) -> None:
        """重置历史记录（测试用）"""
        if user_id:
            self._contact_history.pop(user_id, None)
        else:
            self._contact_history.clear()
