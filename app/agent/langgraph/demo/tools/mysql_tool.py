from __future__ import annotations

import json
from typing import Any
from langchain_core.tools import ArgsSchema, BaseTool
from pydantic import BaseModel, Field

from app.services.db_service import get_mysql_service


class MySQLSchemaInput(BaseModel):
    table_name: str | None = Field(
        default=None,
        description="要查看表结构的表名（如 'resumes', 'candidates'）。若留空或不填，则返回数据库中所有可用的表名列表。",
    )


class MySQLSchemaTool(BaseTool):
    """查询 MySQL 简历数据库 (resume_db) 的表清单与字段结构"""
    name: str = "sql_db_schema"
    description: str = (
        "获取 MySQL 简历数据库 (resume_db) 中的表名列表或指定表的字段定义。"
        "在编写 SQL 查询之前，必须先使用此工具了解有哪些表以及表的具体列名和数据类型。"
    )
    args_schema: ArgsSchema | None = MySQLSchemaInput

    def _run(self, table_name: str | None = None, **kwargs: Any) -> str:
        db = get_mysql_service()
        try:
            if not table_name or table_name.lower() in ["none", "all", ""]:
                tables = db.get_tables()
                if not tables:
                    return f"数据库 '{db.database}' 中当前暂无任何数据表（Tables 为空）。"
                return f"数据库 '{db.database}' 中的可用数据表列表：\n" + "\n".join([f"- {t}" for t in tables])
            else:
                schema = db.get_table_schema(table_name)
                return f"数据表 '{table_name}' 的字段结构定义：\n" + json.dumps(schema, ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            return f"获取表结构失败：{exc}"

    async def _arun(self, table_name: str | None = None, **kwargs: Any) -> str:
        return self._run(table_name=table_name, **kwargs)


class MySQLQueryInput(BaseModel):
    query: str = Field(
        ...,
        description="要在 MySQL 简历数据库 (resume_db) 中执行的标准 SQL 查询语句，例如 'SELECT id, name, skills FROM resumes LIMIT 10;'",
    )


class MySQLQueryTool(BaseTool):
    """在 MySQL 简历数据库 (resume_db) 中执行 SQL 查询"""
    name: str = "sql_db_query"
    description: str = (
        "在 MySQL 简历数据库 (resume_db) 中执行 SQL 查询并返回结果。"
        "可用于检索候选人简历数据、统计简历数量、匹配技能标签等。仅支持安全只读查询（禁止 DROP / TRUNCATE 等危险 DDL）。"
    )
    args_schema: ArgsSchema | None = MySQLQueryInput

    def _run(self, query: str, **kwargs: Any) -> str:
        db = get_mysql_service()
        res = db.execute_query(query)
        if res.get("status") == "error":
            return f"SQL 查询执行错误：{res.get('error')}"
        elif res.get("error"):
            return f"安全拦截：{res.get('error')}"
        
        row_count = res.get("row_count", 0)
        rows = res.get("rows", [])
        columns = res.get("columns", [])
        return (
            f"SQL 执行成功，返回 {row_count} 条记录。\n"
            f"字段列表: {columns}\n"
            f"数据明细:\n"
            + json.dumps(rows, ensure_ascii=False, indent=2, default=str)
        )

    async def _arun(self, query: str, **kwargs: Any) -> str:
        return self._run(query=query, **kwargs)
