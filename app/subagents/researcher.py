from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.subagents.dispatcher import TaskTicket

logger = logging.getLogger(__name__)


class DeepResearcherAgent:
    """深度技术调研子代理 (Deep Researcher Worker)
    职责：
    1. 承担耗时的技术架构方案深度对比（如：FastAPI vs Go Gin 吞吐量对比、Postgres vs Milvus 向量选型）；
    2. 开源技术难点分析与方案深挖；
    3. 生成结构化调研报告，避免主交互前台发生长时间阻塞。
    """

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=os.getenv("DEFAULT_MODEL", "openai/deepseek-v4-pro").split("/")[-1],
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_API_BASE", "https://model-api.datagrand.com/v1"),
            temperature=0.3,
        )

    async def execute_research(self, ticket: TaskTicket) -> dict[str, Any]:
        """执行耗时的深度技术调研任务"""
        user_id = ticket.user_id
        topic = ticket.payload.get("topic", "")
        focus = ticket.payload.get("focus", "")
        system_context = ticket.payload.get("system_context", "")

        if not topic:
            return {"status": "failed", "reason": "empty topic"}

        logger.info(f"DeepResearcherAgent started research on '{topic}' for user {user_id}")

        system_prompt = (
            "你是一个资深架构师兼技术调研专家。你正在为工程师团队出具一份严谨、客观、具备可落地性的深度技术调研报告。\n"
            "调研报告必须包含以下板块：\n"
            "1. 【背景与核心痛点分析】\n"
            "2. 【主流技术/架构选型横向对比矩阵】（包含优缺点、性能体感、维护成本与踩坑风险）\n"
            "3. 【针对业务系统的推荐落地策略与迁移路径】\n"
            "4. 【潜在陷阱与最佳实践踩坑防护指引】\n"
            "风格务实硬核，注重原理与真实生产场景，拒绝套话。"
        )

        user_content = f"调研主题：{topic}\n攻坚侧重点：{focus}\n当前业务系统架构背景：{system_context}"

        response = await self.llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])

        report = str(response.content).strip()
        logger.info(f"DeepResearcherAgent completed research on '{topic}'. Report length: {len(report)}")

        return {
            "status": "success",
            "topic": topic,
            "report": report,
            "user_id": user_id,
        }
