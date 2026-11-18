from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.models.memory import EpisodicMemory, UserProfile
from app.services.ltm_service import LTMService

logger = logging.getLogger(__name__)


class ProactiveDecision:
    """主动决策输出结果"""
    def __init__(
        self,
        should_trigger: bool,
        topic: str,
        content: str,
        reason: str,
        score: float,
    ) -> None:
        self.should_trigger = should_trigger
        self.topic = topic
        self.content = content
        self.reason = reason
        self.score = score


class ProactiveDecider:
    """主动意愿决策器 (Proactive Intention Decider)
    基于大模型与长期记忆，判断当前是否有足够高价值的话题值得主动找用户沟通。
    场景涵盖：
    1. 【周五周度复盘引导】：自动总结本周踩坑日记；
    2. 【排障卡点次日回访】：针对昨天未解决或重要的排障进行追踪关怀；
    3. 【成长里程碑/OKR推进】：长周期空闲时结合目标启发。
    """

    def __init__(self, ltm_service: LTMService | None = None) -> None:
        self.ltm_service = ltm_service or LTMService()

    def _get_llm(self) -> ChatOpenAI:
        return ChatOpenAI(
            model=os.getenv("DEFAULT_MODEL", "openai/deepseek-v4-pro").split("/")[-1],
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_API_BASE", "https://model-api.datagrand.com/v1"),
            temperature=0.7,
        )

    async def evaluate_weekly_review(self, user_id: str) -> ProactiveDecision:
        """评估并生成周五技术复盘的主动关怀内容"""
        profile = self.ltm_service.get_user_profile(user_id)
        # 获取该用户所有的排障记忆
        memories = self.ltm_service.search_episodic_memories(user_id, query="排障 架构 故障 方案", top_k=5)

        system_prompt = (
            "你是 MaoWu，一位懂工程师技术痛点、亦师亦友的技术 Mentor。\n"
            "现在是周五下班前夕，你准备主动给用户发一条【周度技术复盘与周末关怀】。\n"
            "要求：\n"
            "1. 语言自然亲切，有烟火气和工程师圈子的默契，杜绝公文式大排比和官话；\n"
            "2. 结合他本周在系统架构上的排障踩坑和攻关，帮他提炼一句核心心得；\n"
            "3. 鼓励他周末好好休息充电，不要带着线上负担过周末。\n"
            "字数控制在 150 字以内。"
        )

        mem_text = "\n".join([f"- [{m.title}]: 根因: {m.root_cause}, 方案: {m.resolution}" for m in memories]) if memories else "本周系统平稳，无重大踩坑。"
        proj_text = "; ".join([p.name for p in profile.projects]) or "核心系统"

        user_prompt = f"用户负责系统：{proj_text}\n近期关键踩坑与经验：\n{mem_text}"

        llm = self._get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        content = str(response.content).strip()
        return ProactiveDecision(
            should_trigger=True,
            topic="weekly_review",
            content=content,
            reason="周五例行敏捷复盘与技术沉淀关怀",
            score=9.0,
        )

    async def evaluate_blocker_followup(self, user_id: str) -> ProactiveDecision:
        """评估是否有近期重大排障卡点需要主动跟进询问"""
        memories = self.ltm_service.search_episodic_memories(user_id, query="报错 异常 失败 超时", top_k=2)
        if not memories:
            return ProactiveDecision(
                should_trigger=False,
                topic="blocker_followup",
                content="",
                reason="近期无重大阻塞型排障记录",
                score=2.0,
            )

        latest_mem = memories[0]
        system_prompt = (
            "你是 MaoWu 技术导师。你注意到用户近期排查过一个技术卡点，你今天上班主动发一条简短问候，询问是否已彻底稳定解决。\n"
            "风格：简短、专业、务实关切，80 字以内。"
        )

        user_prompt = f"近期排障问题：{latest_mem.title}\n背景与根因：{latest_mem.context} / {latest_mem.root_cause}"

        llm = self._get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        content = str(response.content).strip()
        return ProactiveDecision(
            should_trigger=True,
            topic="blocker_followup",
            content=content,
            reason=f"跟进近期排障卡点: {latest_mem.title}",
            score=8.5,
        )
