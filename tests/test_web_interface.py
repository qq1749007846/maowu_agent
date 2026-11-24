from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.app_factory import create_app
from app.bootstrap.config import get_config


def test_index_page_rendered_successfully():
    """测试根路径 / 是否正确渲染并返回 MaoWu Agent 前端工作台页面"""
    app = create_app(get_config())
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")

    html_content = resp.text
    # 1. 验证品牌与导师身份
    assert "MaoWu Agent" in html_content
    assert "Tech &amp; Career Mentor" in html_content or "Tech & Career Mentor" in html_content

    # 2. 验证使用提示指南模块
    assert "使用提示指南" in html_content
    assert "guideModal" in html_content

    # 3. 验证长期画像卡片与 WMA 装配视窗
    assert "工程师长期技术画像" in html_content
    assert "WMA 工作记忆装配台" in html_content

    # 4. 验证异步子代理监控
    assert "后台子代理任务监控" in html_content

    # 5. 验证 Phase 1~3 新增多功能工作台 Tabs
    assert "tabPanel-tasks" in html_content
    assert "tabPanel-files" in html_content
    assert "tabPanel-sentinel" in html_content
    assert "tabPanel-cognitive" in html_content

    # 6. 验证新功能指南章节
    assert "Python 沙箱与实体 Excel 报表直接交付" in html_content
    assert "待办事项 (TODO) 与备忘录持久化" in html_content
    assert "网页干货萃取与目标变动盯盘哨兵" in html_content

