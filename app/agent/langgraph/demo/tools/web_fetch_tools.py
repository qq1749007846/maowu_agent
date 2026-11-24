from __future__ import annotations

import json
from typing import Any
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.services.web_watcher_service import get_web_watcher_service


class FetchWebInput(BaseModel):
    url: str = Field(description="需要抓取并萃取正文的目标网页 URL 地址（如 https://github.com/... 或新闻、技术博客链接）")
    selector: str = Field(default="", description="可选的 CSS 选择器（如 'article', '.content', '#main'），用于精确定位正文区域")
    max_chars: int = Field(default=3000, description="萃取返回的最大字符数，默认 3000，防止上下文溢出")


class FetchWebContentTool(BaseTool):
    name: str = "fetch_web_content"
    description: str = (
        "抓取并萃取目标网页的核心正文内容。"
        "老夫会自动剔除广告弹窗、无关导航和脚本噪声，提取高信噪比纯净正文，用于内容速览、技术研读或竞品数据分析。"
    )
    args_schema: type[BaseModel] = FetchWebInput

    def _run(
        self,
        url: str,
        selector: str = "",
        max_chars: int = 3000,
        **kwargs: Any,
    ) -> str:
        service = get_web_watcher_service()
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            return "错误：网页 URL 格式不正确，必须以 http:// 或 https:// 开头。"

        res = service.fetch_content(url=clean_url, selector=selector.strip(), max_chars=max_chars)
        if not res.get("success"):
            return f"【网页抓取失败】\n目标网址: {clean_url}\n原因: {res.get('error', '未知网络错误')}"

        title = res.get("title") or "无标题"
        text = res.get("text") or "未能提取到有效正文"
        full_len = res.get("full_length", len(text))

        return (
            f"【网页萃取成功】\n"
            f"- 目标: {clean_url}\n"
            f"- 页面标题: {title}\n"
            f"- 正文总字符数: {full_len} (已截取前 {len(text)} 字符)\n"
            f"- 内容摘要/正文:\n"
            f"```text\n"
            f"{text}\n"
            f"```"
        )


class WebWatchInput(BaseModel):
    action: str = Field(description="操作动作：add（新增监控目标）、list（查看监控清单）、check（手动触发检查变动）、remove（取消监控）")
    name: str = Field(default="", description="监控目标的名称备注，如 'FastAPI 官方版本发布'、'竞品官网价格'")
    url: str = Field(default="", description="需要长期监控变动的目标网页 URL（add 时必填）")
    target_id: str = Field(default="", description="监控目标的唯一 ID（在 remove 或单目标 check 时必填）")
    selector: str = Field(default="", description="可选 CSS 选择器，用于精确监控网页的某个特定模块（如 '.release-entry'）")
    interval_hours: int = Field(default=4, description="巡检周期小时数，默认 4 小时巡检一次")
    user_id: str = Field(default="default_user", description="用户ID，默认从上下文读取")


class WebWatchManagementTool(BaseTool):
    name: str = "manage_web_watch"
    description: str = (
        "管理全天候网页变动监控哨兵。"
        "支持动作：add（登记新增盯盘网址，老夫会自动记录初识基准 Hash）、"
        "list（查看当前活跃的监控清单与最近检查状态）、"
        "check（立刻执行一次网站差异检查，看内容是否更新）、"
        "remove（取消该监控目标）。"
    )
    args_schema: type[BaseModel] = WebWatchInput

    def _run(
        self,
        action: str,
        name: str = "",
        url: str = "",
        target_id: str = "",
        selector: str = "",
        interval_hours: int = 4,
        user_id: str = "default_user",
        **kwargs: Any,
    ) -> str:
        service = get_web_watcher_service()
        clean_action = action.lower().strip()

        if clean_action == "add":
            if not url.strip() or not url.strip().startswith(("http://", "https://")):
                return "错误：添加监控必须提供合法的 http(s) 网址 url。"
            target_name = name.strip() or url.strip()
            item = service.add_watch_target(
                user_id=user_id,
                name=target_name,
                url=url.strip(),
                selector=selector.strip(),
                check_interval_hours=interval_hours if interval_hours > 0 else 4,
            )
            return (
                f"【监控哨兵已部署】\n"
                f"- 目标 ID: {item['id']}\n"
                f"- 目标名称: {item['name']}\n"
                f"- 监控网址: {item['url']}\n"
                f"- 巡检周期: 每 {item['check_interval_hours']} 小时一次\n"
                f"- 初始基线状态: {'已成功抓取基准指纹' if item['initial_hash'] else '待首次联网采样'}"
            )

        elif clean_action == "list":
            targets = service.list_watch_targets(user_id=user_id, status="active")
            if not targets:
                return "当前暂无正在巡检的网页监控目标。"

            lines = [f"【当前活跃监控哨兵清单】共 {len(targets)} 个目标："]
            for idx, t in enumerate(targets, 1):
                last_check = t.get("last_check_time") or "未检测"
                last_change = t.get("last_change_time") or "未发生变动"
                summary = t.get("change_summary") or "正常"
                lines.append(
                    f"{idx}. [{t['id']}] {t['name']}\n"
                    f"   - 网址: {t['url']}\n"
                    f"   - 巡检周期: 每 {t['check_interval_hours']} 小时\n"
                    f"   - 最近检查: {last_check} | 最近变动: {last_change}\n"
                    f"   - 状态摘要: {summary}"
                )
            return "\n".join(lines)

        elif clean_action == "check":
            if target_id.strip():
                # 检查指定单个目标
                res = service.check_target(target_id.strip())
                if not res.get("success"):
                    return f"检查失败: {res.get('error', '未知错误')}"
                if res.get("has_changed"):
                    return (
                        f"🚨【检测到网站更新！】\n"
                        f"- 目标: {res['name']} ({res['url']})\n"
                        f"- 变动详情: {res['summary']}\n"
                        f"- 最新摘要片段: {res.get('new_snippet', '')[:200]}"
                    )
                return f"目标【{res['name']}】({res['url']}) 状态稳定，内容未发生实质变动。"
            else:
                # 检查所有活跃目标
                all_targets = service.list_watch_targets(user_id=user_id, status="active")
                if not all_targets:
                    return "当前没有配置任何监控目标。"
                changed_items = []
                checked_count = 0
                for t in all_targets:
                    checked_count += 1
                    r = service.check_target(t["id"])
                    if r.get("has_changed"):
                        changed_items.append(r)

                if not changed_items:
                    return f"已巡检全部 {checked_count} 个监控目标，所有网站均未发生变动。"

                lines = [f"🚨 巡检完成，发现 {len(changed_items)} 个目标发生内容更新："]
                for item in changed_items:
                    lines.append(f"- 【{item['name']}】: {item['summary']}")
                return "\n".join(lines)

        elif clean_action == "remove":
            if not target_id.strip():
                return "错误：取消监控必须提供 target_id。"
            ok = service.remove_watch_target(target_id.strip())
            if ok:
                return f"监控目标 [{target_id.strip()}] 已成功注销下线。"
            return f"未能找到 ID 为 [{target_id.strip()}] 的监控目标。"

        else:
            return f"不支持的操作动作: '{action}'。请使用 add, list, check 或 remove。"
