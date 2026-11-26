from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.push_service import get_push_service
from app.services.weekly_review_service import get_weekly_review_service

logger = logging.getLogger(__name__)

phase5_router = APIRouter(prefix="/api/v1", tags=["Phase 5: Push & Weekly Reviews"])


class ReviewGenerateReq(BaseModel):
    user_id: str = "default_user"
    auto_push: bool = Field(default=False, description="生成后是否自动推送到外部渠道（微信/群聊/Webhook）")


class PushTestReq(BaseModel):
    user_id: str = "default_user"
    title: str = "MaoWu 测试脉案推送"
    content: str = "这是一条来自 MaoWu Agent 第五阶段外呼推送通道的连通性校验测试！"
    target: str | None = None
    channel: str = "auto"  # auto, astrbot, webhook, internal


# ==========================================
# 1. 周度技术体检与复盘报告 API
# ==========================================
@phase5_router.post("/review/generate")
async def generate_weekly_review(req: ReviewGenerateReq) -> dict[str, Any]:
    """触发生成《周度技术体检与复盘报告》，并支持一键外呼推送至微信/群聊"""
    service = get_weekly_review_service()
    report = await service.generate_weekly_report(user_id=req.user_id, auto_push=req.auto_push)
    return {"status": "success", "report": report}


@phase5_router.get("/review/latest")
async def get_latest_review(user_id: str = "default_user") -> dict[str, Any]:
    """获取最新一份周度技术体检报告概要"""
    service = get_weekly_review_service()
    report = service.get_latest_report(user_id=user_id)
    if not report:
        return {"status": "empty", "message": "暂无生成的周报，请先调用 /api/v1/review/generate 生成"}
    return {"status": "success", "report": report}


@phase5_router.get("/review/history")
async def list_review_history() -> dict[str, Any]:
    """查看所有历史生成的周度体检报告文件清单"""
    service = get_weekly_review_service()
    items = service.list_history()
    return {"status": "success", "total": len(items), "reports": items}


@phase5_router.get("/profile/skills")
async def get_user_skill_radar(user_id: str = "default_user") -> dict[str, Any]:
    """查询用户五维技术能力雷达评估与成长画像"""
    service = get_weekly_review_service()
    radar = service.get_skill_radar(user_id=user_id)
    return {"status": "success", "skills": radar}


# ==========================================
# 2. 多端主动推送通道 API
# ==========================================
@phase5_router.post("/push/test")
async def test_outbound_push(req: PushTestReq) -> dict[str, Any]:
    """主动推送测试接口：验证 AstrBot/微信 或 Webhook 的连通性"""
    push_svc = get_push_service()
    record = await push_svc.push_message(
        user_id=req.user_id,
        title=req.title,
        content=req.content,
        target=req.target,
        channel=req.channel,
    )
    return {"status": "success", "push_record": record.model_dump()}


@phase5_router.get("/push/history")
async def get_push_history(limit: int = 50) -> dict[str, Any]:
    """获取主动外呼推送历史记录清单"""
    push_svc = get_push_service()
    records = push_svc.get_history(limit=limit)
    return {"status": "success", "total": len(records), "records": records}


@phase5_router.get("/push/config")
async def get_push_config() -> dict[str, Any]:
    """获取当前主动外呼推送配置概要"""
    push_svc = get_push_service()
    return {"status": "success", "config": push_svc.get_config()}
