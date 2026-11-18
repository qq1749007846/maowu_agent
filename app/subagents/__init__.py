from __future__ import annotations

import logging

from app.subagents.dispatcher import SubAgentDispatcher, TaskStatus, TaskTicket, dispatcher
from app.subagents.reflector import BackgroundReflectorAgent
from app.subagents.researcher import DeepResearcherAgent

logger = logging.getLogger(__name__)


def init_subagents(custom_dispatcher: SubAgentDispatcher | None = None) -> SubAgentDispatcher:
    """初始化并注册所有后台子代理至派发器"""
    disp = custom_dispatcher or dispatcher

    reflector = BackgroundReflectorAgent()
    researcher = DeepResearcherAgent()

    # 注册记忆沉淀子代理
    disp.register_worker("memory_consolidation", reflector.reflect_and_consolidate)
    # 注册深度技术调研子代理
    disp.register_worker("deep_research", researcher.execute_research)

    logger.info("All subagents registered successfully.")
    return disp


__all__ = [
    "dispatcher",
    "init_subagents",
    "SubAgentDispatcher",
    "TaskTicket",
    "TaskStatus",
    "BackgroundReflectorAgent",
    "DeepResearcherAgent",
]
