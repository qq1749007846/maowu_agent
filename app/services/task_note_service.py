from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskNoteService:
    """私人工作待办 (TODO) 与工作备忘录持久化管理服务 (基于 SQLite)"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path:
            self.db_path = Path(db_path).resolve()
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.db_path = (project_root / "data" / "ltm.db").resolve()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. 待办任务表 (personal_tasks)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS personal_tasks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    priority TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'pending',
                    due_date TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    completed_at TEXT DEFAULT ''
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_user_status 
                ON personal_tasks (user_id, status)
            """)

            # 2. 个人备忘录表 (personal_notes)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS personal_notes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notes_user_cat 
                ON personal_notes (user_id, category)
            """)
            conn.commit()

    # ==========================================
    # 待办任务 (TODO) 管理方法
    # ==========================================
    def create_task(
        self,
        user_id: str,
        title: str,
        description: str = "",
        priority: str = "medium",
        due_date: str = "",
    ) -> dict[str, Any]:
        """创建新待办任务"""
        task_id = f"task_{uuid4().hex[:8]}"
        now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        clean_priority = priority.lower() if priority.lower() in ["high", "medium", "low"] else "medium"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO personal_tasks 
                (id, user_id, title, description, priority, status, due_date, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (task_id, user_id, title.strip(), description.strip(), clean_priority, due_date.strip(), now_str),
            )
            conn.commit()

        return {
            "id": task_id,
            "title": title.strip(),
            "description": description.strip(),
            "priority": clean_priority,
            "status": "pending",
            "due_date": due_date.strip(),
            "created_at": now_str,
        }

    def list_tasks(
        self,
        user_id: str,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """查询待办任务列表，默认按优先级 (high > medium > low) 及创建时间倒序排列"""
        query = "SELECT * FROM personal_tasks WHERE user_id = ?"
        params: list[Any] = [user_id]

        if status:
            query += " AND status = ?"
            params.append(status.strip())

        if priority:
            query += " AND priority = ?"
            params.append(priority.strip().lower())

        # 排序：high 优先，同级按创建时间
        query += """
            ORDER BY 
                CASE priority 
                    WHEN 'high' THEN 1 
                    WHEN 'medium' THEN 2 
                    WHEN 'low' THEN 3 
                    ELSE 4 
                END ASC,
                created_at DESC
            LIMIT ?
        """
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def update_task(
        self,
        task_id: str,
        user_id: str,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        due_date: str | None = None,
    ) -> dict[str, Any] | None:
        """更新待办任务状态、优先级或内容"""
        updates = []
        params: list[Any] = []

        if title is not None:
            updates.append("title = ?")
            params.append(title.strip())
        if description is not None:
            updates.append("description = ?")
            params.append(description.strip())
        if priority is not None and priority.lower() in ["high", "medium", "low"]:
            updates.append("priority = ?")
            params.append(priority.lower())
        if due_date is not None:
            updates.append("due_date = ?")
            params.append(due_date.strip())
        if status is not None:
            clean_status = status.strip().lower()
            updates.append("status = ?")
            params.append(clean_status)
            if clean_status == "done":
                updates.append("completed_at = ?")
                params.append(datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))

        if not updates:
            return None

        params.extend([task_id, user_id])
        query = f"UPDATE personal_tasks SET {', '.join(updates)} WHERE id = ? AND user_id = ?"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            if cursor.rowcount == 0:
                return None

            cursor.execute("SELECT * FROM personal_tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_task(self, task_id: str, user_id: str) -> bool:
        """删除指定待办任务"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM personal_tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ==========================================
    # 个人工作备忘录 (Notes) 管理方法
    # ==========================================
    def save_note(
        self,
        user_id: str,
        title: str,
        content: str,
        category: str = "general",
        tags: str = "",
        note_id: str | None = None,
    ) -> dict[str, Any]:
        """保存或更新工作备忘录"""
        now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        nid = note_id or f"note_{uuid4().hex[:8]}"
        clean_cat = category.strip().lower() if category.strip() else "general"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 检查是否已存在
            cursor.execute("SELECT id FROM personal_notes WHERE id = ? AND user_id = ?", (nid, user_id))
            exists = cursor.fetchone() is not None

            if exists:
                cursor.execute(
                    """
                    UPDATE personal_notes 
                    SET title = ?, content = ?, category = ?, tags = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (title.strip(), content.strip(), clean_cat, tags.strip(), now_str, nid, user_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO personal_notes 
                    (id, user_id, category, title, content, tags, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (nid, user_id, clean_cat, title.strip(), content.strip(), tags.strip(), now_str, now_str),
                )
            conn.commit()

        return {
            "id": nid,
            "category": clean_cat,
            "title": title.strip(),
            "content": content.strip(),
            "tags": tags.strip(),
            "updated_at": now_str,
        }

    def search_notes(
        self,
        user_id: str,
        keyword: str = "",
        category: str = "",
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        """搜索工作备忘录（支持标题、内容、标签或分类多维过滤）"""
        query = "SELECT * FROM personal_notes WHERE user_id = ?"
        params: list[Any] = [user_id]

        if category:
            query += " AND category = ?"
            params.append(category.strip().lower())

        if keyword:
            query += " AND (title LIKE ? OR content LIKE ? OR tags LIKE ?)"
            kw_pattern = f"%{keyword.strip()}%"
            params.extend([kw_pattern, kw_pattern, kw_pattern])

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def get_note(self, note_id: str, user_id: str) -> dict[str, Any] | None:
        """获取单个备忘详情"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM personal_notes WHERE id = ? AND user_id = ?",
                (note_id, user_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_note(self, note_id: str, user_id: str) -> bool:
        """删除指定备忘"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM personal_notes WHERE id = ? AND user_id = ?",
                (note_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0


# 全局单例工厂
_task_note_service: TaskNoteService | None = None


def get_task_note_service() -> TaskNoteService:
    global _task_note_service
    if _task_note_service is None:
        _task_note_service = TaskNoteService()
    return _task_note_service
