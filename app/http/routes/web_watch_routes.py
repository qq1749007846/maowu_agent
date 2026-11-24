from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.web_watcher_service import get_web_watcher_service

logger = logging.getLogger(__name__)

web_watch_router = APIRouter(prefix="/api/v1/web-watch", tags=["Web Watcher & Scraper"])


class FetchReq(BaseModel):
    url: str
    selector: str = ""
    max_chars: int = 4000


class TargetCreateReq(BaseModel):
    name: str
    url: str
    user_id: str = "default_user"
    selector: str = ""
    check_interval_hours: int = 4


@web_watch_router.post("/fetch")
async def fetch_web_page(req: FetchReq) -> dict[str, Any]:
    """即时抓取并清洗网页内容"""
    service = get_web_watcher_service()
    clean_url = req.url.strip()
    if not clean_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL 必须以 http:// 或 https:// 开头")

    result = service.fetch_content(url=clean_url, selector=req.selector, max_chars=req.max_chars)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=f"抓取失败: {result.get('error')}")
    return result


@web_watch_router.get("/targets")
async def list_targets(
    user_id: str = "default_user",
    status: str = "active",
) -> dict[str, Any]:
    """获取指定用户的网页监控目标列表"""
    service = get_web_watcher_service()
    targets = service.list_watch_targets(user_id=user_id, status=status)
    return {"total": len(targets), "targets": targets}


@web_watch_router.post("/targets")
async def add_target(req: TargetCreateReq) -> dict[str, Any]:
    """添加新的网页变动监控哨兵"""
    service = get_web_watcher_service()
    clean_url = req.url.strip()
    if not clean_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL 必须以 http:// 或 https:// 开头")

    item = service.add_watch_target(
        user_id=req.user_id,
        name=req.name.strip() or clean_url,
        url=clean_url,
        selector=req.selector.strip(),
        check_interval_hours=req.check_interval_hours,
    )
    return {"message": "监控目标创建成功", "target": item}


@web_watch_router.delete("/targets/{target_id}")
async def delete_target(target_id: str) -> dict[str, Any]:
    """删除或取消网页监控目标"""
    service = get_web_watcher_service()
    ok = service.remove_watch_target(target_id)
    if not ok:
        raise HTTPException(status_code=404, detail="未找到指定的监控目标")
    return {"message": f"目标 {target_id} 已成功注销"}


@web_watch_router.post("/targets/{target_id}/check")
async def check_single_target(target_id: str) -> dict[str, Any]:
    """立刻触发单个目标的差异检测"""
    service = get_web_watcher_service()
    result = service.check_target(target_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "检查失败"))
    return result


@web_watch_router.post("/check-all")
async def check_all_targets(user_id: str = "default_user") -> dict[str, Any]:
    """巡检所有活跃的监控目标"""
    service = get_web_watcher_service()
    changed = service.check_all_due(user_id=user_id)
    return {
        "changed_count": len(changed),
        "changed_targets": changed,
        "message": f"巡检完成，发现 {len(changed)} 个目标内容更新",
    }
