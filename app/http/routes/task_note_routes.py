from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.task_note_service import get_task_note_service

logger = logging.getLogger(__name__)

task_note_router = APIRouter(prefix="/api/v1", tags=["Tasks & Notes"])


class TaskCreateReq(BaseModel):
    user_id: str = "default_user"
    title: str
    description: str = ""
    priority: str = "medium"
    due_date: str = ""


class TaskUpdateReq(BaseModel):
    user_id: str = "default_user"
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    status: str | None = None
    due_date: str | None = None


class NoteSaveReq(BaseModel):
    user_id: str = "default_user"
    title: str
    content: str
    category: str = "general"
    tags: str = ""
    note_id: str | None = None


# ==========================================
# 待办任务 (Tasks) API
# ==========================================
@task_note_router.get("/tasks")
async def get_tasks(
    user_id: str = "default_user",
    status: str | None = None,
    priority: str | None = None,
    limit: int = 20,
):
    service = get_task_note_service()
    tasks = service.list_tasks(user_id=user_id, status=status, priority=priority, limit=limit)
    return {"status": "success", "user_id": user_id, "tasks": tasks}


@task_note_router.post("/tasks")
async def create_task(req: TaskCreateReq):
    service = get_task_note_service()
    task = service.create_task(
        user_id=req.user_id,
        title=req.title,
        description=req.description,
        priority=req.priority,
        due_date=req.due_date,
    )
    return {"status": "created", "task": task}


@task_note_router.patch("/tasks/{task_id}")
async def update_task(task_id: str, req: TaskUpdateReq):
    service = get_task_note_service()
    res = service.update_task(
        task_id=task_id,
        user_id=req.user_id,
        title=req.title,
        description=req.description,
        priority=req.priority,
        status=req.status,
        due_date=req.due_date,
    )
    if not res:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {"status": "updated", "task": res}


@task_note_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user_id: str = "default_user"):
    service = get_task_note_service()
    ok = service.delete_task(task_id=task_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {"status": "deleted", "task_id": task_id}


# ==========================================
# 个人备忘录 (Notes) API
# ==========================================
@task_note_router.get("/notes")
async def get_notes(
    user_id: str = "default_user",
    keyword: str = "",
    category: str = "",
    limit: int = 15,
):
    service = get_task_note_service()
    notes = service.search_notes(user_id=user_id, keyword=keyword, category=category, limit=limit)
    return {"status": "success", "user_id": user_id, "notes": notes}


@task_note_router.post("/notes")
async def save_note(req: NoteSaveReq):
    service = get_task_note_service()
    note = service.save_note(
        user_id=req.user_id,
        title=req.title,
        content=req.content,
        category=req.category,
        tags=req.tags,
        note_id=req.note_id,
    )
    return {"status": "saved", "note": note}


@task_note_router.get("/notes/{note_id}")
async def get_single_note(note_id: str, user_id: str = "default_user"):
    service = get_task_note_service()
    note = service.get_note(note_id=note_id, user_id=user_id)
    if not note:
        raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found")
    return {"status": "success", "note": note}


@task_note_router.delete("/notes/{note_id}")
async def delete_note(note_id: str, user_id: str = "default_user"):
    service = get_task_note_service()
    ok = service.delete_note(note_id=note_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found")
    return {"status": "deleted", "note_id": note_id}
