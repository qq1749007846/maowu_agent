from collections.abc import Callable
from typing import Any

from .mysql_tool import MySQLQueryTool, MySQLSchemaTool
from .weather_tool import WeatherTool

weather_tool = WeatherTool()
mysql_schema_tool = MySQLSchemaTool()
mysql_query_tool = MySQLQueryTool()

TOOLS: list[Callable[..., Any]] = [
    weather_tool,
    mysql_schema_tool,
    mysql_query_tool,
]
