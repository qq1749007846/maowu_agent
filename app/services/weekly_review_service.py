from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.services.code_runner_service import get_code_runner_service
from app.services.ltm_service import LTMService
from app.services.task_note_service import get_task_note_service
from app.services.push_service import get_push_service

logger = logging.getLogger(__name__)

REPORT_DIR = Path("data/workspace/weekly_reports")


class WeeklyTechReviewService:
    """第五阶段：周度技术体检与复盘报告生成引擎 (Weekly Tech Review Service)
    
    职责：
    1. 汇总统计近 7 天内的：完成与拖延 TODO、沉淀的技术笔记、沙箱导出的文件、LTM 长期记忆事件；
    2. 基于 LLM 并严格注入“猫老”资深技术导师拟人化视角，生成《周度技术成长体检报告》；
    3. 输出纯粹 Markdown 及自带现代审美的独立 HTML 可视化报告（含五维技术能力雷达评分）；
    4. 自动落盘工作区并支持一键通过外呼渠道推送至用户微信/群聊。
    """

    def __init__(self, ltm_service: LTMService | None = None) -> None:
        self.ltm_service = ltm_service or LTMService()
        self.task_service = get_task_note_service()
        self.code_runner = get_code_runner_service()
        self.push_service = get_push_service()
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

    def _get_llm(self) -> ChatOpenAI | None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return None
        return ChatOpenAI(
            model=os.getenv("DEFAULT_MODEL", "openai/deepseek-v4-pro").split("/")[-1],
            api_key=api_key,
            base_url=os.getenv("OPENAI_API_BASE", "https://model-api.datagrand.com/v1"),
            temperature=0.3,
        )

    def _collect_weekly_facts(self, user_id: str) -> dict[str, Any]:
        """收集用户一周内的技术产出与执行事实"""
        # 1. 待办事项
        tasks = self.task_service.list_tasks(user_id=user_id, limit=50)
        completed_tasks = [t for t in tasks if t.get("status") in ["done", "completed"]]
        pending_tasks = [t for t in tasks if t.get("status") not in ["done", "completed"]]
        high_pending = [t for t in pending_tasks if t.get("priority") == "high"]

        # 2. 技术笔记
        notes = self.task_service.search_notes(user_id=user_id, limit=20)

        # 3. 工作区文件
        files = self.code_runner.list_files()

        # 4. 长期记忆画像与事件
        try:
            profile = self.ltm_service.get_user_profile(user_id=user_id)
        except Exception:
            profile = None

        try:
            episodics = self.ltm_service.search_episodic_memories(user_id=user_id, query="", top_k=10)
        except Exception:
            episodics = []

        return {
            "user_id": user_id,
            "period": f"{datetime.now().strftime('%Y-%m-%d')} 周度体检",
            "task_stats": {
                "total": len(tasks),
                "completed_count": len(completed_tasks),
                "pending_count": len(pending_tasks),
                "high_priority_pending": len(high_pending),
                "completed_titles": [t.get("title") for t in completed_tasks[:5]],
                "pending_titles": [t.get("title") for t in pending_tasks[:5]],
            },
            "note_stats": {
                "count": len(notes),
                "titles": [n.get("title") for n in notes[:5]],
            },
            "workspace_files": [f.get("name") for f in files if f.get("type") == "file"][:8],
            "profile": {
                "primary_languages": profile.primary_languages if profile else ["Python", "FastAPI"],
                "tech_stack": profile.tech_stack if profile else ["Docker", "LangGraph", "MySQL"],
            },
            "recent_events": [e.title for e in episodics[:5]],
        }

    def _compute_fallback_radar(self, facts: dict[str, Any]) -> dict[str, int]:
        """基于确定性指标快速推算技术雷达初评（防止大模型超时或离线）"""
        comp_count = facts["task_stats"]["completed_count"]
        high_pen = facts["task_stats"]["high_priority_pending"]
        note_count = facts["note_stats"]["count"]
        file_count = len(facts["workspace_files"])

        # 交付力 delivery
        delivery = min(95, max(50, 60 + comp_count * 8 - high_pen * 10))
        # 动手/沙箱 coding_sandbox
        coding = min(95, max(55, 65 + file_count * 6))
        # 总结/学习 learning
        learning = min(95, max(50, 60 + note_count * 9))
        # 架构与排障基准
        architecture = 78
        troubleshooting = 82

        return {
            "architecture": architecture,
            "coding_sandbox": coding,
            "troubleshooting": troubleshooting,
            "delivery": delivery,
            "learning": learning,
        }

    async def generate_weekly_report(
        self,
        user_id: str = "default_user",
        auto_push: bool = False,
    ) -> dict[str, Any]:
        """生成周度技术体检与复盘报告"""
        facts = self._collect_weekly_facts(user_id)
        now_str = datetime.now().strftime("%Y%m%d")
        report_id = f"review_{now_str}_{uuid4().hex[:6]}"

        llm = self._get_llm()
        radar_scores = self._compute_fallback_radar(facts)
        pulse_summary = ""
        highlights: list[str] = []
        risks: list[str] = []
        prescription = ""

        if llm:
            prompt = (
                f"你是 MaoWu（猫老），一位犀利务实、一针见血、望闻问切的技术老中医导师。\n"
                f"请根据用户本周的真实技术执行与产出事实，进行一次深度切脉复盘，并以严格的 JSON 格式输出：\n\n"
                f"【本周事实输入】：\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
                f"【输出 JSON 契约】：\n"
                f"{{\n"
                f"  \"title\": \"周度技术体检脉案（第 XX 周）\",\n"
                f"  \"tcm_pulse_check\": \"猫老切脉总评（针对本周完成度、拖延点、技术心力状态进行毒舌但切中要害的导师把脉点评，150字左右）\",\n"
                f"  \"highlights\": [\"本周核心攻坚与交付战果1\", \"战果2\"],\n"
                f"  \"blockers_and_risks\": [\"存在的拖延病灶或架构隐患1\", \"隐患2\"],\n"
                f"  \"radar_scores\": {{\n"
                f"    \"architecture\": 70-95,\n"
                f"    \"coding_sandbox\": 70-95,\n"
                f"    \"troubleshooting\": 70-95,\n"
                f"    \"delivery\": 60-95,\n"
                f"    \"learning\": 60-95\n"
                f"  }},\n"
                f"  \"prescription_next_week\": \"下周攻坚处方（具体可落地的 1~2 项硬核攻坚目标，杜绝套话）\"\n"
                f"}}\n"
                f"注意：只输出合法的 JSON，不要输出任何额外文本。"
            )

            try:
                res = await llm.ainvoke([
                    SystemMessage(content="你是一位专业的技术教练和老中医风格架构导师。"),
                    HumanMessage(content=prompt),
                ])
                raw_text = res.content.strip()
                if "```json" in raw_text:
                    raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_text:
                    raw_text = raw_text.split("```")[1].split("```")[0].strip()
                parsed = json.loads(raw_text)

                pulse_summary = parsed.get("tcm_pulse_check", "")
                highlights = parsed.get("highlights", [])
                risks = parsed.get("blockers_and_risks", [])
                prescription = parsed.get("prescription_next_week", "")
                if isinstance(parsed.get("radar_scores"), dict):
                    for k in radar_scores.keys():
                        if k in parsed["radar_scores"]:
                            radar_scores[k] = int(parsed["radar_scores"][k])
            except Exception as e:
                logger.error(f"Failed to generate review via LLM: {e}")

        if not pulse_summary:
            pulse_summary = (
                f"*提笔捋须，目光扫过病案* 本周完成了 {facts['task_stats']['completed_count']} 项任务，"
                f"沙箱产出了 {len(facts['workspace_files'])} 个数据实体文件。手脚还算勤快，"
                f"但尚有 {facts['task_stats']['high_priority_pending']} 项高优待办悬而未决。技术功底在长，但切忌虎头蛇尾！"
            )
        if not highlights:
            highlights = [
                f"成功闭环 {facts['task_stats']['completed_count']} 项核心待办并落盘沉淀",
                f"沙箱执行产生 {len(facts['workspace_files'])} 份数据产物（含实体 Excel/爬虫脚本）",
                f"沉淀 {facts['note_stats']['count']} 条技术备忘与踩坑秘籍",
            ]
        if not risks:
            risks = [
                f"仍有 {facts['task_stats']['pending_count']} 项未结清待办事项，需防范堆积疲劳",
                "关注分布式高并发边界条件与异常重试熔断机制",
            ]
        if not prescription:
            prescription = "清空高优逾期待办，聚焦单一难点深挖；周五准时封板复盘，勿将债务拖入周末。"

        # 生成 Markdown 内容
        md_content = self._render_markdown_report(
            user_id=user_id,
            now_str=now_str,
            pulse_summary=pulse_summary,
            highlights=highlights,
            risks=risks,
            radar_scores=radar_scores,
            prescription=prescription,
            facts=facts,
        )

        # 生成独立 HTML 内容
        html_content = self._render_html_report(
            user_id=user_id,
            now_str=now_str,
            pulse_summary=pulse_summary,
            highlights=highlights,
            risks=risks,
            radar_scores=radar_scores,
            prescription=prescription,
            facts=facts,
        )

        # 持久化落盘
        md_filename = f"技术成长周报_{now_str}.md"
        html_filename = f"技术成长周报_{now_str}.html"
        md_path = REPORT_DIR / md_filename
        html_path = REPORT_DIR / html_filename

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # 同时向主工作区根目录同步一份，确保工作区中心第一眼可见
        root_ws = Path("data/workspace")
        with open(root_ws / md_filename, "w", encoding="utf-8") as f:
            f.write(md_content)
        with open(root_ws / html_filename, "w", encoding="utf-8") as f:
            f.write(html_content)

        report_meta = {
            "report_id": report_id,
            "user_id": user_id,
            "date": now_str,
            "title": f"MaoWu 技术成长体检报告 ({now_str})",
            "pulse_check": pulse_summary,
            "radar_scores": radar_scores,
            "highlights": highlights,
            "risks": risks,
            "prescription": prescription,
            "md_file": md_filename,
            "html_file": html_filename,
            "download_url_html": f"/api/v1/workspace/download/{html_filename}",
            "download_url_md": f"/api/v1/workspace/download/{md_filename}",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 若开启自动推送，则主动下发微信/QQ
        if auto_push:
            push_title = f"周度技术体检报告出炉 ({now_str})"
            push_body = f"{pulse_summary}\n\n🏆 攻坚战果：\n" + "\n".join(f"• {h}" for h in highlights[:2]) + f"\n\n💊 猫老处方：\n{prescription}"
            await self.push_service.push_message(user_id=user_id, title=push_title, content=push_body)

        return report_meta

    def _render_markdown_report(
        self,
        user_id: str,
        now_str: str,
        pulse_summary: str,
        highlights: list[str],
        risks: list[str],
        radar_scores: dict[str, int],
        prescription: str,
        facts: dict[str, Any],
    ) -> str:
        return f"""# 🩺 MaoWu 技术成长体检报告 ({now_str})
> **受检人**：`{user_id}` · **主诊导师**：MaoWu（猫老） · **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

### 一、脉象总评（猫老切脉）
{pulse_summary}

---

### 二、技术能力五维雷达评估
| 评估维度 | 得分 (0-100) | 评级 | 诊断说明 |
| :--- | :---: | :---: | :--- |
| **架构视野 (Architecture)** | **{radar_scores.get('architecture', 80)}** | {'优秀' if radar_scores.get('architecture', 80) >= 85 else '良好'} | 全局系统解耦、异步化与状态机设计能力 |
| **沙箱实操 (Coding & Sandbox)** | **{radar_scores.get('coding_sandbox', 80)}** | {'优秀' if radar_scores.get('coding_sandbox', 80) >= 85 else '良好'} | Python 自动化、实体 Excel 导出与数据处理动手力 |
| **故障根治 (Troubleshooting)** | **{radar_scores.get('troubleshooting', 80)}** | {'优秀' if radar_scores.get('troubleshooting', 80) >= 85 else '良好'} | 根因深挖、排障闭环与稳定性认知 |
| **敏捷交付 (Delivery)** | **{radar_scores.get('delivery', 80)}** | {'优秀' if radar_scores.get('delivery', 80) >= 85 else '良好'} | TODO 结清速度、拖延控制与执行节奏 |
| **知识沉淀 (Learning & Reflection)** | **{radar_scores.get('learning', 80)}** | {'优秀' if radar_scores.get('learning', 80) >= 85 else '良好'} | 技术笔记积累与反思复盘复用度 |

---

### 三、本周战果与攻坚攻克 (Highlights)
{chr(10).join(f"- ✅ **{h}**" for h in highlights)}

---

### 四、拖延病灶与技术债务 (Risks & Blockers)
{chr(10).join(f"- ⚠️ {r}" for r in risks)}

---

### 五、下周攻坚处方 (Prescription)
> 💊 **猫老亲开方子**：  
> {prescription}

*报告由 MaoWu Agent 认知与反思引擎自动归纳生成 · 见证技术成长每一步*
"""

    def _render_html_report(
        self,
        user_id: str,
        now_str: str,
        pulse_summary: str,
        highlights: list[str],
        risks: list[str],
        radar_scores: dict[str, int],
        prescription: str,
        facts: dict[str, Any],
    ) -> str:
        radar_bars = ""
        dim_labels = {
            "architecture": ("架构视野", "Architecture", "#3b82f6"),
            "coding_sandbox": ("沙箱动手", "Coding & Sandbox", "#10b981"),
            "troubleshooting": ("故障排查", "Troubleshooting", "#f59e0b"),
            "delivery": ("敏捷交付", "Delivery", "#8b5cf6"),
            "learning": ("知识复盘", "Learning", "#ec4899"),
        }
        for k, (cn, en, color) in dim_labels.items():
            score = radar_scores.get(k, 75)
            radar_bars += f"""
            <div style="margin-bottom: 14px;">
              <div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; margin-bottom: 4px;">
                <span>{cn} <span style="font-weight: 400; color: #64748b;">({en})</span></span>
                <span style="color: {color};">{score} / 100</span>
              </div>
              <div style="height: 10px; background: #e2e8f0; border-radius: 999px; overflow: hidden;">
                <div style="width: {score}%; height: 100%; background: {color}; border-radius: 999px; transition: width 0.6s ease;"></div>
              </div>
            </div>
            """

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>MaoWu 技术成长体检报告 - {now_str}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: #f8fafc;
      color: #1e293b;
      margin: 0;
      padding: 30px 20px;
      line-height: 1.6;
    }}
    .container {{
      max-width: 820px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.02);
      border: 1px solid #e2e8f0;
      padding: 36px 42px;
    }}
    .header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 2px solid #f1f5f9;
      padding-bottom: 20px;
      margin-bottom: 24px;
    }}
    .title-box h1 {{
      margin: 0 0 6px 0;
      font-size: 24px;
      color: #0f172a;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 12px;
      background: #ecfdf5;
      color: #059669;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
    }}
    .card {{
      background: #f8fafc;
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 24px;
      border: 1px solid #e2e8f0;
    }}
    .card h3 {{
      margin-top: 0;
      margin-bottom: 12px;
      font-size: 16px;
      color: #334155;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .highlight-list, .risk-list {{
      margin: 0;
      padding-left: 20px;
    }}
    .highlight-list li {{
      margin-bottom: 8px;
      color: #0f766e;
    }}
    .risk-list li {{
      margin-bottom: 8px;
      color: #b45309;
    }}
    .prescription {{
      background: #fefce8;
      border-left: 4px solid #eab308;
      padding: 16px 20px;
      border-radius: 0 12px 12px 0;
      font-weight: 500;
      color: #854d0e;
    }}
    .footer {{
      margin-top: 36px;
      text-align: center;
      font-size: 12px;
      color: #94a3b8;
      border-top: 1px solid #f1f5f9;
      padding-top: 16px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="title-box">
        <h1>🩺 MaoWu 技术成长周度体检报告</h1>
        <div style="font-size: 13px; color: #64748b;">
          受检人: <strong>{user_id}</strong> · 主诊导师: <strong>MaoWu（猫老）</strong> · 周期: {now_str}
        </div>
      </div>
      <div>
        <span class="badge">已归档 · 官方体检单</span>
      </div>
    </div>

    <!-- 脉象总评 -->
    <div class="card" style="background: #eff6ff; border-color: #bfdbfe;">
      <h3 style="color: #1e40af;">🩺 猫老切脉总评</h3>
      <div style="font-size: 15px; color: #1e3a8a; line-height: 1.7;">
        {pulse_summary}
      </div>
    </div>

    <!-- 五维技术能力雷达 -->
    <div class="card">
      <h3>📊 技术能力五维雷达评估</h3>
      <div style="margin-top: 16px;">
        {radar_bars}
      </div>
    </div>

    <!-- 战果与隐患两栏 -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px;">
      <div class="card" style="margin-bottom: 0;">
        <h3 style="color: #0f766e;">🏆 本周技术战果</h3>
        <ul class="highlight-list">
          {''.join(f'<li>{h}</li>' for h in highlights)}
        </ul>
      </div>
      <div class="card" style="margin-bottom: 0;">
        <h3 style="color: #b45309;">⚠️ 拖延病灶与风险</h3>
        <ul class="risk-list">
          {''.join(f'<li>{r}</li>' for r in risks)}
        </ul>
      </div>
    </div>

    <!-- 下周攻坚处方 -->
    <div class="card" style="border: none; padding: 0; background: transparent;">
      <div class="prescription">
        <strong style="display: block; margin-bottom: 6px; font-size: 15px;">💊 猫老亲开·下周攻坚处方：</strong>
        {prescription}
      </div>
    </div>

    <div class="footer">
      MaoWu Agent 技术成长伴随式智能体 · 见证工程师的每一寸蜕变
    </div>
  </div>
</body>
</html>
"""

    def get_latest_report(self, user_id: str = "default_user") -> dict[str, Any] | None:
        """获取最近一份生成的报告"""
        html_files = sorted(list(REPORT_DIR.glob("*.html")), reverse=True)
        if not html_files:
            # 尝试从根工作区查找
            html_files = sorted(list(Path("data/workspace").glob("技术成长周报_*.html")), reverse=True)
            if not html_files:
                return None

        latest = html_files[0]
        facts = self._collect_weekly_facts(user_id)
        radar = self._compute_fallback_radar(facts)
        return {
            "title": latest.stem,
            "filename": latest.name,
            "html_url": f"/api/v1/workspace/download/{latest.name}",
            "modified": datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "radar_scores": radar,
        }

    def list_history(self) -> list[dict[str, Any]]:
        """列出所有历史周报"""
        files = sorted(list(REPORT_DIR.glob("*.html")), reverse=True)
        items = []
        for f in files:
            items.append({
                "title": f.stem,
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "download_url": f"/api/v1/workspace/download/{f.name}",
                "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        return items

    def get_skill_radar(self, user_id: str = "default_user") -> dict[str, Any]:
        """获取用户当前技术能力雷达指标及演进画像"""
        facts = self._collect_weekly_facts(user_id)
        radar = self._compute_fallback_radar(facts)
        return {
            "user_id": user_id,
            "radar_scores": radar,
            "tech_stack": facts["profile"]["tech_stack"],
            "primary_languages": facts["profile"]["primary_languages"],
            "tasks_completed": facts["task_stats"]["completed_count"],
            "tasks_pending": facts["task_stats"]["pending_count"],
            "notes_accumulated": facts["note_stats"]["count"],
            "artifacts_generated": len(facts["workspace_files"]),
        }


# 全局单例
_weekly_review_service = WeeklyTechReviewService()


def get_weekly_review_service() -> WeeklyTechReviewService:
    return _weekly_review_service
