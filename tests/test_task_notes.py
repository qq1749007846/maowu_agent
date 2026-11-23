from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.agent.langgraph.demo.tools.task_note_tools import NoteManagementTool, TodoManagementTool
from app.bootstrap import AppConfig, create_app
from app.proactive.decider import ProactiveDecider
from app.services.task_note_service import TaskNoteService


@pytest.fixture
def temp_task_service():
    """使用临时 SQLite 数据库隔离测试"""
    temp_dir = tempfile.mkdtemp(prefix="maowu_test_task_")
    db_file = Path(temp_dir) / "test_tasks.db"
    service = TaskNoteService(db_path=db_file)
    yield service
    # 自动关闭与清理


class TestTaskNoteService:
    def test_task_lifecycle(self, temp_task_service):
        service = temp_task_service
        user_id = "test_user_01"

        # 1. 创建高、中、低优先级任务
        t_high = service.create_task(user_id, "修复线上核心支付超时", priority="high", due_date="今日15:00")
        t_low = service.create_task(user_id, "清理测试日志", priority="low")
        t_med = service.create_task(user_id, "整理架构复盘文档", priority="medium")

        assert t_high["priority"] == "high"
        assert t_high["status"] == "pending"

        # 2. 查询列表（按优先级 high > medium > low 排序）
        tasks = service.list_tasks(user_id)
        assert len(tasks) == 3
        assert tasks[0]["id"] == t_high["id"]
        assert tasks[1]["id"] == t_med["id"]
        assert tasks[2]["id"] == t_low["id"]

        # 3. 标记完成
        updated = service.update_task(t_high["id"], user_id, status="done")
        assert updated is not None
        assert updated["status"] == "done"
        assert updated["completed_at"] != ""

        # 4. 按状态筛选
        pending_tasks = service.list_tasks(user_id, status="pending")
        assert len(pending_tasks) == 2

        # 5. 删除任务
        assert service.delete_task(t_low["id"], user_id) is True
        assert len(service.list_tasks(user_id)) == 2

    def test_notes_lifecycle(self, temp_task_service):
        service = temp_task_service
        user_id = "test_user_01"

        # 1. 保存备忘
        note1 = service.save_note(
            user_id,
            title="测试机 Redis 端口与密码",
            content="Host: 10.0.0.5, Port: 6379, Pass: redis_secret_123",
            category="server",
            tags="redis,pwd",
        )
        assert note1["id"].startswith("note_")

        note2 = service.save_note(
            user_id,
            title="下周技术方案构想",
            content="针对消息队列堆积，采用动态分区消费者模式",
            category="idea",
            tags="mq,kafka",
        )

        # 2. 搜索备忘 (关键词匹配)
        search_res = service.search_notes(user_id, keyword="redis")
        assert len(search_res) == 1
        assert search_res[0]["title"] == "测试机 Redis 端口与密码"

        # 3. 分类过滤
        idea_notes = service.search_notes(user_id, category="idea")
        assert len(idea_notes) == 1
        assert idea_notes[0]["id"] == note2["id"]

        # 4. 获取详情与删除
        single = service.get_note(note1["id"], user_id)
        assert single is not None
        assert "redis_secret_123" in single["content"]

        assert service.delete_note(note1["id"], user_id) is True
        assert service.get_note(note1["id"], user_id) is None


class TestTaskNoteTools:
    def test_todo_tool_actions(self):
        tool = TodoManagementTool()
        # 1. 创建
        res_create = tool._run(action="create", title="测试自动化待办", priority="high", user_id="tool_user")
        assert "【待办已创建】" in res_create
        assert "HIGH" in res_create

        # 2. 列表
        res_list = tool._run(action="list", user_id="tool_user")
        assert "测试自动化待办" in res_list

    def test_notes_tool_actions(self):
        tool = NoteManagementTool()
        # 1. 保存
        res_save = tool._run(
            action="save",
            title="生产数据库备份秘钥",
            content="ak_test_xxxx_key",
            category="config",
            user_id="tool_user",
        )
        assert "【备忘已安全归档】" in res_save

        # 2. 搜索
        res_search = tool._run(action="search", keyword="备份", user_id="tool_user")
        assert "生产数据库备份秘钥" in res_search


class TestTaskNoteHTTPRoutes:
    def test_http_api_endpoints(self):
        app = create_app(AppConfig())
        client = TestClient(app)

        # 1. POST /api/v1/tasks
        r = client.post(
            "/api/v1/tasks",
            json={"user_id": "http_user", "title": "API集成测试任务", "priority": "high"},
        )
        assert r.status_code == 200
        task_id = r.json()["task"]["id"]

        # 2. GET /api/v1/tasks
        r_get = client.get("/api/v1/tasks?user_id=http_user")
        assert r_get.status_code == 200
        assert len(r_get.json()["tasks"]) >= 1

        # 3. PATCH /api/v1/tasks/{id}
        r_patch = client.patch(
            f"/api/v1/tasks/{task_id}",
            json={"user_id": "http_user", "status": "done"},
        )
        assert r_patch.status_code == 200
        assert r_patch.json()["task"]["status"] == "done"

        # 4. POST /api/v1/notes
        r_note = client.post(
            "/api/v1/notes",
            json={"user_id": "http_user", "title": "API备忘", "content": "备忘正文"},
        )
        assert r_note.status_code == 200
        note_id = r_note.json()["note"]["id"]

        # 5. GET /api/v1/notes
        r_notes_get = client.get("/api/v1/notes?user_id=http_user&keyword=API")
        assert r_notes_get.status_code == 200
        assert len(r_notes_get.json()["notes"]) >= 1

        # 6. DELETE /api/v1/tasks/{id}
        r_del = client.delete(f"/api/v1/tasks/{task_id}?user_id=http_user")
        assert r_del.status_code == 200


class TestProactiveMorningStandup:
    @pytest.mark.asyncio
    async def test_morning_tasks_decision_with_pending(self):
        decider = ProactiveDecider()
        # Mock task service
        with patch("app.proactive.decider.get_task_note_service") as mock_get_svc, \
             patch.object(decider, "_get_llm") as mock_get_llm:
            mock_svc = MagicMock()
            mock_svc.list_tasks.return_value = [
                {"id": "t1", "title": "修复死锁异常", "priority": "high", "due_date": "11:00"}
            ]
            mock_get_svc.return_value = mock_svc

            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="太阳晒屁股了，赶紧把死锁给老夫修了！"))
            mock_get_llm.return_value = mock_llm

            decision = await decider.evaluate_morning_tasks("morning_user")
            assert decision.should_trigger is True
            assert decision.topic == "morning_tasks"
            assert "死锁" in decision.content
            assert decision.score > 9.0

    @pytest.mark.asyncio
    async def test_morning_tasks_decision_empty(self):
        decider = ProactiveDecider()
        with patch("app.proactive.decider.get_task_note_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.list_tasks.return_value = []
            mock_get_svc.return_value = mock_svc

            decision = await decider.evaluate_morning_tasks("empty_user")
            assert decision.should_trigger is False
            assert decision.content == ""
