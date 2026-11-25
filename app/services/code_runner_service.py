from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 危险指令与高危操作黑名单（严禁在私人代码中执行系统级破坏动作）
DANGEROUS_PATTERNS = [
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+[06]\b",
    r"rm\s+-rf\s+[/~]",
    r"rmdir\s+/[sq]\s+[a-zA-Z]:",
    r"mkfs",
    r":\(\)\s*\{\s*:\|:&\s*\};:",  # Fork bomb
    r"os\.system\s*\(\s*['\"]rm\s+-rf",
    r"shutil\.rmtree\s*\(\s*['\"]/['\"]\s*\)",
    r"shutil\.rmtree\s*\(\s*['\"][a-zA-Z]:[/\\\\]['\"]\s*\)",
]


class CodeRunnerService:
    """私人工作区代码与文件安全执行服务"""

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        if workspace_dir:
            self.workspace_dir = Path(workspace_dir).resolve()
        else:
            # 默认工作区目录：data/workspace (挂载卷持久化存储)
            project_root = Path(__file__).resolve().parent.parent.parent
            self.workspace_dir = (project_root / "data" / "workspace").resolve()

        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, relative_path: str) -> Path:
        """解析并确保路径严格限制在 data/workspace/ 沙箱工作区内，防御路径遍历"""
        clean_name = relative_path.strip().lstrip("/\\")
        # 兼容处理直接传入带有工作区前缀的路径（如 "data/workspace/foo.txt"）
        normalized = clean_name.replace("\\", "/")
        if normalized.startswith("data/workspace/"):
            clean_name = normalized[len("data/workspace/"):]

        target_path = (self.workspace_dir / clean_name).resolve()
        try:
            target_path.relative_to(self.workspace_dir)
        except ValueError as err:
            raise PermissionError(f"安全拦截：禁止越权访问工作区外部路径 '{relative_path}'") from err
        return target_path

    def _check_code_safety(self, code: str) -> tuple[bool, str]:
        """静态审计待执行的 Python 代码安全规范"""
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                return False, f"安全拦截：检测到高危系统破坏性指令模式 '{pattern}'，已拒绝执行。"
        return True, ""

    def run_python_code(self, code: str, timeout_seconds: int = 30) -> dict[str, Any]:
        """
        在 data/workspace 工作区沙箱中安全执行 Python 脚本
        - 超时自动熔断
        - 自动捕获 stdout、stderr 及新生成/修改的文件
        """
        is_safe, reason = self._check_code_safety(code)
        if not is_safe:
            return {
                "success": False,
                "stdout": "",
                "stderr": reason,
                "exit_code": -1,
                "duration": 0.0,
                "created_files": [],
            }

        # 记录执行前的文件快照
        before_files = set(self.workspace_dir.glob("*"))

        start_time = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=str(self.workspace_dir),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                encoding="utf-8",
                errors="replace",
            )
            duration = round(time.time() - start_time, 3)

            # 检查是否有新生成的文件
            after_files = set(self.workspace_dir.glob("*"))
            new_files = [f.name for f in (after_files - before_files) if f.is_file()]

            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "exit_code": proc.returncode,
                "duration": duration,
                "created_files": new_files,
            }
        except subprocess.TimeoutExpired:
            duration = round(time.time() - start_time, 3)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"执行超时：脚本运行超过最大限制 {timeout_seconds} 秒，已强制终止。",
                "exit_code": -124,
                "duration": duration,
                "created_files": [],
            }
        except Exception as exc:
            duration = round(time.time() - start_time, 3)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"运行时异常: {exc}",
                "exit_code": -1,
                "duration": duration,
                "created_files": [],
            }

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    def list_files(self, subpath: str = "") -> list[dict[str, Any]]:
        """列出工作区沙箱目录中的文件与大小信息"""
        target_dir = self._resolve_safe_path(subpath)
        if not target_dir.is_dir():
            return []

        results = []
        for item in sorted(target_dir.iterdir()):
            if item.name.startswith("."):
                continue
            is_file = item.is_file()
            stat = item.stat()
            size = stat.st_size if is_file else 0
            size_h = self._format_size(size) if is_file else "--"
            mod_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
            quoted_filename = urllib.parse.quote(item.name)
            download_url = f"/api/v1/workspace/download/{quoted_filename}" if is_file else ""

            results.append({
                "name": item.name,
                "type": "file" if is_file else "directory",
                "size_bytes": size,
                "size_human": size_h,
                "modified": mod_time,
                "modified_at": mod_time,
                "download_url": download_url,
            })
        return results

    def read_file(self, filename: str, max_chars: int = 15000) -> str:
        """读取工作区内的指定文本文件内容"""
        target_file = self._resolve_safe_path(filename)
        if not target_file.exists():
            return f"错误：工作区内不存在文件 '{filename}'"
        if not target_file.is_file():
            return f"错误：'{filename}' 是目录而不是普通文件"

        try:
            content = target_file.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                return (
                    content[:max_chars]
                    + f"\n\n[提示：文件总长度 {len(content)} 字符，已截断展示前 {max_chars} 字符]"
                )
            return content
        except Exception as exc:
            return f"读取文件失败: {exc}"

    def write_file(self, filename: str, content: str, append: bool = False) -> str:
        """写入或追加内容到工作区文件"""
        target_file = self._resolve_safe_path(filename)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        try:
            with open(target_file, mode, encoding="utf-8") as f:
                f.write(content)
            action_desc = "追加" if append else "创建/覆盖"
            return f"成功：已在工作区{action_desc}文件 '{filename}'，当前大小 {target_file.stat().st_size} 字节。"
        except Exception as exc:
            return f"写入文件失败: {exc}"

    def delete_file(self, filename: str) -> str:
        """安全删除工作区内的文件"""
        target_file = self._resolve_safe_path(filename)
        if not target_file.exists():
            return f"错误：工作区内不存在文件 '{filename}'"
        if not target_file.is_file():
            return f"安全拦截：只允许删除普通文件，不能直接删除目录 '{filename}'"

        try:
            target_file.unlink()
            return f"成功：已从工作区删除文件 '{filename}'"
        except Exception as exc:
            return f"删除文件失败: {exc}"


# 单例工厂
_code_runner_service: CodeRunnerService | None = None


def get_code_runner_service() -> CodeRunnerService:
    global _code_runner_service
    if _code_runner_service is None:
        _code_runner_service = CodeRunnerService()
    return _code_runner_service
