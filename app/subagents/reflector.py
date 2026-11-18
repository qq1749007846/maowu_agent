from __future__ import annotations

import json
import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.models.memory import EpisodicMemory, MemoryCategory, UserProfile
from app.services.ltm_service import LTMService
from app.subagents.dispatcher import TaskTicket

logger = logging.getLogger(__name__)


class BackgroundReflectorAgent:
    """记忆沉淀与反思子代理 (Memory Consolidator & Reflector)
    职责：
    1. 异步分析对话内容，提取其中的【技术踩坑与故障排障】、【架构经验】、【技术画像变化】；
    2. 静默将提取后的结构化经验持久化到 LTM (data/ltm.db)，无需用户手动录入；
    3. 在新旧技术认知冲突时，进行反思去重与版本演进。
    """

    def __init__(self, ltm_service: LTMService | None = None) -> None:
        self.ltm_service = ltm_service or LTMService()
        self.llm = ChatOpenAI(
            model=os.getenv("DEFAULT_MODEL", "openai/deepseek-v4-pro").split("/")[-1],
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_API_BASE", "https://model-api.datagrand.com/v1"),
            temperature=0.2,  # 抽取提炼任务使用低温度保障结构稳定
        )

    async def reflect_and_consolidate(self, ticket: TaskTicket) -> dict[str, Any]:
        """执行记忆沉淀与反思"""
        user_id = ticket.user_id
        conversation = ticket.payload.get("conversation", "")
        if not conversation:
            return {"status": "skipped", "reason": "empty conversation"}

        system_prompt = (
            "你是一个技术记忆沉淀分析器。请仔细阅读用户与技术导师的对话，判断其中是否包含有价值的技术沉淀信息。\n"
            "如果有，请以严格的 JSON 格式输出，不要包含任何 markdown 标记之外的内容。\n"
            "JSON 结构定义：\n"
            "{\n"
            "  \"has_valuable_memory\": true/false,\n"
            "  \"troubleshooting\": [\n"
            "    {\n"
            "      \"title\": \"简明故障标题\",\n"
            "      \"context\": \"问题背景与现象\",\n"
            "      \"root_cause\": \"技术根因\",\n"
            "      \"resolution\": \"解决步骤\",\n"
            "      \"reflection\": \"经验启示\",\n"
            "      \"tags\": [\"标签1\", \"标签2\"]\n"
            "    }\n"
            "  ],\n"
            "  \"profile_updates\": {\n"
            "    \"primary_languages\": [\"新增主力语言\"],\n"
            "    \"tech_stack\": [\"新增技术栈\"]\n"
            "  }\n"
            "}\n"
            "若无明显技术经验沉淀，则设置 has_valuable_memory 为 false。"
        )

        response = await self.llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"对话内容如下：\n{conversation}"),
        ])

        raw_content = str(response.content).strip()
        # 清理可能存在的 ```json 标记
        if raw_content.startswith("```json"):
            raw_content = raw_content[7:]
        if raw_content.startswith("```"):
            raw_content = raw_content[3:]
        if raw_content.endswith("```"):
            raw_content = raw_content[:-3]
        raw_content = raw_content.strip()

        try:
            data = json.loads(raw_content)
        except Exception as exc:
            logger.warning(f"Failed to parse LLM reflection output: {exc}. Content: {raw_content[:100]}")
            return {"status": "parse_error", "raw": raw_content}

        if not data.get("has_valuable_memory"):
            return {"status": "no_memory_extracted"}

        saved_memories = []
        # 1. 沉淀排障踩坑记忆
        for item in data.get("troubleshooting", []):
            memory = EpisodicMemory(
                user_id=user_id,
                category=MemoryCategory.TROUBLESHOOTING,
                title=item.get("title", "未命名排障"),
                context=item.get("context", ""),
                root_cause=item.get("root_cause", ""),
                resolution=item.get("resolution", ""),
                reflection=item.get("reflection", ""),
                tags=item.get("tags", []),
                importance=4,
            )
            self.ltm_service.add_episodic_memory(memory)
            saved_memories.append(memory.title)
            logger.info(f"Reflector saved episodic memory: {memory.title} for user {user_id}")

        # 2. 演进更新用户技术画像
        profile_updates = data.get("profile_updates", {})
        new_langs = profile_updates.get("primary_languages", [])
        new_stacks = profile_updates.get("tech_stack", [])
        if new_langs or new_stacks:
            profile = self.ltm_service.get_user_profile(user_id)
            updated = False
            for lang in new_langs:
                if lang and lang not in profile.primary_languages:
                    profile.primary_languages.append(lang)
                    updated = True
            for stack in new_stacks:
                if stack and stack not in profile.tech_stack:
                    profile.tech_stack.append(stack)
                    updated = True
            if updated:
                self.ltm_service.save_user_profile(profile)
                logger.info(f"Reflector updated user profile for user {user_id}")

        return {
            "status": "success",
            "saved_memories": saved_memories,
            "profile_updates": profile_updates,
        }
