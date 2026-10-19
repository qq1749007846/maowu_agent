from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    """长期情境记忆类型"""
    TROUBLESHOOTING = "troubleshooting"  # 技术踩坑与故障排障记录
    CAREER_EVENT = "career_event"        # 职场节点（答辩、晋升、跳槽、面试、周报）
    TECH_INSIGHT = "tech_insight"        # 架构选型反思与技术顿悟
    LEARNING_PROGRESS = "learning"       # 技能学习路线推进与知识吸收


class ProjectContext(BaseModel):
    """用户负责的核心业务系统/项目上下文"""
    name: str = Field(description="项目或系统名称")
    architecture: str = Field(description="架构简述与关键技术选型")
    current_focus: str = Field(default="", description="当前攻坚重点或难点")


class CareerGoal(BaseModel):
    """用户的职业与技能成长目标"""
    goal: str = Field(description="目标描述（如：半年内精通分布式事务与高并发调优）")
    deadline: str = Field(default="", description="期望达成周期")
    status: str = Field(default="in_progress", description="当前状态: in_progress, achieved, paused")


class UserProfile(BaseModel):
    """用户技术画像与职场档案（长期实体记忆）"""
    user_id: str = Field(description="用户唯一ID")
    primary_languages: list[str] = Field(default_factory=list, description="主力编程语言")
    tech_stack: list[str] = Field(default_factory=list, description="常用框架与中间件")
    projects: list[ProjectContext] = Field(default_factory=list, description="正在维护或开发的核心系统")
    goals: list[CareerGoal] = Field(default_factory=list, description="职业目标与近期OKR")
    communication_style: str = Field(default="注重原理、思路清晰、杜绝空话", description="沟通偏好")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="最后更新时间")


class EpisodicMemory(BaseModel):
    """情节记忆（踩坑复盘日记、职场事件时光轴）"""
    id: str = Field(default_factory=lambda: str(uuid4()), description="记忆项唯一ID")
    user_id: str = Field(description="所属用户ID")
    category: MemoryCategory = Field(description="记忆分类")
    title: str = Field(description="简要标题（例如：Windows下psycopg缺libpq导致启动报错）")
    context: str = Field(description="发生背景与问题表现")
    root_cause: str = Field(default="", description="技术根因或核心矛盾")
    resolution: str = Field(default="", description="最终解决方案或应对措施")
    reflection: str = Field(default="", description="复盘启示与导师总结经验")
    tags: list[str] = Field(default_factory=list, description="检索标签，如 ['postgres', 'windows', 'driver']")
    importance: int = Field(default=3, ge=1, le=5, description="重要度权重 (1-5)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="记录时间戳")


class SemanticKnowledge(BaseModel):
    """语义知识卡片（技能沉淀、架构经验库）"""
    id: str = Field(default_factory=lambda: str(uuid4()), description="知识卡片唯一ID")
    user_id: str = Field(description="所属用户ID")
    topic: str = Field(description="知识主题（例如：LangGraph状态机循环设计规范）")
    summary: str = Field(description="核心概念与经验提炼")
    code_snippet: str | None = Field(default=None, description="关键示例代码或配置片段")
    references: list[str] = Field(default_factory=list, description="关联文档或源码URL")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkingMemoryContext(BaseModel):
    """工作记忆装配输出：注入单次模型对话上下文的工作台"""
    user_profile_summary: str = Field(default="", description="当前用户核心画像浓缩")
    relevant_memories: list[EpisodicMemory] = Field(default_factory=list, description="针对当前问题召回的Top-K相关历史排障/复盘记忆")
    active_scratchpad: str = Field(default="", description="当前正在进行的待办/排障暂存现场")
    persona_prompt_modifier: str = Field(default="", description="当前导师情绪与羁绊微调提示词")
