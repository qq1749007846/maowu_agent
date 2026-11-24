from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.container import Container
from app.models import Thread, User
from app.subagents import dispatcher

logger = logging.getLogger(__name__)

astrbot_router = APIRouter(tags=["AstrBot-Integration"])


class AstrBotChatRequest(BaseModel):
    """专属 AstrBot 快捷聊天请求"""
    user_id: str = Field(default="qq_user", description="QQ 或外部用户唯一标识")
    message: str = Field(description="用户提问内容")
    thread_id: str | None = Field(default=None, description="会话ID（可选）")


class OpenAIMessage(BaseModel):
    model_config = {"extra": "allow"}
    role: str = "user"
    content: Any = ""


def _extract_content(content: Any) -> str:
    """安全解析不同格式的 message content（支持纯文本、多模态数组等）"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    if content is None:
        return ""
    return str(content)


class OpenAIChatRequest(BaseModel):
    """标准 OpenAI ChatCompletions 兼容请求（AstrBot 原生支持）"""
    model_config = {"extra": "allow"}
    model: str = "deepseek-v4.1-flash"
    messages: list[OpenAIMessage] = Field(default_factory=list)
    stream: bool = False
    user: str | None = None


class SubAgentTaskSubmitRequest(BaseModel):
    """提交异步子代理任务（如深度架构调研）"""
    task_type: str = Field(default="deep_research", description="任务类型：deep_research / memory_consolidation")
    user_id: str = Field(default="default_user", description="用户ID")
    payload: dict[str, Any] = Field(default_factory=dict, description="任务参数")


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
        elif event_name == "tool_call":
            data_raw = event.get("data")
            tool_name = ""
            if data_raw:
                try:
                    tool_data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
                    tool_name = tool_data.get("name", "")
                except Exception:
                    pass
            tool_desc = {
                "fetch_web_content": "正在抓取网页内容与清洗降噪",
                "execute_python": "正在沙箱中执行 Python 数据处理脚本",
                "manage_workspace_files": "正在操作工作区文件",
                "manage_todo": "正在读写个人待办事项",
                "manage_notes": "正在检索备忘录与技术笔记",
                "manage_web_watch": "正在配置与巡检网站监控哨兵",
                "sql_db_query": "正在执行业务数据库安全查询",
            }.get(tool_name, f"正在执行工具 [{tool_name}]")
            yield f"\n\n> ⚙️ *【猫老正在动手】{tool_desc}...*\n\n"
        elif event_name == "error":
            logger.error(f"Agent error event: {event.get('data')}")



# ========================================================
# 1. 标准 OpenAI 兼容端点（AstrBot 在 WebUI 无插件直接填入）
# ========================================================
@astrbot_router.get("/v1/models")
@astrbot_router.get("/models")
async def list_models() -> dict[str, Any]:
    """返回标准 OpenAI 格式的模型列表，供 AstrBot 等客户端探活与拉取模型"""
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": "deepseek-v4.1-flash",
                "object": "model",
                "created": now,
                "owned_by": "codebuddy",
            },
            {
                "id": "deepseek-v4-pro",
                "object": "model",
                "created": now,
                "owned_by": "codebuddy",
            },
            {
                "id": "maowu-agent",
                "object": "model",
                "created": now,
                "owned_by": "maowu",
            },
            {
                "id": "openai/deepseek-v4.1-flash",
                "object": "model",
                "created": now,
                "owned_by": "codebuddy",
            },
        ],
    }


@astrbot_router.post("/v1/chat/completions")
@astrbot_router.post("/chat/completions")
async def openai_chat_completions(req: OpenAIChatRequest, background_tasks: BackgroundTasks) -> Any:
    """
    提供标准 OpenAI 格式的 /v1/chat/completions 端点
    AstrBot 的 LLM 提供商选择 OpenAI 兼容协议，填入 http://maowu-agent:8000/v1 即可直连！
    并在对话完成后自动派发异步记忆沉淀子代理。
    """
    last_user_msg = ""
    for msg in reversed(req.messages):
        extracted = _extract_content(msg.content).strip()
        if msg.role == "user" and extracted:
            last_user_msg = extracted
            break

    if not last_user_msg:
        last_user_msg = "你好"

    user_id = req.user or "qq_user"
    completion_id = f"chatcmpl-{uuid4().hex[:12]}"
    created_time = int(time.time())

    # 流式输出
    if req.stream:
        async def stream_generator():
            collected_tokens = []
            async for token in _run_maowu_agent(user_id=user_id, prompt=last_user_msg):
                collected_tokens.append(token)
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

            # 异步触发反思子代理
            full_conv = f"用户: {last_user_msg}\n导师: {''.join(collected_tokens)}"
            await dispatcher.submit_task("memory_consolidation", user_id, {"conversation": full_conv})

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    # 非流式输出
    full_tokens: list[str] = []
    async for token in _run_maowu_agent(user_id=user_id, prompt=last_user_msg):
        full_tokens.append(token)

    reply_content = "".join(full_tokens).strip()

    # 异步触发反思子代理
    full_conv = f"用户: {last_user_msg}\n导师: {reply_content}"
    background_tasks.add_task(
        dispatcher.submit_task,
        "memory_consolidation",
        user_id,
        {"conversation": full_conv},
    )

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
async def astrbot_simple_chat(req: AstrBotChatRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """专属快捷接口：传入 user_id 与 message，返回技术导师思考后的回答，并异步沉淀记忆"""
    full_tokens: list[str] = []
    async for token in _run_maowu_agent(user_id=req.user_id, prompt=req.message, thread_id=req.thread_id):
        full_tokens.append(token)

    reply = "".join(full_tokens).strip()

    # 异步沉淀记忆
    full_conv = f"用户: {req.message}\n导师: {reply}"
    background_tasks.add_task(
        dispatcher.submit_task,
        "memory_consolidation",
        req.user_id,
        {"conversation": full_conv},
    )

    return {
        "status": "success",
        "user_id": req.user_id,
        "reply": reply,
    }


# ========================================================
# 3. 异步子代理任务管理接口（工单派发与状态查询）
# ========================================================
@astrbot_router.post("/api/v1/subagents/tasks")
async def submit_subagent_task(req: SubAgentTaskSubmitRequest) -> dict[str, Any]:
    """派发耗时异步任务（如 deep_research 深度技术调研）"""
    ticket = await dispatcher.submit_task(req.task_type, req.user_id, req.payload)
    return {
        "status": "accepted",
        "task_id": ticket.task_id,
        "task_type": ticket.task_type,
        "user_id": ticket.user_id,
        "task_status": ticket.status.value,
        "created_at": ticket.created_at.isoformat(),
    }


@astrbot_router.get("/api/v1/subagents/tasks/{task_id}")
async def get_subagent_task(task_id: str) -> dict[str, Any]:
    """查询异步子代理任务的执行进度与调研报告结果"""
    ticket = dispatcher.get_task(task_id)
    if not ticket:
        return {"status": "not_found", "task_id": task_id}

    return {
        "task_id": ticket.task_id,
        "task_type": ticket.task_type,
        "user_id": ticket.user_id,
        "task_status": ticket.status.value,
        "result": ticket.result,
        "error": ticket.error,
        "created_at": ticket.created_at.isoformat(),
        "completed_at": ticket.completed_at.isoformat() if ticket.completed_at else None,
    }
