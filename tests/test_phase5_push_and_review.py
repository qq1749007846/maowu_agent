from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.bootstrap.app_factory import create_app
from app.bootstrap.config import AppConfig
from app.proactive.scheduler import ProactiveMessage
from app.services.push_service import OutboundPushService, PushRecord, get_push_service
from app.services.weekly_review_service import WeeklyTechReviewService, get_weekly_review_service


@pytest.fixture
def test_client():
    app = create_app(AppConfig())
    return TestClient(app)


class TestOutboundPushService:
    @pytest.mark.asyncio
    async def test_push_service_lifecycle(self):
        svc = OutboundPushService(astrbot_url="http://mock-astrbot:6185")
        assert svc.enabled is True

        # 测试主动推送
        rec = await svc.push_message(
            user_id="test_user",
            title="排障跟进测试",
            content="这是一条测试消息",
            channel="internal",
        )
        assert isinstance(rec, PushRecord)
        assert rec.title == "排障跟进测试"
        assert rec.status in ["sent", "buffered"]

        # 测试历史记录与配置查询
        history = svc.get_history()
        assert len(history) >= 1
        assert history[0]["id"] == rec.id

        cfg = svc.get_config()
        assert cfg["enabled"] is True
        assert cfg["buffered_count"] >= 1

    @pytest.mark.asyncio
    async def test_proactive_message_subscriber_hook(self):
        svc = OutboundPushService(astrbot_url="http://mock-astrbot:6185")
        msg = ProactiveMessage(
            user_id="user_alice",
            topic="morning_tasks",
            title="晨间待办督办",
            content="今日待办 2 项请结清",
            reason="standup",
        )
        await svc.on_proactive_message(msg)
        history = svc.get_history()
        assert any(h["user_id"] == "user_alice" and "晨间待办" in h["title"] for h in history)


class TestWeeklyTechReviewService:
    @pytest.mark.asyncio
    async def test_review_service_generation(self):
        svc = get_weekly_review_service()
        user_id = "test_engineer"

        # 收集事实
        facts = svc._collect_weekly_facts(user_id)
        assert "task_stats" in facts
        assert "note_stats" in facts
        assert "workspace_files" in facts

        # 雷达基准测算
        radar = svc._compute_fallback_radar(facts)
        assert all(k in radar for k in ["architecture", "coding_sandbox", "troubleshooting", "delivery", "learning"])
        assert all(0 <= v <= 100 for v in radar.values())

        # 生成周报（使用 fallback 模板确保离线自洽）
        with patch.object(svc, "_get_llm", return_value=None):
            report = await svc.generate_weekly_report(user_id=user_id, auto_push=False)
            assert report["user_id"] == user_id
            assert "html_file" in report
            assert "md_file" in report
            assert report["radar_scores"]["architecture"] > 0

        # 查询最新与历史
        latest = svc.get_latest_report(user_id=user_id)
        assert latest is not None
        assert "filename" in latest

        history = svc.list_history()
        assert len(history) >= 1

        skill_radar = svc.get_skill_radar(user_id=user_id)
        assert "radar_scores" in skill_radar
        assert "tasks_completed" in skill_radar


class TestPhase5HTTPRoutes:
    def test_phase5_api_endpoints(self, test_client):
        # 1. 触发生成周报
        r = test_client.post("/api/v1/review/generate", json={"user_id": "api_user", "auto_push": False})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert "report_id" in data["report"]

        # 2. 查询最新周报
        r = test_client.get("/api/v1/review/latest?user_id=api_user")
        assert r.status_code == 200
        assert r.json()["status"] == "success"

        # 3. 历史周报
        r = test_client.get("/api/v1/review/history")
        assert r.status_code == 200
        assert r.json()["status"] == "success"

        # 4. 技术能力雷达画像
        r = test_client.get("/api/v1/profile/skills?user_id=api_user")
        assert r.status_code == 200
        assert "radar_scores" in r.json()["skills"]

        # 5. 主动外呼推送测试
        r = test_client.post("/api/v1/push/test", json={
            "user_id": "api_user",
            "title": "测试推送",
            "content": "测试内容",
            "channel": "internal",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "success"

        # 6. 推送历史与配置
        r = test_client.get("/api/v1/push/history")
        assert r.status_code == 200
        assert r.json()["status"] == "success"

        r = test_client.get("/api/v1/push/config")
        assert r.status_code == 200
        assert r.json()["status"] == "success"
