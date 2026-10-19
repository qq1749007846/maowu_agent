from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pydantic import BaseModel, Field


class MentorTone(str, Enum):
    """导师语气模式"""
    PRACTICAL_INSIGHTFUL = "practical_insightful"  # 沉稳务实、富有启发性（默认日常技术探讨）
    CRISIS_CALM = "crisis_calm"                    # 紧急故障排查时冷静定心、直击要害
    WARM_SUPPORTIVE = "warm_supportive"            # 面对职场焦虑/倦怠时温和共情、深度倾听
    LIGHT_HUMOROUS = "light_humorous"              # 攻关顺利或闲聊时适度幽默解压


class UserEmotion(str, Enum):
    """用户当前情绪状态感知"""
    CALM = "calm"                            # 平和、专注
    ANXIOUS_BLOCKED = "anxious_blocked"      # 技术卡壳、焦虑急躁
    EXHAUSTED = "exhausted"                  # 熬夜攻坚、身心疲惫
    EXCITED_SOLVED = "excited_solved"        # 难题攻克、兴奋自豪


class IntimacyLevel(str, Enum):
    """羁绊与信任度阶梯"""
    ACQUAINTANCE = "acquaintance"            # 初识阶梯（客气、严谨的技术导师）
    FAMILIAR = "familiar"                    # 熟悉阶梯（了解对方技术背景，称呼亲近，探讨深入）
    TRUSTED_COMPANION = "trusted_companion"  # 默契战友（无话不谈，深刻懂得彼此技术偏好与职业理想）


class PersonaState(BaseModel):
    """动态拟人化状态模型"""
    intimacy_score: int = Field(default=10, description="羁绊/信任积分 (0-100)")
    intimacy_level: IntimacyLevel = Field(default=IntimacyLevel.ACQUAINTANCE, description="当前羁绊等级")
    current_tone: MentorTone = Field(default=MentorTone.PRACTICAL_INSIGHTFUL, description="当前响应语气基调")
    detected_emotion: UserEmotion = Field(default=UserEmotion.CALM, description="最新检测到的用户情绪")
    interaction_rounds: int = Field(default=0, description="累计交互轮次")
    last_active_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="最近交互时间")

    def get_persona_prompt_modifier(self) -> str:
        """根据当前情绪与羁绊状态动态生成注入 System Prompt 的微调指令"""
        tone_instructions = {
            MentorTone.PRACTICAL_INSIGHTFUL: "保持沉稳务实且有启发性的技术专家口吻，不废话，引导用户从根本原理思考。",
            MentorTone.CRISIS_CALM: "用户当前可能面临紧急线上或卡点问题，保持极度冷静，优先给出条理清晰、最最小风险的排查和止血方案。",
            MentorTone.WARM_SUPPORTIVE: "感知到用户情绪低落或职场压力，优先给予情感共情与正向肯定，像值得信赖的前辈一样温和交谈，杜绝机械化讲大道理。",
            MentorTone.LIGHT_HUMOROUS: "气氛融洽，可适当融入程序员圈子的幽默，语言轻松随和。",
        }

        intimacy_instructions = {
            IntimacyLevel.ACQUAINTANCE: "保持专业礼貌，认真了解对方的技术背景与工作上下文。",
            IntimacyLevel.FAMILIAR: "双方已有较多技术交集，对话更加直接熟络，适时主动提及过往讨论过的技术议题。",
            IntimacyLevel.TRUSTED_COMPANION: "如同多年并肩作战的老战友与懂你的导师，充满信任感与默契。",
        }

        return (
            f"【导师当前状态指引】\n"
            f"- 语气调优：{tone_instructions.get(self.current_tone, '')}\n"
            f"- 关系羁绊（{self.intimacy_level.value}）：{intimacy_instructions.get(self.intimacy_level, '')}\n"
            f"- 用户当前情绪感应：{self.detected_emotion.value}。"
        )
