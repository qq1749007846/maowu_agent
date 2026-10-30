from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel

from app.container import Container
from app.models import Thread, User

logger = logging.getLogger(__name__)

qq_router = APIRouter(prefix="/qq", tags=["QQ-Bot"])

# NapCat / OneBot 协议端监听地址（默认 http://127.0.0.1:3000）
NAPCAT_HTTP_URL = os.getenv("NAPCAT_HTTP_URL", "http://127.0.0.1:3000").rstrip("/")


def clean_cq_codes(text: str) -> str:
    """清理 QQ CQ码（如 [CQ:at,qq=123456]）"""
    return re.sub(r"\[CQ:[^\]]+\]", "", text).strip()


async def process_qq_message(
    message_type: str,
    user_id: int,
    raw_message: str,
    group_id: int | None = None,
) -> None:
    """后台异步处理 QQ 消息并调用 MaoWu Agent 回复"""
    clean_msg = clean_cq_codes(raw_message)
    if not clean_msg:
        logger.info("Empty message after cleaning CQ codes, skipping.")
        return

    logger.info(f"Processing QQ message from {user_id} in {message_type}: {clean_msg}")

    # 1. 映射为 MaoWu Agent 身份与会话
    agent_user_id = f"qq_{user_id}"
    thread_id = f"qq_group_{group_id}" if message_type == "group" else f"qq_private_{user_id}"

    user = User(id=agent_user_id, email=f"{user_id}@qq.com")
    thread = Thread(id=thread_id, user_id=agent_user_id)

    # 2. 调用 MaoWu Agent 运行时（自动触发 WMA 记忆装配与 DeepSeek 导师推理）
    try:
        container = Container()
        agent_factory = container.agent_factory()
        agent = await agent_factory.create_agent("demo_agent")

        reply_tokens: list[str] = []
        async for event in agent.stream_response(message=clean_msg, thread=thread, user=user):
            event_name = event.get("event")
            if event_name == "token":
                data_raw = event.get("data")
                if data_raw:
                    try:
                        token_obj = json.loads(data_raw)
                        reply_tokens.append(token_obj.get("content", ""))
                    except Exception:
                        pass
            elif event_name == "error":
                logger.error(f"Agent error event: {event.get('data')}")

        full_reply = "".join(reply_tokens).strip()
        if not full_reply:
            full_reply = "【MaoWu 提示】未能成功生成回复，请稍后重试。"

        logger.info(f"Agent generated reply for {user_id}: {full_reply[:60]}...")

        # 3. 将结果推回给 NapCat 发送到 QQ
        target_url = f"{NAPCAT_HTTP_URL}/send_msg"
        payload: dict[str, Any] = {
            "message_type": message_type,
            "message": f"[CQ:at,qq={user_id}]\n{full_reply}" if message_type == "group" else full_reply,
        }
        if message_type == "group":
            payload["group_id"] = group_id
        else:
            payload["user_id"] = user_id

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(target_url, json=payload)
            if resp.status_code == 200:
                logger.info(f"Successfully sent reply to QQ {user_id} via NapCat.")
            else:
                logger.warning(f"NapCat returned status {resp.status_code}: {resp.text}")

    except Exception as exc:
        logger.exception("Error processing QQ message: %s", exc)


@qq_router.post("/webhook")
async def qq_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    """
    NapCat HTTP 上报 / Webhook 接收端
    支持 OneBot v11 协议标准
    """
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "message": "invalid json"}

    post_type = payload.get("post_type")

    # 1. 忽略元事件（心跳包、生命周期等）
    if post_type == "meta_event":
        return {"status": "ok"}

    # 2. 处理消息事件
    if post_type == "message":
        self_id = payload.get("self_id")
        user_id = payload.get("user_id")
        message_type = payload.get("message_type")  # "private" or "group"
        raw_message = payload.get("raw_message", "") or payload.get("message", "")
        group_id = payload.get("group_id")

        # 忽略机器人自己发送的消息，防止死循环
        if user_id == self_id:
            return {"status": "ignored"}

        # 如果是群聊，判断是否被 @ 或者以“导师/MaoWu”开头唤醒
        if message_type == "group":
            is_at_bot = f"[CQ:at,qq={self_id}]" in str(raw_message)
            is_keyword = any(k in str(raw_message) for k in ["导师", "MaoWu", "maowu"])
            if not (is_at_bot or is_keyword):
                # 普通群聊未唤醒机器人，跳过不处理
                return {"status": "ignored"}

        # 提交后台异步处理，立即返回 200 给 NapCat，防止超时重试
        background_tasks.add_task(
            process_qq_message,
            message_type=message_type,
            user_id=user_id,
            raw_message=str(raw_message),
            group_id=group_id,
        )
        return {"status": "ok"}

    return {"status": "ignored"}
