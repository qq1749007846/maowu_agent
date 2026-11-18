from __future__ import annotations

import asyncio
import pytest

from app.subagents.dispatcher import TaskTicket
from app.subagents.researcher import DeepResearcherAgent


@pytest.mark.asyncio
async def test_deep_researcher_agent():
    """测试深度技术调研子代理：生成结构化选型架构报告"""
    researcher = DeepResearcherAgent()

    ticket = TaskTicket(
        task_type="deep_research",
        user_id="user_research_test",
        payload={
            "topic": "FastAPI 与 Go Gin 在微服务架构下的高并发选型对比",
            "focus": "I/O 密集型异步处理、协程开销、工程维护成本",
            "system_context": "当前系统为 LangGraph Agent 网关，需要承载大量长连接 SSE 流式请求",
        },
    )

    result = await researcher.execute_research(ticket)
    print("Researcher result status:", result.get("status"))

    assert result.get("status") == "success"
    report = result.get("report", "")
    assert len(report) > 100
    assert "FastAPI" in report or "Gin" in report
