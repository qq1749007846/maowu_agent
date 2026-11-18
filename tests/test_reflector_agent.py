from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from app.models.memory import MemoryCategory
from app.services.ltm_service import LTMService
from app.subagents.dispatcher import TaskTicket
from app.subagents.reflector import BackgroundReflectorAgent


@pytest.mark.asyncio
async def test_reflector_agent_extracts_troubleshooting_memory(tmp_path: Path):
    """测试反思子代理：能否从实际排障对话中自动提取根因/方案并静默写入 LTM"""
    test_db = str(tmp_path / "test_ltm.db")
    ltm = LTMService(db_path=test_db)
    reflector = BackgroundReflectorAgent(ltm_service=ltm)

    user_id = "user_reflector_test"
    conversation = (
        "用户: 刚才在生产环境部署时，Redis 连接池突然抛出 TimeoutError，排查发现是连接没归还导致泄露了。\n"
        "导师: 了解，连接池泄露很典型。解决方案是在每个获取连接的地方加上 try...finally 确保 conn.release() 释放。\n"
        "用户: 搞定了，加上 finally 块并把 max_connections 从 10 调到 50 后恢复正常了，记录一下。"
    )

    ticket = TaskTicket(
        task_type="memory_consolidation",
        user_id=user_id,
        payload={"conversation": conversation},
    )

    result = await reflector.reflect_and_consolidate(ticket)
    print("Reflector result:", result)

    assert result.get("status") == "success"

    # 验证是否静默持久化到了 LTM 数据库
    memories = ltm.search_episodic_memories(user_id=user_id, query="Redis 连接池 泄露")
    assert len(memories) > 0
    first_mem = memories[0]
    assert first_mem.category == MemoryCategory.TROUBLESHOOTING
    assert "redis" in first_mem.title.lower() or "连接" in first_mem.title or "redis" in "".join(first_mem.tags).lower()
