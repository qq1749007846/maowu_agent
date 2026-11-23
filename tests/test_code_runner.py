from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from app.agent.langgraph.demo.tools.python_runner_tool import PythonRunnerTool
from app.agent.langgraph.demo.tools.workspace_file_tool import WorkspaceFileTool
from app.services.code_runner_service import CodeRunnerService


@pytest.fixture
def temp_workspace():
    """创建临时工作区用于隔离单测"""
    temp_dir = tempfile.mkdtemp(prefix="maowu_test_ws_")
    service = CodeRunnerService(workspace_dir=temp_dir)
    yield service, Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestCodeRunnerService:
    def test_normal_python_execution(self, temp_workspace):
        service, ws_dir = temp_workspace
        code = "print(10 + 20)\nfor i in range(3): print(f'item_{i}')"
        res = service.run_python_code(code)

        assert res["success"] is True
        assert res["exit_code"] == 0
        assert "30" in res["stdout"]
        assert "item_2" in res["stdout"]
        assert res["stderr"] == ""

    def test_execution_timeout_interception(self, temp_workspace):
        service, _ = temp_workspace
        # 超时设为 1 秒，代码休眠 3 秒
        code = "import time\ntime.sleep(3)"
        res = service.run_python_code(code, timeout_seconds=1)

        assert res["success"] is False
        assert res["exit_code"] == -124
        assert "执行超时" in res["stderr"]

    def test_dangerous_code_interception(self, temp_workspace):
        service, _ = temp_workspace
        dangerous_codes = [
            "import os\nos.system('rm -rf /')",
            "import os\nos.system('shutdown /s /t 0')",
            "import shutil\nshutil.rmtree('/')",
        ]
        for bad_code in dangerous_codes:
            res = service.run_python_code(bad_code)
            assert res["success"] is False
            assert "安全拦截" in res["stderr"]

    def test_file_generation_tracking(self, temp_workspace):
        service, _ = temp_workspace
        code = "with open('output_calc.txt', 'w') as f: f.write('hello from python')"
        res = service.run_python_code(code)

        assert res["success"] is True
        assert "output_calc.txt" in res["created_files"]

    def test_workspace_file_operations(self, temp_workspace):
        service, _ = temp_workspace
        # 1. 写入
        write_res = service.write_file("data.csv", "name,score\nalice,95\nbob,88\n")
        assert "成功" in write_res

        # 2. 读取
        content = service.read_file("data.csv")
        assert "alice,95" in content

        # 3. 追加
        service.write_file("data.csv", "charlie,90\n", append=True)
        updated_content = service.read_file("data.csv")
        assert "charlie,90" in updated_content

        # 4. 列出
        files = service.list_files()
        file_names = [f["name"] for f in files]
        assert "data.csv" in file_names

        # 5. 删除
        del_res = service.delete_file("data.csv")
        assert "成功" in del_res
        assert len(service.list_files()) == 0

    def test_path_traversal_blocking(self, temp_workspace):
        service, _ = temp_workspace
        with pytest.raises(PermissionError) as exc_info:
            service.read_file("../../outside.txt")
        assert "禁止越权访问工作区外部路径" in str(exc_info.value)


class TestLangGraphTools:
    def test_python_runner_tool(self):
        tool = PythonRunnerTool()
        result = tool._run("print('AGENT_SANDBOX_OK')")
        assert "AGENT_SANDBOX_OK" in result
        assert "执行成功" in result

    def test_workspace_file_tool(self):
        tool = WorkspaceFileTool()
        # 写入
        res_write = tool._run(action="write", filename="tool_test.txt", content="test_content")
        assert "成功" in res_write

        # 读取
        res_read = tool._run(action="read", filename="tool_test.txt")
        assert "test_content" in res_read

        # 列出
        res_list = tool._run(action="list")
        assert "tool_test.txt" in res_list

        # 删除
        res_del = tool._run(action="delete", filename="tool_test.txt")
        assert "成功" in res_del
