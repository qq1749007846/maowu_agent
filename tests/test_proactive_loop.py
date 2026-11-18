from __future__ import annotations

import asyncio
from datetime import datetime
import pytest
from httpx import ASGITransport, AsyncClient

from app.bootstrap.app_factory import create_app
from app.bootstrap.config import AppConfig
from app.models.memory import EpisodicMemory, MemoryCategory, UserProfile
from app.proactive.cooldown import CooldownGuard
from app.proactive.decider import ProactiveDecider
from app.proactive.scheduler import ProactiveMessage, ProactiveScheduler
from app.services.ltm_service import LTMService


class TestCooldownGuard:
    """测试防打扰与冷却守卫"""

    def test_quiet_hours_detection(self):
        guard = CooldownGuard(quiet_hours_start=23, quiet_hours_end=8, quiet_minutes_end=30)
        # 23:15 应该在静默时段
        dt_night = datetime(2026, 11, 20, 23, 15)
        assert guard.is_quiet_hours(dt_night) is True

        # 07:00 应该在静默时段
        dt_early = datetime(2026, 11, 20, 7, 0)
        assert guard.is_quiet_hours(dt_early) is True

        # 08:35 应该已过静默时段
        dt_morning = datetime(2026, 11, 20, 8, 35)
        assert guard.is_quiet_hours(dt_morning) is False

        # 14:00 工作日下午不在静默时段
        dt_afternoon = datetime(2026, 11, 20, 14, 0)
        assert guard.is_quiet_hours(dt_afternoon) is False

    def test_contact_frequency_and_cooldown(self):
        guard = CooldownGuard(cooldown_hours=4.0, max_daily_contacts=2)
        guard.reset_history()
        user = "test_user"

        t1 = datetime(2026, 11, 20, 10, 0)
        can, reason = guard.can_contact(user, current_dt=t1)
        assert can is True

        # 记录第一次触达
        guard.record_contact(user, contact_dt=t1)

        # 1 小时后再次触达，应被冷却期拦截 (4h)
        t2 = datetime(2026, 11, 20, 11, 0)
        can, reason = guard.can_contact(user, current_dt=t2)
        assert can is False
        assert "冷却期" in reason

        # 5 小时后 (15:00)，应允许第二次触达
        t3 = datetime(2026, 11, 20, 15, 0)
        can, reason = guard.can_contact(user, current_dt=t3)
        assert can is True
        guard.record_contact(user, contact_dt=t3)

        # 6 小时后 (21:00)，由于已达到每日上限 2 次，应被拦截
        t4 = datetime(2026, 11, 20, 21, 0)
        can, reason = guard.can_contact(user, current_dt=t4)
        assert can is False
        assert "上限" in reason


@pytest.mark.asyncio
class TestProactiveScheduler:
    """测试主动事件调度器与决策流"""

    async def test_scheduler_trigger_and_subscribers(self, tmp_path):
        db_path = str(tmp_path / "ltm_test.db")
        ltm = LTMService(db_path=db_path)
        # 初始化测试用户与排障记录
        user_id = "test_dev_01"
        profile = UserProfile(user_id=user_id)
        profile.projects = []
        ltm.save_user_profile(profile)

        mem = EpisodicMemory(
            user_id=user_id,
            category=MemoryCategory.TROUBLESHOOTING,
            title="Redis连接池泄露排查",
            context="生产高并发场景连接数耗尽",
            root_cause="未显式 release 连接导致挂死",
            resolution="引入上下文管理器自动回收",
        )
        ltm.add_episodic_memory(mem)

        guard = CooldownGuard()
        scheduler = ProactiveScheduler(
            cooldown_guard=guard,
            ltm_service=ltm,
            check_interval_seconds=600,
        )

        # 订阅回调验证
        received_messages: list[ProactiveMessage] = []

        async def sub_callback(msg: ProactiveMessage):
            received_messages.append(msg)

        scheduler.subscribe(sub_callback)

        # 启动调度器并手动 force 触发
        await scheduler.start()
        assert scheduler._running is True

        msg = await scheduler.trigger_check(user_id, trigger_type="weekly_review", force=True)
        assert msg is not None
        assert msg.user_id == user_id
        assert msg.topic == "weekly_review"
        assert len(msg.content) > 0
        assert len(received_messages) == 1

        # 验证消息列表与状态修改
        all_msgs = scheduler.get_messages(user_id)
        assert len(all_msgs) == 1

        scheduler.mark_message_read(user_id, msg.id)
        unread = scheduler.get_messages(user_id, unread_only=True)
        assert len(unread) == 0

        scheduler.dismiss_message(user_id, msg.id)
        assert scheduler.get_messages(user_id)[0].status == "dismissed"

        await scheduler.stop()
        assert scheduler._running is False


from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


class TestProactiveHTTPRoutes:
    """测试主动对话与防打扰 API 接口"""

    def test_proactive_api_endpoints(self):
        config = AppConfig()
        app = create_app(config)

        mock_msg = ProactiveMessage(
            id="mock-msg-001",
            user_id="test_api_user",
            topic="weekly_review",
            title="周五技术复盘与周末充电关怀",
            content="这周生产排障很稳，周末好好充电！",
            reason="测试主动复盘",
            score=9.0,
        )

        with patch("app.proactive.scheduler.ProactiveScheduler.trigger_check", new_callable=AsyncMock) as mock_trigger:
            mock_trigger.return_value = mock_msg
            client = TestClient(app)

            # 1. 查询防打扰状态
            resp = client.get("/api/v1/proactive/status?user_id=test_api_user")
            assert resp.status_code == 200
            data = resp.json()
            assert "is_quiet_hours" in data
            assert "can_contact" in data
            assert data["user_id"] == "test_api_user"

            # 2. 触发一次主动研判 (force=True)
            t_resp = client.post(
                "/api/v1/proactive/trigger",
                json={
                    "user_id": "test_api_user",
                    "trigger_type": "weekly_review",
                    "force": True,
                },
            )
            assert t_resp.status_code == 200
            t_data = t_resp.json()
            assert t_data["status"] == "triggered"
            assert t_data["proactive_message"]["id"] == "mock-msg-001"

            # 3. 手动向 scheduler 塞入一条消息并测试获取主动消息列表与已读确认
            from app.proactive import get_proactive_scheduler
            scheduler = get_proactive_scheduler()
            if "test_api_user" not in scheduler._user_messages:
                scheduler._user_messages["test_api_user"] = []
            scheduler._user_messages["test_api_user"].append(mock_msg)

            m_resp = client.get("/api/v1/proactive/messages?user_id=test_api_user")
            assert m_resp.status_code == 200
            m_data = m_resp.json()
            assert m_data["total"] >= 1

            # 4. 标记已读 (ack)
            ack_resp = client.post(
                "/api/v1/proactive/ack",
                json={"user_id": "test_api_user", "message_id": "mock-msg-001", "action": "read"},
            )
            assert ack_resp.status_code == 200
            assert ack_resp.json()["status"] == "success"
