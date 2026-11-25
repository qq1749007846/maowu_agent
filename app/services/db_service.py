from __future__ import annotations

import logging
import os
from typing import Any
import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger(__name__)


class MySQLService:
    """MySQL 数据库连接与操作服务（简历数据库 resume_db 集成）"""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        self.host = host or os.getenv("MYSQL_HOST", "localhost")
        self.port = int(port or os.getenv("MYSQL_PORT", 3306))
        self.user = user or os.getenv("MYSQL_USER", "root")
        self.password = password or os.getenv("MYSQL_PASSWORD", "root123")
        self.database = database or os.getenv("MYSQL_DATABASE", "resume_db")

    def get_connection(self, select_db: bool = True) -> pymysql.Connection:
        """获取底层 PyMySQL 数据库连接"""
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database if select_db else None,
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=5,
            autocommit=True,
        )

    def test_connection(self) -> tuple[bool, str]:
        """连通性与健康状态自检"""
        try:
            with self.get_connection(select_db=False) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT VERSION() AS version;")
                    row = cursor.fetchone()
                    version = row["version"] if row else "unknown"

                    # 检查目标数据库是否存在，若不存在则安全创建
                    cursor.execute(
                        f"CREATE DATABASE IF NOT EXISTS `{self.database}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
                    )

            # 再次确认连接到目标数据库
            with self.get_connection(select_db=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT DATABASE() AS current_db;")
                    cur_db = cursor.fetchone()
                    return True, f"Connected to MySQL {version}, database '{self.database}' ready"
        except Exception as exc:
            logger.error(f"MySQL connection test failed: {exc}", exc_info=True)
            return False, str(exc)

    def get_tables(self) -> list[str]:
        """获取目标数据库中的所有表名"""
        try:
            with self.get_connection(select_db=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SHOW TABLES;")
                    rows = cursor.fetchall()
                    tables = []
                    for row in rows:
                        tables.extend(row.values())
                    return tables
        except Exception as exc:
            logger.error(f"Failed to fetch tables from {self.database}: {exc}")
            return []

    def get_table_schema(self, table_name: str) -> list[dict[str, Any]]:
        """获取指定表的数据结构定义 (DESCRIBE)"""
        try:
            # 使用白名单校验表名避免 SQL 注入
            valid_tables = self.get_tables()
            if table_name not in valid_tables:
                raise ValueError(f"Table '{table_name}' does not exist in database '{self.database}'")

            with self.get_connection(select_db=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(f"DESCRIBE `{table_name}`;")
                    return cursor.fetchall()
        except Exception as exc:
            logger.error(f"Failed to get schema for table '{table_name}': {exc}")
            raise

    def execute_query(self, query: str, max_rows: int = 100) -> dict[str, Any]:
        """执行 SQL 查询并返回安全格式化结果（内置只读防护与最大行数截断）"""
        cleaned_query = query.strip()
        if not cleaned_query:
            return {"error": "Query cannot be empty"}

        # 针对潜在危险指令做只读阻断（如 DROP, TRUNCATE 等）
        first_word = cleaned_query.split()[0].upper()
        if first_word in ["DROP", "TRUNCATE", "ALTER"]:
            return {"error": f"DDL command '{first_word}' is forbidden for security safety."}

        try:
            with self.get_connection(select_db=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(cleaned_query)
                    if cursor.description:
                        rows = cursor.fetchmany(max_rows)
                        total_fetched = len(rows)
                        return {
                            "status": "success",
                            "columns": [col[0] for col in cursor.description],
                            "row_count": total_fetched,
                            "rows": rows,
                        }
                    else:
                        # 如 INSERT/UPDATE
                        return {
                            "status": "success",
                            "affected_rows": cursor.rowcount,
                            "message": f"Query executed successfully, affected rows: {cursor.rowcount}",
                        }
        except Exception as exc:
            logger.error(f"SQL execution failed: {exc}", exc_info=True)
            return {"status": "error", "error": str(exc)}


# 单例实例
mysql_service = MySQLService()


def get_mysql_service() -> MySQLService:
    """获取 MySQL 全局服务单例"""
    return mysql_service
