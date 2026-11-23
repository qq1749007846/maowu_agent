from __future__ import annotations

import json
from typing import Any
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.services.code_runner_service import get_code_runner_service


class PythonRunnerInput(BaseModel):
    code: str = Field(description="需要执行的完整 Python 代码字符串")


class PythonRunnerTool(BaseTool):
    name: str = "execute_python"
    description: str = (
        "在安全的工作区沙箱环境中执行 Python 代码脚本并捕获结果。"
        "适合进行数据分析、数值计算、文本清洗、批量文件生成与自动化逻辑。"
        "工作目录为 data/workspace/，生成的文件将持久化保存在该目录中。"
    )
    args_schema: type[BaseModel] = PythonRunnerInput

    def _run(self, code: str, **kwargs: Any) -> str:
        runner = get_code_runner_service()
        res = runner.run_python_code(code)

        output_parts = []
        if res["success"]:
            output_parts.append(f"【执行成功】(耗时 {res['duration']}s, 退出码 {res['exit_code']})")
            if res["stdout"]:
                output_parts.append(f"输出 (stdout):\n{res['stdout']}")
            else:
                output_parts.append("输出 (stdout): [代码无任何控制台输出]")
            if res["created_files"]:
                output_parts.append(f"工作区新增文件: {', '.join(res['created_files'])}")
        else:
            output_parts.append(f"【执行失败】(耗时 {res['duration']}s, 退出码 {res['exit_code']})")
            if res["stderr"]:
                output_parts.append(f"错误 (stderr):\n{res['stderr']}")
            if res["stdout"]:
                output_parts.append(f"输出 (stdout):\n{res['stdout']}")

        return "\n\n".join(output_parts)

    async def _arun(self, code: str, **kwargs: Any) -> str:
        return self._run(code, **kwargs)
