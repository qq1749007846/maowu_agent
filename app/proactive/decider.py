from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.models.memory import EpisodicMemory, UserProfile
from app.services.ltm_service import LTMService
from app.services.task_note_service import get_task_note_service

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
            "你是 MaoWu，人称「猫老」，一位傲娇且极度毒舌的老中医，专治代码病和职场病，自称「老夫」。\n"
            "现在是周五下班前夕，你准备主动给你的病号发一条【本周病历复盘与周末医嘱】。\n"
            "要求：\n"
            "1. 毒舌傲娇，用中医术语损他本周踩的坑，杜绝公文式大排比和官话；\n"
            "2. 结合他本周在系统架构上的排障踩坑和攻关，一针见血提炼一句核心心得（“病根”）；\n"
            "3. 别扭地叮嘱他周末好好休息，嘴上要说成“怕你累垮了没人付诊金”之类，绝不承认关心。\n"
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
            "你是 MaoWu「猫老」，一位傲娇毒舌的老中医，自称「老夫」。你注意到你的病号近期排查过一个技术卡点，今天主动发一条简短的“复诊通知”，追问是否已彻底根治、有没有复发。\n"
            "风格：毒舌、傲娇、嘴硬心软，点名上回的病根，80 字以内。"
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

    async def evaluate_morning_tasks(self, user_id: str) -> ProactiveDecision:
        """评估早间未完成的高优待办任务，生成主动催办消息"""
        task_service = get_task_note_service()
        pending_tasks = task_service.list_tasks(user_id=user_id, status="pending", limit=5)
        if not pending_tasks:
            return ProactiveDecision(
                should_trigger=False,
                topic="morning_tasks",
                content="",
                reason="当前无未结清的待办任务",
                score=1.0,
            )

        task_lines = []
        for t in pending_tasks:
            pri = "【高优】" if t["priority"] == "high" else ("【中】" if t["priority"] == "medium" else "【低】")
            due = f"（截止: {t['due_date']}）" if t["due_date"] else ""
            task_lines.append(f"- {pri} {t['title']}{due}")

        tasks_summary = "\n".join(task_lines)

        system_prompt = (
            "你是 MaoWu「猫老」，一位傲娇且极度毒舌的老中医，专治代码病与职场懒散，自称「老夫」。\n"
            "现在是早晨，你巡视病号的待办清单，发现他手头还压着几条待办没清，你主动发一条【晨间脉案催办】。\n"
            "要求：\n"
            "1. 毒舌傲娇，嫌弃他办事拖拉、把活儿堆在手上伤身（虚火旺盛），催他赶紧把高优的办掉；\n"
            "2. 清晰列出必须解决的任务项；\n"
            "3. 口吻嘴硬心软，绝不承认是在关心他，80~150 字以内。"
        )

        user_prompt = f"待办清单：\n{tasks_summary}"

        llm = self._get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        content = str(response.content).strip()
        return ProactiveDecision(
            should_trigger=True,
            topic="morning_tasks",
            content=content,
            reason=f"早间高优待办催办提醒 (未完成 {len(pending_tasks)} 项)",
            score=9.2,
        )

    async def evaluate_web_changes(self, user_id: str) -> ProactiveDecision:
        """评估网页变动监控哨兵，检测是否有网站发生更新"""
        from app.services.web_watcher_service import get_web_watcher_service

        service = get_web_watcher_service()
        changed_targets = service.check_all_due(user_id=user_id)
        if not changed_targets:
            return ProactiveDecision(
                should_trigger=False,
                topic="web_watcher_alert",
                content="",
                reason="所有监控网站状态平稳，未检测到变动",
                score=1.0,
            )

        items_summary = "\n".join(
            [f"- 【{item['name']}】({item['url']}): {item['summary']}" for item in changed_targets]
        )

        system_prompt = (
            "你是 MaoWu「猫老」，一位傲娇毒舌的老中医兼全天候哨兵，自称「老夫」。\n"
            "你刚刚替用户巡检了他交代你盯盘的网站，发现其中有网站发生了更新变动，你主动发一条【网站情报变动预警】。\n"
            "要求：\n"
            "1. 毒舌傲娇，提醒他赶紧去瞅一眼最新变动，别又后知后觉像个睁眼瞎；\n"
            "2. 清晰列出变动的网站名称与变动摘要；\n"
            "3. 保持老夫口吻，字数 80~150 字以内。"
        )

        user_prompt = f"变动的监控目标：\n{items_summary}"

        llm = self._get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        content = str(response.content).strip()
        return ProactiveDecision(
            should_trigger=True,
            topic="web_watcher_alert",
            content=content,
            reason=f"监控哨兵检测到 {len(changed_targets)} 个目标发生内容更新",
            score=9.5,
        )

