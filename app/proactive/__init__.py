from __future__ import annotations

from app.proactive.cooldown import CooldownGuard
from app.proactive.decider import ProactiveDecider, ProactiveDecision
from app.proactive.scheduler import ProactiveMessage, ProactiveScheduler

# 单例调度器实例
proactive_scheduler = ProactiveScheduler()


def get_proactive_scheduler() -> ProactiveScheduler:
    """获取全局主动调度器单例"""
    return proactive_scheduler


__all__ = [
    "CooldownGuard",
    "ProactiveDecider",
    "ProactiveDecision",
    "ProactiveMessage",
    "ProactiveScheduler",
    "get_proactive_scheduler",
    "proactive_scheduler",
]
