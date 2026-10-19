from __future__ import annotations

import logging
from typing import Any

from app.models.memory import WorkingMemoryContext
from app.services.ltm_service import LTMService

logger = logging.getLogger(__name__)


class WorkingMemoryAssembler:
    """工作记忆装配引擎（Working Memory Assembler）
    在模型推理前瞬间，动态调取长期画像、相关排障记录与拟人化状态，组装当前工作台。
    """

    def __init__(self, ltm_service: LTMService | None = None) -> None:
        self.ltm_service = ltm_service or LTMService()

    def assemble(self, user_id: str, current_query: str) -> WorkingMemoryContext:
        """针对当前输入动态装配工作记忆"""
        # 1. 获取用户技术画像
        profile = self.ltm_service.get_user_profile(user_id)
        profile_summary_parts: list[str] = []
        if profile.primary_languages:
            profile_summary_parts.append(f"主力语言: {', '.join(profile.primary_languages)}")
        if profile.tech_stack:
            profile_summary_parts.append(f"常用技术栈: {', '.join(profile.tech_stack)}")
        if profile.projects:
            proj_str = "; ".join([f"{p.name}({p.architecture})" for p in profile.projects])
            profile_summary_parts.append(f"核心负责系统: {proj_str}")
        if profile.goals:
            goals_str = "; ".join([g.goal for g in profile.goals])
            profile_summary_parts.append(f"成长目标: {goals_str}")

        profile_summary = " | ".join(profile_summary_parts)

        # 2. 混合检索与当前问题最相关的排障/踩坑经验 (Top-2)
        relevant_memories = self.ltm_service.search_episodic_memories(
            user_id=user_id,
            query=current_query,
            top_k=2,
        )

        # 3. 获取拟人化状态微调指令
        persona_state = self.ltm_service.get_persona_state(user_id)
        persona_modifier = persona_state.get_persona_prompt_modifier()

        return WorkingMemoryContext(
            user_profile_summary=profile_summary,
            relevant_memories=relevant_memories,
            persona_prompt_modifier=persona_modifier,
        )

    def format_to_prompt_block(self, context: WorkingMemoryContext) -> str:
        """将装配好的工作记忆格式化为注入 System Prompt 的精炼文本块"""
        blocks: list[str] = []

        # 注入用户技术画像
        if context.user_profile_summary:
            blocks.append(f"【用户技术与项目档案】\n{context.user_profile_summary}")

        # 注入历史排障踩坑联想
        if context.relevant_memories:
            mem_blocks: list[str] = []
            for idx, mem in enumerate(context.relevant_memories, 1):
                mem_blocks.append(
                    f"{idx}. 历史排障/经验：[{mem.title}]\n"
                    f"   - 根因：{mem.root_cause}\n"
                    f"   - 方案：{mem.resolution}\n"
                    f"   - 复盘心得：{mem.reflection}"
                )
            blocks.append("【相关历史排障与踩坑记忆】\n" + "\n".join(mem_blocks))

        # 注入当前导师情绪与羁绊微调
        if context.persona_prompt_modifier:
            blocks.append(context.persona_prompt_modifier)

        if not blocks:
            return ""

        return "\n\n" + "\n\n".join(blocks)
