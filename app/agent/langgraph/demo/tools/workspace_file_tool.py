from __future__ import annotations

import json
from typing import Any
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.services.code_runner_service import get_code_runner_service


class WorkspaceFileInput(BaseModel):
    action: str = Field(description="操作动作：list（列出目录）、read（读取文件）、write（写入或覆盖）、append（追加内容）、delete（删除文件）")
    filename: str = Field(default="", description="文件名或相对路径，例如 'test.csv', 'logs/output.txt'")
    content: str = Field(default="", description="文件内容，在 write 或 append 动作时使用")


class WorkspaceFileTool(BaseTool):
    name: str = "manage_workspace_files"
    description: str = (
        "管理私人沙箱工作区 (data/workspace/) 内的文件。"
        "支持查看工作区文件列表 (list)、读取指定文件内容 (read)、写入/创建文件 (write)、追加内容 (append) 及删除文件 (delete)。"
    )
    args_schema: type[BaseModel] = WorkspaceFileInput

    def _run(self, action: str, filename: str = "", content: str = "", **kwargs: Any) -> str:
        runner = get_code_runner_service()
        clean_action = action.lower().strip()

        if clean_action == "list":
            files = runner.list_files(filename)
            if not files:
                return "工作区目录为空，暂无文件。"
            lines = ["工作区文件列表:"]
            for f in files:
                lines.append(f"- [{f['type'].upper()}] {f['name']} ({f['size_bytes']} bytes, 修改于 {f['modified_at']})")
            return "\n".join(lines)

        elif clean_action == "read":
            if not filename.strip():
                return "错误：read 动作必须指定 filename。"
            return runner.read_file(filename.strip())

        elif clean_action == "write":
            if not filename.strip():
                return "错误：write 动作必须指定 filename。"
            return runner.write_file(filename.strip(), content, append=False)

        elif clean_action == "append":
            if not filename.strip():
                return "错误：append 动作必须指定 filename。"
            return runner.write_file(filename.strip(), content, append=True)

        elif clean_action == "delete":
            if not filename.strip():
                return "错误：delete 动作必须指定 filename。"
            return runner.delete_file(filename.strip())

        else:
            return f"错误：不支持的 action '{action}'。有效选项为: list, read, write, append, delete。"

    async def _arun(self, action: str, filename: str = "", content: str = "", **kwargs: Any) -> str:
        return self._run(action, filename, content, **kwargs)
