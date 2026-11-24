from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent.langgraph.demo.tools.web_fetch_tools import (
    FetchWebContentTool,
    WebWatchManagementTool,
)
from app.bootstrap.app_factory import create_app
from app.bootstrap.config import get_config
from app.services.web_watcher_service import WebWatcherService


@pytest.fixture
def temp_watcher_service():
    """提供独立的临时数据库 WebWatcherService"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    service = WebWatcherService(db_path=temp_path)
    yield service
    try:
        Path(temp_path).unlink(missing_ok=True)
    except Exception:
        pass


def test_parse_and_clean_html(temp_watcher_service: WebWatcherService):
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>FastAPI Release v0.115.0</title></head>
    <body>
        <nav><a href="/">Home</a><a href="/docs">Docs</a></nav>
        <script>console.log("ad script");</script>
        <article class="release-body">
            <h1>FastAPI 0.115.0 Released!</h1>
            <p>Support for Pydantic v2 and Python 3.12+ async features.</p>
        </article>
        <footer>Copyright 2026 FastAPI</footer>
    </body>
    </html>
    """
    res = temp_watcher_service.parse_and_clean_html(html=html, url="https://example.com/release")
    assert res["success"] is True
    assert res["title"] == "FastAPI Release v0.115.0"
    assert "ad script" not in res["text"]
    assert "Copyright 2026" not in res["text"]
    assert "FastAPI 0.115.0 Released!" in res["text"]
    assert res["hash"] != ""

    # Test with CSS selector
    res_sel = temp_watcher_service.parse_and_clean_html(
        html=html, url="https://example.com", selector=".release-body"
    )
    assert res_sel["success"] is True
    assert "FastAPI 0.115.0 Released!" in res_sel["text"]


def test_web_watcher_db_crud(temp_watcher_service: WebWatcherService):
    # Mock initial fetch during add
    with patch.object(temp_watcher_service, "fetch_content") as mock_fetch:
        mock_fetch.return_value = {
            "success": True,
            "title": "Initial Title",
            "text": "Initial body content",
            "hash": "hash_v1",
        }
        item = temp_watcher_service.add_watch_target(
            user_id="user_test",
            name="FastAPI Release",
            url="https://github.com/fastapi/fastapi/releases",
            selector=".release",
            check_interval_hours=2,
        )
        assert item["id"].startswith("watch_")
        assert item["name"] == "FastAPI Release"
        assert item["initial_hash"] == "hash_v1"

        # List
        targets = temp_watcher_service.list_watch_targets(user_id="user_test")
        assert len(targets) == 1
        assert targets[0]["id"] == item["id"]

        # Get single
        single = temp_watcher_service.get_watch_target(item["id"])
        assert single is not None
        assert single["url"] == "https://github.com/fastapi/fastapi/releases"

        # Remove
        removed = temp_watcher_service.remove_watch_target(item["id"])
        assert removed is True
        assert temp_watcher_service.get_watch_target(item["id"]) is None


def test_check_target_diff_detection(temp_watcher_service: WebWatcherService):
    # 1. 建立基准
    with patch.object(temp_watcher_service, "fetch_content") as mock_fetch:
        mock_fetch.return_value = {
            "success": True,
            "title": "Page V1",
            "text": "Content Version 1.0",
            "hash": "hash_111",
        }
        item = temp_watcher_service.add_watch_target(
            name="Doc Watch", url="https://example.com/docs"
        )
        target_id = item["id"]

    # 2. 第一次检查：内容未变
    with patch.object(temp_watcher_service, "fetch_content") as mock_fetch:
        mock_fetch.return_value = {
            "success": True,
            "title": "Page V1",
            "text": "Content Version 1.0",
            "hash": "hash_111",
        }
        res_no_change = temp_watcher_service.check_target(target_id)
        assert res_no_change["has_changed"] is False

    # 3. 第二次检查：内容更新
    with patch.object(temp_watcher_service, "fetch_content") as mock_fetch:
        mock_fetch.return_value = {
            "success": True,
            "title": "Page V2 - Breaking Change",
            "text": "Content Version 2.0 Released!",
            "hash": "hash_222",
        }
        res_changed = temp_watcher_service.check_target(target_id)
        assert res_changed["has_changed"] is True
        assert res_changed["old_hash"] == "hash_111"
        assert res_changed["new_hash"] == "hash_222"
        assert "变动" in res_changed["summary"]


def test_fetch_web_content_tool():
    tool = FetchWebContentTool()
    with patch("app.agent.langgraph.demo.tools.web_fetch_tools.get_web_watcher_service") as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.fetch_content.return_value = {
            "success": True,
            "title": "Python 3.13 Changelog",
            "text": "New JIT compiler introduced in Python 3.13.",
            "full_length": 500,
        }
        mock_get_svc.return_value = mock_svc

        out = tool._run(url="https://docs.python.org/3/whatsnew/3.13.html")
        assert "【网页萃取成功】" in out
        assert "Python 3.13 Changelog" in out
        assert "New JIT compiler" in out


def test_manage_web_watch_tool():
    tool = WebWatchManagementTool()
    with patch("app.agent.langgraph.demo.tools.web_fetch_tools.get_web_watcher_service") as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.add_watch_target.return_value = {
            "id": "watch_999",
            "name": "Vue Release",
            "url": "https://github.com/vuejs/core/releases",
            "check_interval_hours": 4,
            "initial_hash": "abc",
        }
        mock_svc.list_watch_targets.return_value = [
            {
                "id": "watch_999",
                "name": "Vue Release",
                "url": "https://github.com/vuejs/core/releases",
                "check_interval_hours": 4,
                "last_check_time": "2026-11-24T08:00:00",
                "last_change_time": "",
                "change_summary": "正常",
            }
        ]
        mock_svc.check_target.return_value = {
            "success": True,
            "has_changed": True,
            "name": "Vue Release",
            "url": "https://github.com/vuejs/core/releases",
            "summary": "发现新版本 v3.5.0",
            "new_snippet": "v3.5.0 features...",
        }
        mock_svc.remove_watch_target.return_value = True
        mock_get_svc.return_value = mock_svc

        # 1. Add
        add_res = tool._run(
            action="add",
            name="Vue Release",
            url="https://github.com/vuejs/core/releases",
        )
        assert "【监控哨兵已部署】" in add_res
        assert "watch_999" in add_res

        # 2. List
        list_res = tool._run(action="list")
        assert "【当前活跃监控哨兵清单】" in list_res
        assert "Vue Release" in list_res

        # 3. Check single
        check_res = tool._run(action="check", target_id="watch_999")
        assert "🚨【检测到网站更新！】" in check_res
        assert "v3.5.0" in check_res

        # 4. Remove
        rem_res = tool._run(action="remove", target_id="watch_999")
        assert "已成功注销下线" in rem_res


def test_web_watch_api_routes(temp_watcher_service: WebWatcherService):
    app = create_app(get_config())
    with patch(
        "app.http.routes.web_watch_routes.get_web_watcher_service",
        return_value=temp_watcher_service,
    ):
        with TestClient(app) as client:
            # 1. Mock Fetch API
            with patch.object(temp_watcher_service, "fetch_content") as mock_fetch:
                mock_fetch.return_value = {
                    "success": True,
                    "title": "API Test Page",
                    "text": "Cleaned body text",
                    "hash": "hash_api",
                }
                resp = client.post(
                    "/api/v1/web-watch/fetch",
                    json={"url": "https://httpbin.org/html", "selector": ""},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["title"] == "API Test Page"

            # 2. Add Target API
            with patch.object(temp_watcher_service, "fetch_content") as mock_fetch:
                mock_fetch.return_value = {
                    "success": True,
                    "title": "Initial",
                    "text": "Init",
                    "hash": "init_hash",
                }
                resp_add = client.post(
                    "/api/v1/web-watch/targets",
                    json={
                        "name": "My Target",
                        "url": "https://example.com",
                        "check_interval_hours": 3,
                    },
                )
                assert resp_add.status_code == 200
                target_id = resp_add.json()["target"]["id"]

            # 3. List Targets API
            resp_list = client.get("/api/v1/web-watch/targets")
            assert resp_list.status_code == 200
            assert resp_list.json()["total"] == 1

            # 4. Delete Target API
            resp_del = client.delete(f"/api/v1/web-watch/targets/{target_id}")
            assert resp_del.status_code == 200

            resp_list_after = client.get("/api/v1/web-watch/targets")
            assert resp_list_after.json()["total"] == 0
