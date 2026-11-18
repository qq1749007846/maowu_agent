from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.proactive import get_proactive_scheduler

logger = logging.getLogger(__name__)

proactive_router = APIRouter(prefix="/api/v1/proactive", tags=["Proactive Mentoring"])


class ProactiveTriggerRequest(BaseModel):
    user_id: str = Field(default="mazikang", description="目标用户 ID")
    trigger_type: Literal["auto", "weekly_review", "blocker_followup"] = Field(
        default="auto",
        description="触发场景：auto (自动研判), weekly_review (周五复盘), blocker_followup (排障跟进)",
    )
    force: bool = Field(default=False, description="是否强制触发（跳过静默与冷却校验）")


class ProactiveAckRequest(BaseModel):
    user_id: str = Field(default="mazikang")
    message_id: str = Field(..., description="消息 ID")
    action: Literal["read", "dismiss"] = Field(default="read", description="处理操作")


@proactive_router.get("/messages")
async def get_proactive_messages(
    user_id: str = Query("mazikang", description="用户 ID"),
    unread_only: bool = Query(False, description="是否仅获取未读"),
) -> dict[str, Any]:
    """获取指定用户的主动关怀/复盘提醒消息"""
    scheduler = get_proactive_scheduler()
    messages = scheduler.get_messages(user_id=user_id, unread_only=unread_only)
    return {
        "status": "success",
        "user_id": user_id,
        "total": len(messages),
        "messages": [m.model_dump() for m in messages],
    }


@proactive_router.post("/trigger")
async def trigger_proactive_evaluation(
    request: ProactiveTriggerRequest,
) -> dict[str, Any]:
    """手动或外部事件驱动主动复盘评估"""
    scheduler = get_proactive_scheduler()
    msg = await scheduler.trigger_check(
        user_id=request.user_id,
        trigger_type=request.trigger_type,
        force=request.force,
    )
    if msg:
        return {
            "status": "triggered",
            "message": "主动关怀决策已通过并生成",
            "proactive_message": msg.model_dump(),
        }
    return {
        "status": "skipped",
        "message": "当前处于防打扰冷却时段或意愿评分未达标",
    }


@proactive_router.post("/ack")
async def acknowledge_proactive_message(
    request: ProactiveAckRequest,
) -> dict[str, Any]:
    """标记主动消息状态（已读或已忽略）"""
    scheduler = get_proactive_scheduler()
    if request.action == "read":
        ok = scheduler.mark_message_read(request.user_id, request.message_id)
    else:
        ok = scheduler.dismiss_message(request.user_id, request.message_id)

    return {
        "status": "success" if ok else "not_found",
        "message_id": request.message_id,
        "action": request.action,
        "updated": ok,
    }


@proactive_router.get("/status")
async def get_proactive_status(
    user_id: str = Query("mazikang", description="用户 ID"),
) -> dict[str, Any]:
    """查询用户的防打扰状态与未读消息统计"""
    scheduler = get_proactive_scheduler()
    guard = scheduler.cooldown_guard
    is_quiet = guard.is_quiet_hours()
    can_contact, reason = guard.can_contact(user_id)
    unread_msgs = scheduler.get_messages(user_id, unread_only=True)

    return {
        "user_id": user_id,
        "is_quiet_hours": is_quiet,
        "can_contact": can_contact,
        "guard_reason": reason,
        "unread_count": len(unread_msgs),
        "quiet_hours_range": f"{guard.quiet_hours_start}:00 - {guard.quiet_hours_end}:{guard.quiet_minutes_end:02d}",
        "cooldown_hours": guard.cooldown_hours,
        "max_daily_contacts": guard.max_daily_contacts,
    }
