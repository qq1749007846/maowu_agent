from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.db_service import get_mysql_service

logger = logging.getLogger(__name__)

db_router = APIRouter(prefix="/api/v1/db", tags=["MySQL Database"])


class SQLQueryRequest(BaseModel):
    query: str = Field(..., description="要执行的 SQL 查询语句")
    max_rows: int = Field(default=100, description="最多返回记录数")


@db_router.get("/status")
async def get_db_status() -> dict[str, Any]:
    """检查 MySQL 简历数据库连接健康状态与当前数据表列表"""
    service = get_mysql_service()
    ok, msg = service.test_connection()
    tables = service.get_tables() if ok else []
    return {
        "status": "connected" if ok else "disconnected",
        "message": msg,
        "database": service.database,
        "host": service.host,
        "port": service.port,
        "tables": tables,
        "table_count": len(tables),
    }


@db_router.post("/query")
async def execute_sql_query(request: SQLQueryRequest) -> dict[str, Any]:
    """通过 API 直接执行 SQL 查询（带安全防护）"""
    service = get_mysql_service()
    result = service.execute_query(request.query, max_rows=request.max_rows)
    return result
