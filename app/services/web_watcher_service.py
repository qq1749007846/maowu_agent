from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 MaoWuAgent/1.0"
)


class WebWatcherService:
    """网页信息抓取与目标网站变动监控服务 (基于 SQLite 与 httpx)"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path:
            self.db_path = Path(db_path).resolve()
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.db_path = (project_root / "data" / "ltm.db").resolve()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS web_watch_targets (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    selector TEXT DEFAULT '',
                    last_content_hash TEXT DEFAULT '',
                    last_content_snippet TEXT DEFAULT '',
                    last_check_time TEXT DEFAULT '',
                    last_change_time TEXT DEFAULT '',
                    check_interval_hours INTEGER DEFAULT 4,
                    status TEXT DEFAULT 'active',
                    change_summary TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_watch_user_status 
                ON web_watch_targets (user_id, status)
            """)
            conn.commit()

    def fetch_content(
        self,
        url: str,
        selector: str = "",
        max_chars: int = 4000,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """抓取网页，清洗 HTML，提取标题与纯文本内容"""
        headers = {"User-Agent": USER_AGENT}
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                response = client.get(url)
                response.raise_for_status()
                html = response.text
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)
            return {
                "success": False,
                "url": url,
                "error": str(e),
                "title": "",
                "text": "",
                "hash": "",
                "status_code": getattr(e, "response", None).status_code if hasattr(e, "response") and e.response else 500,
            }

        return self.parse_and_clean_html(html=html, url=url, selector=selector, max_chars=max_chars)

    def parse_and_clean_html(
        self,
        html: str,
        url: str = "",
        selector: str = "",
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        """解析并清洗 HTML 内容"""
        soup = BeautifulSoup(html, "html.parser")

        # 提取标题
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # 剔除噪声标签
        for tag in soup(["script", "style", "noscript", "iframe", "svg", "nav", "footer", "header"]):
            tag.decompose()

        # 根据选择器定位或默认全页面主体
        target_elem = None
        if selector:
            target_elem = soup.select_one(selector)

        if not target_elem:
            target_elem = soup.body or soup

        # 提取干净的纯文本
        raw_text = target_elem.get_text(separator="\n", strip=True)
        # 合并多余连续空行
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        content_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

        return {
            "success": True,
            "url": url,
            "title": title,
            "text": clean_text[:max_chars],
            "full_length": len(clean_text),
            "hash": content_hash,
            "status_code": 200,
        }

    def add_watch_target(
        self,
        name: str,
        url: str,
        user_id: str = "default_user",
        selector: str = "",
        check_interval_hours: int = 4,
        do_initial_fetch: bool = True,
    ) -> dict[str, Any]:
        """添加一个监控目标网站，并立刻进行首次基准拉取记录哈希值"""
        target_id = f"watch_{uuid4().hex[:10]}"
        now_iso = datetime.now(UTC).isoformat()

        initial_hash = ""
        initial_snippet = ""
        last_check = ""

        if do_initial_fetch:
            res = self.fetch_content(url, selector=selector, max_chars=500)
            if res.get("success"):
                initial_hash = res.get("hash", "")
                initial_snippet = res.get("text", "")[:300]
                last_check = now_iso

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO web_watch_targets (
                    id, user_id, name, url, selector,
                    last_content_hash, last_content_snippet,
                    last_check_time, last_change_time,
                    check_interval_hours, status, change_summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_id,
                    user_id,
                    name,
                    url,
                    selector,
                    initial_hash,
                    initial_snippet,
                    last_check,
                    "",
                    check_interval_hours,
                    "active",
                    "初始基线已建立",
                    now_iso,
                ),
            )
            conn.commit()

        return {
            "id": target_id,
            "name": name,
            "url": url,
            "selector": selector,
            "initial_hash": initial_hash,
            "initial_snippet": initial_snippet,
            "check_interval_hours": check_interval_hours,
            "status": "active",
            "created_at": now_iso,
        }

    def list_watch_targets(
        self, user_id: str = "default_user", status: str = ""
    ) -> list[dict[str, Any]]:
        """获取监控目标列表"""
        query = "SELECT * FROM web_watch_targets WHERE 1=1"
        params: list[Any] = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_watch_target(self, target_id: str) -> dict[str, Any] | None:
        """获取单个监控目标详情"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM web_watch_targets WHERE id = ?", (target_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def remove_watch_target(self, target_id: str) -> bool:
        """删除监控目标"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM web_watch_targets WHERE id = ?", (target_id,))
            conn.commit()
            return cursor.rowcount > 0

    def check_target(self, target_id: str) -> dict[str, Any]:
        """检查指定目标网站是否发生内容变动"""
        target = self.get_watch_target(target_id)
        if not target:
            return {"success": False, "error": f"Target {target_id} not found"}

        now_iso = datetime.now(UTC).isoformat()
        res = self.fetch_content(target["url"], selector=target.get("selector", ""), max_chars=1000)

        if not res.get("success"):
            return {
                "success": False,
                "target_id": target_id,
                "name": target["name"],
                "url": target["url"],
                "error": res.get("error"),
            }

        new_hash = res.get("hash", "")
        new_snippet = res.get("text", "")[:300]
        old_hash = target.get("last_content_hash", "")
        has_changed = False
        summary = ""

        if old_hash and old_hash != new_hash:
            has_changed = True
            summary = f"检测到内容变动: 标题【{res.get('title')}】，最新内容摘要: {new_snippet[:120]}..."
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE web_watch_targets
                    SET last_content_hash = ?,
                        last_content_snippet = ?,
                        last_check_time = ?,
                        last_change_time = ?,
                        change_summary = ?
                    WHERE id = ?
                    """,
                    (new_hash, new_snippet, now_iso, now_iso, summary, target_id),
                )
                conn.commit()
        else:
            # 未变动或初次校准
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE web_watch_targets
                    SET last_content_hash = ?,
                        last_content_snippet = ?,
                        last_check_time = ?
                    WHERE id = ?
                    """,
                    (new_hash, new_snippet, now_iso, target_id),
                )
                conn.commit()

        return {
            "success": True,
            "target_id": target_id,
            "name": target["name"],
            "url": target["url"],
            "has_changed": has_changed,
            "old_hash": old_hash,
            "new_hash": new_hash,
            "summary": summary,
            "new_snippet": new_snippet,
            "title": res.get("title", ""),
            "last_check_time": now_iso,
        }

    def check_all_due(self, user_id: str = "default_user") -> list[dict[str, Any]]:
        """巡检所有满足检测时间周期的目标，返回检测到发生变动的所有目标"""
        targets = self.list_watch_targets(user_id=user_id, status="active")
        changed_targets = []
        now = time.time()

        for t in targets:
            last_check_str = t.get("last_check_time", "")
            interval_sec = (t.get("check_interval_hours") or 4) * 3600

            should_check = True
            if last_check_str:
                try:
                    last_check_dt = datetime.fromisoformat(last_check_str)
                    if now - last_check_dt.timestamp() < interval_sec:
                        should_check = False
                except Exception:
                    should_check = True

            if should_check:
                result = self.check_target(t["id"])
                if result.get("has_changed"):
                    changed_targets.append(result)

        return changed_targets


# 全局单例工厂
_web_watcher_service: WebWatcherService | None = None


def get_web_watcher_service() -> WebWatcherService:
    global _web_watcher_service
    if _web_watcher_service is None:
        _web_watcher_service = WebWatcherService()
    return _web_watcher_service

