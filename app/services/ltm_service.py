from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models.memory import EpisodicMemory, MemoryCategory, UserProfile
from app.models.persona import IntimacyLevel, MentorTone, PersonaState, UserEmotion

logger = logging.getLogger(__name__)


class LTMService:
    """长期记忆与拟人化状态持久化服务（Long-Term Memory Service）"""

    def __init__(self, db_path: str = "data/ltm.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """初始化长期记忆 SQLite 数据库表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memories (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    context TEXT NOT NULL,
                    root_cause TEXT,
                    resolution TEXT,
                    reflection TEXT,
                    tags TEXT,
                    importance INTEGER DEFAULT 3,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_user_cat 
                ON episodic_memories (user_id, category)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS persona_states (
                    user_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    # --- 用户画像管理 ---
    def get_user_profile(self, user_id: str) -> UserProfile:
        """获取用户技术与职场档案"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT profile_json FROM user_profiles WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return UserProfile.model_validate_json(row["profile_json"])

        # 若未找到，返回默认初始画像
        return UserProfile(user_id=user_id)

    def save_user_profile(self, profile: UserProfile) -> None:
        """保存或更新用户技术与职场档案"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_profiles (user_id, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.user_id,
                    profile.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()

    # --- 排障踩坑情节记忆管理 ---
    def add_episodic_memory(self, memory: EpisodicMemory) -> None:
        """保存一条排障踩坑或关键成长记忆"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO episodic_memories (
                    id, user_id, category, title, context,
                    root_cause, resolution, reflection, tags, importance, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    context = excluded.context,
                    root_cause = excluded.root_cause,
                    resolution = excluded.resolution,
                    reflection = excluded.reflection,
                    tags = excluded.tags,
                    importance = excluded.importance
                """,
                (
                    memory.id,
                    memory.user_id,
                    memory.category.value,
                    memory.title,
                    memory.context,
                    memory.root_cause,
                    memory.resolution,
                    memory.reflection,
                    json.dumps(memory.tags, ensure_ascii=False),
                    memory.importance,
                    memory.created_at.isoformat(),
                ),
            )
            conn.commit()

    def search_episodic_memories(
        self, user_id: str, query: str, category: MemoryCategory | None = None, top_k: int = 3
    ) -> list[EpisodicMemory]:
        """
        根据用户输入，结合关键词匹配、标签关联与重要度加权混合召回最相关的排障记忆
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute(
                    "SELECT * FROM episodic_memories WHERE user_id = ? AND category = ?",
                    (user_id, category.value),
                )
            else:
                cursor.execute(
                    "SELECT * FROM episodic_memories WHERE user_id = ?",
                    (user_id,),
                )
            rows = cursor.fetchall()

        if not rows:
            return []

        # 简单的多维度加权打分匹配
        query_tokens = set(query.lower().split())
        scored_memories: list[tuple[float, EpisodicMemory]] = []

        for row in rows:
            tags = json.loads(row["tags"]) if row["tags"] else []
            mem = EpisodicMemory(
                id=row["id"],
                user_id=row["user_id"],
                category=MemoryCategory(row["category"]),
                title=row["title"],
                context=row["context"],
                root_cause=row["root_cause"] or "",
                resolution=row["resolution"] or "",
                reflection=row["reflection"] or "",
                tags=tags,
                importance=row["importance"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )

            # 计算匹配分
            score = 0.0
            # 1. 基础分：重要度加权
            score += mem.importance * 1.5

            # 2. 标签匹配
            for t in tags:
                if t.lower() in query.lower():
                    score += 5.0

            # 3. 标题与关键词重合度
            title_lower = mem.title.lower()
            context_lower = mem.context.lower()
            for token in query_tokens:
                if len(token) > 1:
                    if token in title_lower:
                        score += 3.0
                    if token in context_lower:
                        score += 1.0

            scored_memories.append((score, mem))

        # 按打分降序排列，取 Top-K
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored_memories[:top_k]]

    # --- 拟人化状态管理 ---
    def get_persona_state(self, user_id: str) -> PersonaState:
        """获取当前与该用户的拟人化状态"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT state_json FROM persona_states WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return PersonaState.model_validate_json(row["state_json"])

        # 默认初始状态
        return PersonaState()

    def save_persona_state(self, user_id: str, state: PersonaState) -> None:
        """持久化保存与该用户的拟人化状态"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO persona_states (user_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    state.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
