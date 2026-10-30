from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.container import Container
from app.models import Thread, User

logger = logging.getLogger(__name__)

astrbot_router = APIRouter(tags=["AstrBot-Integration"])


class AstrBotChatRequest(BaseModel):
    """专属 AstrBot 快捷聊天请求"""
    user_id: str = Field(default="qq_user", description="QQ 或外部用户唯一标识")
    message: str = Field(description="用户提问内容")
    thread_id: str | None = Field(default=None, description="会话ID（可选）")


class OpenAIMessage(BaseModel):
    role: str
    content: str


class OpenAIChatRequest(BaseModel):
    """标准 OpenAI ChatCompletions 兼容请求（AstrBot 原生支持）"""
    model: str = "deepseek-v4-pro"
    messages: list[OpenAIMessage]
    stream: bool = False
    user: str | None = None


async def _run_maowu_agent(user_id: str, prompt: str, thread_id: str | None = None) -> AsyncGenerator[str, None]:
    """底层调用 MaoWu Agent 运行时，流式生成回答"""
    real_thread_id = thread_id or f"astrbot_thread_{user_id}"
    agent_user = User(id=user_id, email=f"{user_id}@qq.com")
    agent_thread = Thread(id=real_thread_id, user_id=user_id)

    container = Container()
    agent_factory = container.agent_factory()
    agent = await agent_factory.create_agent("demo_agent")

    async for event in agent.stream_response(message=prompt, thread=agent_thread, user=agent_user):
        event_name = event.get("event")
        if event_name == "token":
            data_raw = event.get("data")
            if data_raw:
                try:
                    token_obj = json.loads(data_raw)
                    content = token_obj.get("content", "")
                    if content:
                        yield content
                except Exception:
                    pass
        elif event_name == "error":
            logger.error(f"Agent error event: {event.get('data')}")


# ========================================================
# 1. 标准 OpenAI 兼容端点（AstrBot 在 WebUI 无插件直接填入）
# ========================================================
@astrbot_router.post("/v1/chat/completions")
async def openai_chat_completions(req: OpenAIChatRequest) -> Any:
    """
    提供标准 OpenAI 格式的 /v1/chat/completions 端点
    AstrBot 的 LLM 提供商选择 OpenAI 兼容协议，填入 http://localhost:8000/v1 即可直连！
    """
    # 提取用户最新提问
    last_user_msg = ""
    for msg in reversed(req.messages):
        if msg.role == "user" and msg.content.strip():
            last_user_msg = msg.content.strip()
            break

    if not last_user_msg:
        last_user_msg = "你好"

    user_id = req.user or "qq_user"
    completion_id = f"chatcmpl-{uuid4().hex[:12]}"
    created_time = int(time.time())

    # 流式输出
    if req.stream:
        async def stream_generator():
            async for token in _run_maowu_agent(user_id=user_id, prompt=last_user_msg):
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": req.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": token},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            # 结束标志
            done_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": req.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(done_chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    # 非流式输出
    full_tokens: list[str] = []
    async for token in _run_maowu_agent(user_id=user_id, prompt=last_user_msg):
        full_tokens.append(token)

    reply_content = "".join(full_tokens).strip()

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_time,
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply_content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(last_user_msg),
            "completion_tokens": len(reply_content),
            "total_tokens": len(last_user_msg) + len(reply_content),
        },
    }


# ========================================================
# 2. 专属简洁端点（适合 AstrBot 插件或 Webhook 自定义调用）
# ========================================================
@astrbot_router.post("/api/v1/astrbot/chat")
async def astrbot_simple_chat(req: AstrBotChatRequest) -> dict[str, Any]:
    """专属快捷接口：传入 user_id 与 message，返回技术导师思考后的回答"""
    full_tokens: list[str] = []
    async for token in _run_maowu_agent(user_id=req.user_id, prompt=req.message, thread_id=req.thread_id):
        full_tokens.append(token)

    return {
        "status": "success",
        "user_id": req.user_id,
        "reply": "".join(full_tokens).strip(),
    }
