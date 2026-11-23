from collections.abc import Callable
from typing import Any

from .mysql_tool import MySQLQueryTool, MySQLSchemaTool
from .python_runner_tool import PythonRunnerTool
from .weather_tool import WeatherTool
from .workspace_file_tool import WorkspaceFileTool

weather_tool = WeatherTool()
mysql_schema_tool = MySQLSchemaTool()
mysql_query_tool = MySQLQueryTool()
python_runner_tool = PythonRunnerTool()
workspace_file_tool = WorkspaceFileTool()

TOOLS: list[Callable[..., Any]] = [
    python_runner_tool,
    workspace_file_tool,
    mysql_schema_tool,
    mysql_query_tool,
    weather_tool,
]
