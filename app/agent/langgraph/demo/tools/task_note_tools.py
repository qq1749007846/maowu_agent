from __future__ import annotations

import json
from typing import Any
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.services.task_note_service import get_task_note_service


class TodoInput(BaseModel):
    action: str = Field(description="操作动作：create（新建待办）、list（查询待办列表）、complete（标记完成）、update（修改待办）、delete（删除待办）")
    title: str = Field(default="", description="待办任务标题或主要内容")
    priority: str = Field(default="", description="优先级：high（高优）、medium（中等）、low（低优），留空则表示不限或使用默认")
    status: str = Field(default="", description="任务状态过滤或修改：pending（待办）、in_progress（进行中）、done（已完成），留空表示不限")
    due_date: str = Field(default="", description="截止时间，如 '2026-11-25 18:00' 或 '今日下班前'")
    task_id: str = Field(default="", description="任务唯一标识 ID（在 complete/update/delete 时必填）")
    description: str = Field(default="", description="详细说明或补充备注")
    user_id: str = Field(default="default_user", description="用户ID，默认从会话上下文读取")


class TodoManagementTool(BaseTool):
    name: str = "manage_todo"
    description: str = (
        "管理私人待办事项 (TODO)。"
        "支持动作：create（创建待办）、list（查看待办清单，支持按状态/优先级排序）、"
        "complete（快捷标记某任务为已完成）、update（修改内容或状态）、delete（删除待办）。"
    )
    args_schema: type[BaseModel] = TodoInput

    def _run(
        self,
        action: str,
        title: str = "",
        priority: str = "",
        status: str = "",
        due_date: str = "",
        task_id: str = "",
        description: str = "",
        user_id: str = "default_user",
        **kwargs: Any,
    ) -> str:
        service = get_task_note_service()
        clean_action = action.lower().strip()

        if clean_action == "create":
            if not title.strip():
                return "错误：创建待办必须提供 title 标题。"
            task = service.create_task(
                user_id=user_id,
                title=title,
                description=description,
                priority=priority,
                due_date=due_date,
            )
            return (
                f"【待办已创建】\n"
                f"- ID: {task['id']}\n"
                f"- 标题: {task['title']}\n"
                f"- 优先级: {task['priority'].upper()}\n"
                f"- 截止时间: {task['due_date'] or '未指定'}"
            )

        elif clean_action == "list":
            filter_status = status.strip() if status.strip() else None
            filter_priority = priority.strip() if priority.strip() in ["high", "medium", "low"] else None
            tasks = service.list_tasks(user_id=user_id, status=filter_status, priority=filter_priority)
            if not tasks:
                status_desc = f" [{filter_status}]" if filter_status else ""
                return f"当前暂无待办任务{status_desc}。"

            lines = ["【私人待办清单】:"]
            for idx, t in enumerate(tasks, start=1):
                pri_tag = "🔴 [高]" if t["priority"] == "high" else ("🟡 [中]" if t["priority"] == "medium" else "🟢 [低]")
                status_tag = "✅ 已完成" if t["status"] == "done" else ("⏳ 进行中" if t["status"] == "in_progress" else "📌 待办")
                due_str = f" | 截止: {t['due_date']}" if t["due_date"] else ""
                lines.append(f"{idx}. {pri_tag} {status_tag} {t['title']} (ID: {t['id']}{due_str})")
            return "\n".join(lines)

        elif clean_action == "complete":
            if not task_id.strip():
                return "错误：complete 动作必须提供 task_id。"
            res = service.update_task(task_id=task_id.strip(), user_id=user_id, status="done")
            if res:
                return f"成功：待办任务 '{res['title']}' (ID: {task_id}) 已标记为已完成！"
            return f"错误：未找到 ID 为 '{task_id}' 的待办任务。"

        elif clean_action == "update":
            if not task_id.strip():
                return "错误：update 动作必须提供 task_id。"
            res = service.update_task(
                task_id=task_id.strip(),
                user_id=user_id,
                title=title if title else None,
                description=description if description else None,
                priority=priority if priority else None,
                status=status if status else None,
                due_date=due_date if due_date else None,
            )
            if res:
                return f"成功：待办任务 '{res['title']}' (ID: {task_id}) 更新成功！"
            return f"错误：未找到 ID 为 '{task_id}' 的待办任务。"

        elif clean_action == "delete":
            if not task_id.strip():
                return "错误：delete 动作必须提供 task_id。"
            ok = service.delete_task(task_id=task_id.strip(), user_id=user_id)
            if ok:
                return f"成功：已从数据库删除待办任务 (ID: {task_id})。"
            return f"错误：未找到 ID 为 '{task_id}' 的待办任务。"

        else:
            return f"错误：不支持的 action '{action}'。支持: create, list, complete, update, delete。"

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


class NoteInput(BaseModel):
    action: str = Field(description="操作动作：save（保存或更新备忘）、search（搜索备忘）、get（查看单条）、delete（删除备忘）")
    title: str = Field(default="", description="备忘录标题")
    content: str = Field(default="", description="备忘正文内容或重要信息")
    category: str = Field(default="", description="分类：config（配置）、server（服务器/运维）、idea（灵感/想法）、general（日常），留空表示不限分类")
    tags: str = Field(default="", description="逗号分隔的标签，如 'mysql,prod,password'")
    keyword: str = Field(default="", description="搜索关键词（在 search 动作时使用）")
    note_id: str = Field(default="", description="备忘唯一标识 ID（在 get/delete 或更新时使用）")
    user_id: str = Field(default="default_user", description="用户ID")


class NoteManagementTool(BaseTool):
    name: str = "manage_notes"
    description: str = (
        "管理私人工作备忘录 (Notes)。"
        "随时随地记录重要信息（服务器配置、账户密码、灵感想法、踩坑记录等），"
        "并支持快速按关键词检索、分类查询与读取。"
    )
    args_schema: type[BaseModel] = NoteInput

    def _run(
        self,
        action: str,
        title: str = "",
        content: str = "",
        category: str = "",
        tags: str = "",
        keyword: str = "",
        note_id: str = "",
        user_id: str = "default_user",
        **kwargs: Any,
    ) -> str:
        service = get_task_note_service()
        clean_action = action.lower().strip()

        if clean_action == "save":
            if not title.strip() or not content.strip():
                return "错误：保存备忘必须提供 title 和 content。"
            note = service.save_note(
                user_id=user_id,
                title=title,
                content=content,
                category=category.strip() if category.strip() else "general",
                tags=tags,
                note_id=note_id if note_id.strip() else None,
            )
            return (
                f"【备忘已安全归档】\n"
                f"- ID: {note['id']}\n"
                f"- 标题: {note['title']}\n"
                f"- 分类: [{note['category']}]\n"
                f"- 标签: {note['tags'] or '无'}"
            )

        elif clean_action == "search":
            notes = service.search_notes(user_id=user_id, keyword=keyword, category=category)
            if not notes:
                return f"未找到匹配的备忘记录 (关键词: '{keyword}', 分类: '{category}')。"
            lines = [f"找到 {len(notes)} 条备忘记录:"]
            for idx, n in enumerate(notes, start=1):
                preview = n['content'][:60] + ("..." if len(n['content']) > 60 else "")
                lines.append(f"{idx}. [{n['category'].upper()}] {n['title']} (ID: {n['id']})\n   摘要: {preview}")
            return "\n".join(lines)

        elif clean_action == "get":
            if not note_id.strip():
                return "错误：get 动作必须提供 note_id。"
            note = service.get_note(note_id=note_id.strip(), user_id=user_id)
            if not note:
                return f"未找到 ID 为 '{note_id}' 的备忘。"
            return (
                f"【备忘详情】\n"
                f"标题: {note['title']}\n"
                f"分类: {note['category']} | 标签: {note['tags']}\n"
                f"更新时间: {note['updated_at']}\n\n"
                f"内容:\n{note['content']}"
            )

        elif clean_action == "delete":
            if not note_id.strip():
                return "错误：delete 动作必须提供 note_id。"
            ok = service.delete_note(note_id=note_id.strip(), user_id=user_id)
            if ok:
                return f"成功：已从数据库删除备忘 (ID: {note_id})。"
            return f"错误：未找到 ID 为 '{note_id}' 的备忘。"

        else:
            return f"错误：不支持的 action '{action}'。支持: save, search, get, delete。"

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)
