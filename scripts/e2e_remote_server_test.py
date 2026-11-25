# -*- coding: utf-8 -*-
"""
MaoWu Agent 全功能远程生产端点（124.222.9.212:8000）端到端集成验证脚本
涵盖：
1. 健康检查与探活
2. OpenAI 兼容模型列表 & 聊天补全（流式 SSE 与非流式）
3. 工作区文件中心（列表、下载校验、上传同步）
4. 个人 TODO 敏捷督办（增删改查全生命周期）
5. 私人工作备忘录（保存、检索、删除）
6. 网页哨兵与正文萃取（实时抓取、监控目标注册、全量巡检、注销）
7. 主动交互与防打扰守护（状态查询、站会决策触发、消息拉取与 ACK）
8. MySQL 数据库安全只读与 Schema 查询
9. 静态 Web 仪表盘入口探活
"""

import json
import time
import requests

BASE_URL = "http://124.222.9.212:8000"
TEST_USER = "e2e_verification_user"

results = []

def record(module: str, item: str, status: bool, detail: str, duration: float = 0.0):
    results.append({
        "module": module,
        "item": item,
        "status": "PASS" if status else "FAIL",
        "detail": detail,
        "duration": f"{duration:.3f}s"
    })
    mark = "√ [PASS]" if status else "× [FAIL]"
    print(f"{mark} [{module}] {item} ({duration:.3f}s) - {detail}")


def test_health():
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/api/v1/health", timeout=10)
        d = time.time() - t0
        record("系统探活", "健康检查 (/api/v1/health)", r.status_code == 200, f"状态码: {r.status_code}, 响应: {r.text[:60]}", d)
    except Exception as e:
        record("系统探活", "健康检查 (/api/v1/health)", False, str(e), time.time() - t0)


def test_openai_models():
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/v1/models", timeout=10)
        d = time.time() - t0
        data = r.json()
        ids = [m["id"] for m in data.get("data", [])]
        ok = r.status_code == 200 and "deepseek-v4.1-flash" in ids and "maowu-agent" in ids
        record("OpenAI协议", "模型列表 (/v1/models)", ok, f"模型数: {len(ids)}, 包含: {ids}", d)
    except Exception as e:
        record("OpenAI协议", "模型列表 (/v1/models)", False, str(e), time.time() - t0)


def test_openai_chat_completions_non_stream():
    t0 = time.time()
    try:
        body = {
            "model": "deepseek-v4.1-flash",
            "messages": [{"role": "user", "content": "老夫，报上你的坐诊门规，一句话概括！"}],
            "stream": False,
            "user": TEST_USER
        }
        r = requests.post(f"{BASE_URL}/v1/chat/completions", json=body, timeout=35)
        d = time.time() - t0
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        ok = r.status_code == 200 and len(content.strip()) > 0
        record("导师对话", "非流式补全 (/v1/chat/completions)", ok, f"耗时 {d:.2f}s, 输出长度: {len(content)}, 预览: {content[:80].replace(chr(10), ' ')}", d)
    except Exception as e:
        record("导师对话", "非流式补全 (/v1/chat/completions)", False, str(e), time.time() - t0)


def test_openai_chat_completions_stream():
    t0 = time.time()
    try:
        body = {
            "model": "deepseek-v4.1-flash",
            "messages": [{"role": "user", "content": "伸手，把脉！"}],
            "stream": True,
            "user": TEST_USER
        }
        r = requests.post(f"{BASE_URL}/v1/chat/completions", json=body, stream=True, timeout=35)
        chunks_count = 0
        full_text = ""
        has_done = False
        for line in r.iter_lines(decode_unicode=True):
            if line:
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        has_done = True
                    else:
                        try:
                            c = json.loads(payload)
                            tok = c.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            full_text += tok
                            chunks_count += 1
                        except:
                            pass
        d = time.time() - t0
        ok = r.status_code == 200 and chunks_count > 0 and len(full_text) > 0 and has_done
        record("导师对话", "SSE流式逐Token推流 (/v1/chat/completions stream=True)", ok, f"共推流 {chunks_count} 个包, 文本长: {len(full_text)}, 包含[DONE]: {has_done}, 预览: {full_text[:80].replace(chr(10), ' ')}", d)
    except Exception as e:
        record("导师对话", "SSE流式逐Token推流 (/v1/chat/completions stream=True)", False, str(e), time.time() - t0)


def test_workspace_files_and_download():
    # 1. 列表
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/api/v1/workspace/files", timeout=10)
        d = time.time() - t0
        files = r.json().get("files", [])
        names = [f["name"] for f in files]
        target_found = any("广西行政处罚" in n for n in names)
        # 验证新字段 download_url 与 size_human
        has_meta = all("download_url" in f and "size_human" in f for f in files if f.get("type") == "file")
        record("工作区中心", "文件列表检索 (/api/v1/workspace/files)", r.status_code == 200 and target_found and has_meta, f"共 {len(files)} 个文件, 发现处罚Excel: {target_found}, 元数据完备: {has_meta}", d)
    except Exception as e:
        record("工作区中心", "文件列表检索 (/api/v1/workspace/files)", False, str(e), time.time() - t0)

    # 2. 下载真实实体 Excel
    t0 = time.time()
    try:
        filename = "广西行政处罚_前100条.xlsx"
        r = requests.get(f"{BASE_URL}/api/v1/workspace/download/{requests.utils.quote(filename)}", timeout=15)
        d = time.time() - t0
        cd = r.headers.get("Content-Disposition", "")
        ct = r.headers.get("Content-Type", "")
        size = len(r.content)
        ok = r.status_code == 200 and size > 5000 and "spreadsheet" in ct
        record("工作区中心", "实体Excel下载 (/api/v1/workspace/download/...)", ok, f"下载大小: {size} bytes, Content-Type: {ct}, Content-Disposition: {cd[:60]}", d)
    except Exception as e:
        record("工作区中心", "实体Excel下载 (/api/v1/workspace/download/...)", False, str(e), time.time() - t0)

    # 3. 模糊别名容错下载
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/api/v1/workspace/download/广西行政处罚", timeout=15)
        d = time.time() - t0
        ok = r.status_code == 200 and len(r.content) > 5000
        record("工作区中心", "模糊别名容错下载 (/api/v1/workspace/download/广西行政处罚)", ok, f"容错命中下载大小: {len(r.content)} bytes", d)
    except Exception as e:
        record("工作区中心", "模糊别名容错下载 (/api/v1/workspace/download/广西行政处罚)", False, str(e), time.time() - t0)

    # 4. 上传测试文件
    t0 = time.time()
    try:
        content = b"MaoWu E2E Safe Binary Upload Test Content"
        r = requests.post(f"{BASE_URL}/api/v1/workspace/upload/e2e_test_file.txt", data=content, timeout=10)
        d = time.time() - t0
        ok = r.status_code == 200 and r.json().get("success") is True
        record("工作区中心", "沙箱文件上传 (/api/v1/workspace/upload/...)", ok, f"上传响应: {r.text}", d)
    except Exception as e:
        record("工作区中心", "沙箱文件上传 (/api/v1/workspace/upload/...)", False, str(e), time.time() - t0)


def test_todo_management():
    # 1. 创建待办
    t0 = time.time()
    task_id = None
    try:
        body = {
            "user_id": TEST_USER,
            "title": "完成金监总局行政处罚100条复盘",
            "priority": "HIGH",
            "due_date": "2026-11-30"
        }
        r = requests.post(f"{BASE_URL}/api/v1/tasks", json=body, timeout=10)
        d = time.time() - t0
        data = r.json()
        task_id = data.get("task", {}).get("id")
        record("TODO待办", "创建高优待办 (POST /api/v1/tasks)", r.status_code == 200 and task_id is not None, f"任务ID: {task_id}, 优先级: HIGH", d)
    except Exception as e:
        record("TODO待办", "创建高优待办 (POST /api/v1/tasks)", False, str(e), time.time() - t0)

    # 2. 查询待办列表
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/api/v1/tasks?user_id={TEST_USER}", timeout=10)
        d = time.time() - t0
        tasks = r.json().get("tasks", [])
        found = any(t.get("id") == task_id for t in tasks) if task_id else len(tasks) > 0
        record("TODO待办", "查询任务清单 (GET /api/v1/tasks)", r.status_code == 200 and found, f"用户任务数: {len(tasks)}, 包含新增任务: {found}", d)
    except Exception as e:
        record("TODO待办", "查询任务清单 (GET /api/v1/tasks)", False, str(e), time.time() - t0)

    # 3. 标记完成
    if task_id:
        t0 = time.time()
        try:
            r = requests.patch(f"{BASE_URL}/api/v1/tasks/{task_id}", json={"user_id": TEST_USER, "status": "completed"}, timeout=10)
            d = time.time() - t0
            task_status = str(r.json().get("task", {}).get("status", "")).lower()
            ok = r.status_code == 200 and task_status in ["completed", "done"]
            record("TODO待办", "标记任务完成 (PATCH /api/v1/tasks/{id})", ok, f"状态更新为 {task_status}", d)
        except Exception as e:
            record("TODO待办", "标记任务完成 (PATCH /api/v1/tasks/{id})", False, str(e), time.time() - t0)

        # 4. 删除清理
        t0 = time.time()
        try:
            r = requests.delete(f"{BASE_URL}/api/v1/tasks/{task_id}?user_id={TEST_USER}", timeout=10)
            d = time.time() - t0
            record("TODO待办", "删除任务 (DELETE /api/v1/tasks/{id})", r.status_code == 200, "测试任务已安全清理", d)
        except Exception as e:
            record("TODO待办", "删除任务 (DELETE /api/v1/tasks/{id})", False, str(e), time.time() - t0)


def test_notes_management():
    # 1. 保存笔记
    t0 = time.time()
    note_id = None
    try:
        body = {
            "user_id": TEST_USER,
            "title": "金监总局接口抓取秘籍",
            "content": "使用 itemId 1635 获取广西分局处罚，1634 获取区局处罚，注意 DocInfo 首字母大写。",
            "tags": "政务爬虫, 金融监管"
        }
        r = requests.post(f"{BASE_URL}/api/v1/notes", json=body, timeout=10)
        d = time.time() - t0
        data = r.json()
        note_id = data.get("note", {}).get("id")
        record("工作备忘", "保存技术笔记 (POST /api/v1/notes)", r.status_code == 200 and note_id is not None, f"笔记ID: {note_id}", d)
    except Exception as e:
        record("工作备忘", "保存技术笔记 (POST /api/v1/notes)", False, str(e), time.time() - t0)

    # 2. 检索笔记
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/api/v1/notes?user_id={TEST_USER}&keyword=DocInfo", timeout=10)
        d = time.time() - t0
        notes = r.json().get("notes", [])
        found = any("DocInfo" in n.get("content", "") for n in notes)
        record("工作备忘", "搜索笔记 (GET /api/v1/notes?keyword=...)", r.status_code == 200 and found, f"命中笔记数: {len(notes)}", d)
    except Exception as e:
        record("工作备忘", "搜索笔记 (GET /api/v1/notes?query=...)", False, str(e), time.time() - t0)

    # 3. 删除清理
    if note_id:
        t0 = time.time()
        try:
            r = requests.delete(f"{BASE_URL}/api/v1/notes/{note_id}?user_id={TEST_USER}", timeout=10)
            d = time.time() - t0
            record("工作备忘", "删除笔记 (DELETE /api/v1/notes/{id})", r.status_code == 200, "测试笔记已清理", d)
        except Exception as e:
            record("工作备忘", "删除笔记 (DELETE /api/v1/notes/{id})", False, str(e), time.time() - t0)


def test_web_watch_and_fetch():
    # 1. 实时网页正文萃取降噪
    t0 = time.time()
    try:
        body = {
            "url": "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild?itemId=1635&pageSize=2&pageIndex=1",
            "max_chars": 2000
        }
        r = requests.post(f"{BASE_URL}/api/v1/web-watch/fetch", json=body, timeout=15)
        d = time.time() - t0
        data = r.json()
        ok = r.status_code == 200 and data.get("success") is True and len(data.get("hash", "")) == 64
        record("网页哨兵", "网页正文萃取与Hash计算 (POST /api/v1/web-watch/fetch)", ok, f"成功: {data.get('success')}, 提取长度: {data.get('full_length')}, Hash: {data.get('hash')[:16]}...", d)
    except Exception as e:
        record("网页哨兵", "网页正文萃取与Hash计算 (POST /api/v1/web-watch/fetch)", False, str(e), time.time() - t0)

    # 2. 注册监控目标
    t0 = time.time()
    target_id = None
    try:
        body = {
            "user_id": TEST_USER,
            "url": "https://www.nfra.gov.cn/branch/guangxi/view/pages/common/ItemList.html?itemPId=1610&itemId=1614",
            "name": "广西金监行政处罚官方专栏",
            "check_interval_hours": 6
        }
        r = requests.post(f"{BASE_URL}/api/v1/web-watch/targets", json=body, timeout=10)
        d = time.time() - t0
        data = r.json()
        target_id = data.get("target", {}).get("id")
        record("网页哨兵", "添加监控哨兵目标 (POST /api/v1/web-watch/targets)", r.status_code == 200 and target_id is not None, f"目标ID: {target_id}", d)
    except Exception as e:
        record("网页哨兵", "添加监控哨兵目标 (POST /api/v1/web-watch/targets)", False, str(e), time.time() - t0)

    # 3. 查询监控列表
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/api/v1/web-watch/targets?user_id={TEST_USER}", timeout=10)
        d = time.time() - t0
        targets = r.json().get("targets", [])
        found = any(t.get("id") == target_id for t in targets)
        record("网页哨兵", "查询监控列表 (GET /api/v1/web-watch/targets)", r.status_code == 200 and found, f"监控目标数: {len(targets)}", d)
    except Exception as e:
        record("网页哨兵", "查询监控列表 (GET /api/v1/web-watch/targets)", False, str(e), time.time() - t0)

    # 4. 一键立即全量巡检比对
    t0 = time.time()
    try:
        r = requests.post(f"{BASE_URL}/api/v1/web-watch/check-all?user_id={TEST_USER}", timeout=30)
        d = time.time() - t0
        data = r.json()
        record("网页哨兵", "执行全网指纹巡检比对 (POST /api/v1/web-watch/check-all)", r.status_code == 200, f"巡检响应: {data.get('message', r.text)}", d)
    except Exception as e:
        record("网页哨兵", "执行全网指纹巡检比对 (POST /api/v1/web-watch/check-all)", False, str(e), time.time() - t0)

    # 5. 注销目标
    if target_id:
        t0 = time.time()
        try:
            r = requests.delete(f"{BASE_URL}/api/v1/web-watch/targets/{target_id}", timeout=10)
            d = time.time() - t0
            record("网页哨兵", "注销监控目标 (DELETE /api/v1/web-watch/targets/{id})", r.status_code == 200, "测试哨兵已注销", d)
        except Exception as e:
            record("网页哨兵", "注销监控目标 (DELETE /api/v1/web-watch/targets/{id})", False, str(e), time.time() - t0)


def test_proactive_interaction():
    # 1. 查询防打扰与触达状态
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/api/v1/proactive/status?user_id={TEST_USER}", timeout=10)
        d = time.time() - t0
        data = r.json()
        ok = r.status_code == 200 and "can_contact" in data and "quiet_hours_range" in data
        record("主动触达", "防打扰与触达状态查询 (/api/v1/proactive/status)", ok, f"允许触达: {data.get('can_contact')}, 静默区间: {data.get('quiet_hours_range')}", d)
    except Exception as e:
        record("主动触达", "防打扰与触达状态查询 (/api/v1/proactive/status)", False, str(e), time.time() - t0)

    # 2. 演示模式强制触发主动决策 (如 weekly_review)
    t0 = time.time()
    msg_id = None
    try:
        body = {
            "user_id": TEST_USER,
            "trigger_type": "weekly_review",
            "force": True
        }
        r = requests.post(f"{BASE_URL}/api/v1/proactive/trigger", json=body, timeout=20)
        d = time.time() - t0
        data = r.json()
        msg_id = data.get("proactive_message", {}).get("id")
        record("主动触达", "主动决策问候触发 (POST /api/v1/proactive/trigger)", r.status_code == 200, f"决策状态: {data.get('status')}, 标题: {data.get('proactive_message', {}).get('title')}", d)
    except Exception as e:
        record("主动触达", "主动决策问候触发 (POST /api/v1/proactive/trigger)", False, str(e), time.time() - t0)

    # 3. 查询主动消息
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/api/v1/proactive/messages?user_id={TEST_USER}&unread_only=false", timeout=10)
        d = time.time() - t0
        msgs = r.json().get("messages", [])
        record("主动触达", "获取主动触达消息队列 (/api/v1/proactive/messages)", r.status_code == 200, f"用户主动消息数: {len(msgs)}", d)
    except Exception as e:
        record("主动触达", "获取主动触达消息队列 (/api/v1/proactive/messages)", False, str(e), time.time() - t0)

    # 4. 确认 ACK
    if msg_id:
        t0 = time.time()
        try:
            body = {"user_id": TEST_USER, "message_id": msg_id, "action": "read"}
            r = requests.post(f"{BASE_URL}/api/v1/proactive/ack", json=body, timeout=10)
            d = time.time() - t0
            record("主动触达", "消息已读确认 (POST /api/v1/proactive/ack)", r.status_code == 200, "已标记已读", d)
        except Exception as e:
            record("主动触达", "消息已读确认 (POST /api/v1/proactive/ack)", False, str(e), time.time() - t0)


def test_db_routes():
    # 1. 数据库状态与白名单表探活
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/api/v1/db/status", timeout=10)
        d = time.time() - t0
        data = r.json()
        tables = data.get("tables", [])
        ok = r.status_code == 200 and data.get("status") == "connected"
        record("MySQL数据库", "数据库连接探活与表检测 (/api/v1/db/status)", ok, f"状态: {data.get('status')}, 库: {data.get('database')}, 包含数据表: {tables}", d)
    except Exception as e:
        record("MySQL数据库", "数据库连接探活与表检测 (/api/v1/db/status)", False, str(e), time.time() - t0)

    # 2. 只读 SQL 执行沙箱探针
    t0 = time.time()
    try:
        body = {"query": "SELECT 1 AS probe, 'MaoWu' AS system_name;", "max_rows": 10}
        r = requests.post(f"{BASE_URL}/api/v1/db/query", json=body, timeout=10)
        d = time.time() - t0
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "success" and len(data.get("rows", [])) > 0
        record("MySQL数据库", "安全只读SQL执行 (/api/v1/db/query)", ok, f"执行状态: {data.get('status')}, 返回行数: {len(data.get('rows', []))}, 字段: {data.get('columns')}", d)
    except Exception as e:
        record("MySQL数据库", "安全只读SQL执行 (/api/v1/db/query)", False, str(e), time.time() - t0)


def test_web_ui():
    t0 = time.time()
    try:
        r = requests.get(f"{BASE_URL}/", timeout=10)
        d = time.time() - t0
        ok = r.status_code == 200 and "MaoWu" in r.text and "文件中心" in r.text
        record("Web前端", "主控制台页面加载 (GET /)", ok, f"状态码: {r.status_code}, 页面大小: {len(r.content)} bytes, 包含MaoWu与文件中心", d)
    except Exception as e:
        record("Web前端", "主控制台页面加载 (GET /)", False, str(e), time.time() - t0)


def main():
    print("=" * 70)
    print(f"🚀 开始对远程生产服务器 ({BASE_URL}) 执行全功能 API 接口端到端测试...")
    print("=" * 70)

    test_health()
    test_web_ui()
    test_openai_models()
    test_openai_chat_completions_non_stream()
    test_openai_chat_completions_stream()
    test_workspace_files_and_download()
    test_todo_management()
    test_notes_management()
    test_web_watch_and_fetch()
    test_proactive_interaction()
    test_db_routes()

    print("=" * 70)
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = total - passed
    print(f"📊 测试总结: 总计执行 {total} 项，通过: {passed}，失败: {failed}")
    print("=" * 70)

    # 输出 Markdown 结构化汇总
    with open("tests/test_page/remote_server_api_verification.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
