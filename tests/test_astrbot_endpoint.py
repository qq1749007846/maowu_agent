import json
import pytest
from httpx import AsyncClient, ASGITransport
from app.bootstrap.app_factory import create_app
from app.bootstrap.config import get_config


@pytest.fixture
def app():
    return create_app(get_config())


@pytest.mark.asyncio
async def test_list_models(app):
    """验证 /v1/models 返回 OpenAI 兼容模型列表"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        model_ids = [m["id"] for m in data["data"]]
        assert "deepseek-v4.1-flash" in model_ids
        assert "maowu-agent" in model_ids


@pytest.mark.asyncio
async def test_chat_completions_stream_tokens(app, monkeypatch):
    """测试流式 SSE 协议正常推送 token 与进度"""
    async def mock_streaming_agent(*args, **kwargs):
        yield "伸手，"
        yield "老夫给你把把脉！"

    import app.http.routes.astrbot_routes as ar
    monkeypatch.setattr(ar, "_run_maowu_agent", mock_streaming_agent)

    async def fake_submit(*args, **kwargs):
        return None

    monkeypatch.setattr(ar.dispatcher, "submit_task", fake_submit)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/v1/chat/completions", json={
            "model": "deepseek-v4.1-flash",
            "messages": [{"role": "user", "content": "你好"}],
            "stream": True,
            "user": "test_user"
        })
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text
        assert "伸手，" in body
        assert "老夫给你把把脉！" in body
        assert "[DONE]" in body


@pytest.mark.asyncio
async def test_chat_completions_stream_error_diagnostic(app, monkeypatch):
    """测试当 Agent 报错时能正常输出诊断信息而非空字符串"""
    async def mock_error_agent(*args, **kwargs):
        yield "*把脉受阻* 【调用异常】老夫运功被阻：`ConnectTimeout`"

    import app.http.routes.astrbot_routes as ar
    monkeypatch.setattr(ar, "_run_maowu_agent", mock_error_agent)

    async def fake_submit(*args, **kwargs):
        return None

    monkeypatch.setattr(ar.dispatcher, "submit_task", fake_submit)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/v1/chat/completions", json={
            "model": "deepseek-v4.1-flash",
            "messages": [{"role": "user", "content": "你好"}],
            "stream": True,
            "user": "test_user"
        })
        assert resp.status_code == 200
        assert "把脉受阻" in resp.text
        assert "ConnectTimeout" in resp.text
