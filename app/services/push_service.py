from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
import json
import logging
import os
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from app.proactive.scheduler import ProactiveMessage

logger = logging.getLogger(__name__)


class PushRecord(BaseModel):
    """主动推送记录对象"""
    id: str = Field(default_factory=lambda: f"push_{uuid4().hex[:8]}")
    user_id: str
    title: str
    content: str
    channel: str = "astrbot"  # astrbot, webhook, internal
    target: str = ""
    status: str = "pending"  # sent, failed, buffered
    error: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    latency_ms: float = 0.0


class OutboundPushService:
    """第五阶段：多端主动触达与外呼推送服务 (Outbound Push Service)
    
    职责：
    1. 监听 ProactiveScheduler 主动决策事件，将复盘问候、晨间待办、哨兵告警主动推送到外部平台；
    2. 支持 AstrBot API 直连推送（微信/QQ）、通用 Webhook（企业微信/钉钉/飞书）及沙箱模拟测试；
    3. 维护内存级外呼历史队列，供 Web 前端与诊断探针实时监控触达状态。
    """

    def __init__(
        self,
        astrbot_url: str | None = None,
        webhook_url: str | None = None,
        default_target: str = "default_user",
        history_limit: int = 100,
    ) -> None:
        # 默认优先尝试内网 Docker 网桥地址，若无则使用公网或 localhost
        self.astrbot_url = astrbot_url or os.getenv("ASTRBOT_API_URL", "http://172.17.0.1:6185").rstrip("/")
        self.webhook_url = webhook_url or os.getenv("PUSH_WEBHOOK_URL", "")
        self.default_target = default_target or os.getenv("ASTRBOT_PUSH_TARGET", "default_user")
        self._history: deque[PushRecord] = deque(maxlen=history_limit)
        self.enabled = os.getenv("PUSH_ENABLED", "true").lower() == "true"

    async def on_proactive_message(self, msg: ProactiveMessage) -> None:
        """作为 ProactiveScheduler 的订阅者，收到主动关怀消息后触发外呼推送"""
        logger.info(f"PushService received proactive message: {msg.title} (topic={msg.topic})")
        await self.push_message(
            user_id=msg.user_id,
            title=msg.title,
            content=msg.content,
            channel="auto",
        )

    async def push_message(
        self,
        user_id: str,
        title: str,
        content: str,
        target: str | None = None,
        channel: str = "auto",
    ) -> PushRecord:
        """执行主动外呼推送"""
        target_id = target or self.default_target or user_id
        record = PushRecord(
            user_id=user_id,
            title=title,
            content=content,
            channel=channel,
            target=target_id,
        )

        if not self.enabled:
            record.status = "buffered"
            record.error = "Push disabled via PUSH_ENABLED=false"
            self._history.append(record)
            return record

        t0 = asyncio.get_event_loop().time()
        delivered = False
        last_error = ""

        # 1. 尝试通过 AstrBot API 推送 (微信 / QQ)
        if channel in ["auto", "astrbot"] and self.astrbot_url:
            astrbot_ok, err = await self._push_to_astrbot(target_id, title, content)
            if astrbot_ok:
                delivered = True
                record.channel = "astrbot"
            else:
                last_error = f"AstrBot push failed: {err}"

        # 2. 如果配置了通用 Webhook 且尚未成功，尝试 Webhook
        if not delivered and (channel in ["auto", "webhook"] or self.webhook_url):
            if self.webhook_url:
                webhook_ok, err = await self._push_to_webhook(title, content, target_id)
                if webhook_ok:
                    delivered = True
                    record.channel = "webhook"
                else:
                    last_error = (last_error + " | " + err) if last_error else err

        duration = (asyncio.get_event_loop().time() - t0) * 1000
        record.latency_ms = round(duration, 2)

        if delivered:
            record.status = "sent"
            record.error = None
            logger.info(f"Successfully pushed message '{title}' to {target_id} via {record.channel}")
        else:
            # 若外部 API 暂时未连通，转为内部缓冲成功，防止阻断主业务流程
            record.status = "buffered"
            record.error = last_error or "All external outbound endpoints unavailable, stored in buffer"
            logger.warning(f"Outbound push buffered for '{title}': {record.error}")

        self._history.append(record)
        return record

    async def _push_to_astrbot(self, target: str, title: str, content: str) -> tuple[bool, str]:
        """向 AstrBot API 发送消息推流"""
        endpoints = [
            f"{self.astrbot_url}/api/message/send",
            f"{self.astrbot_url}/api/v1/message/send",
            f"{self.astrbot_url}/v1/chat/completions",
        ]
        formatted_msg = f"🔔 *【{title}】*\n\n{content}\n\n*—— 来自 MaoWu（猫老）坐诊室*"
        payload = {
            "target": target,
            "user_id": target,
            "message": formatted_msg,
            "content": formatted_msg,
        }

        async with httpx.AsyncClient(timeout=3.5) as client:
            for url in endpoints[:2]:
                try:
                    res = await client.post(url, json=payload)
                    if res.status_code in [200, 201]:
                        return True, ""
                except Exception as e:
                    last_e = str(e)
            return False, f"HTTP request failed: {last_e if 'last_e' in locals() else 'Connection refused'}"

    async def _push_to_webhook(self, title: str, content: str, target: str) -> tuple[bool, str]:
        """向企业微信/钉钉/飞书/自定义 Webhook 推送 Markdown 消息"""
        if not self.webhook_url:
            return False, "No webhook_url configured"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"### {title}\n\n{content}\n\n> 🎯 目标用户: {target} · 诊断源: MaoWu Agent",
            },
        }
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(self.webhook_url, json=payload)
                if res.status_code in [200, 204]:
                    return True, ""
                return False, f"Webhook returned status {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, f"Webhook error: {e}"

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """获取最近主动推送外呼历史"""
        records = list(self._history)[-limit:]
        records.reverse()
        return [r.model_dump() for r in records]

    def get_config(self) -> dict[str, Any]:
        """查看当前推送配置概况"""
        return {
            "enabled": self.enabled,
            "astrbot_url": self.astrbot_url,
            "has_webhook": bool(self.webhook_url),
            "default_target": self.default_target,
            "buffered_count": len(self._history),
        }


# 全局单例
_push_service = OutboundPushService()


def get_push_service() -> OutboundPushService:
    """获取外呼推送服务全局单例"""
    return _push_service
