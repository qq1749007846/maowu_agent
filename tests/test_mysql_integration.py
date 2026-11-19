from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.agent.langgraph.demo.tools.mysql_tool import MySQLQueryTool, MySQLSchemaTool
from app.bootstrap.app_factory import create_app
from app.bootstrap.config import get_config
from app.services.db_service import MySQLService


class TestMySQLService:
    """测试 MySQL 数据库服务逻辑与安全防护"""

    def test_ddl_security_interception(self):
        service = MySQLService()
        # DROP / TRUNCATE 必须被阻断
        res1 = service.execute_query("DROP TABLE resumes;")
        assert "forbidden" in res1.get("error", "").lower()

        res2 = service.execute_query("TRUNCATE TABLE candidates;")
        assert "forbidden" in res2.get("error", "").lower()

        res3 = service.execute_query("   alter table users drop column age;")
        assert "forbidden" in res3.get("error", "").lower()

    def test_empty_query_handling(self):
        service = MySQLService()
        res = service.execute_query("   ")
        assert "cannot be empty" in res.get("error", "")

    def test_table_schema_whitelist_validation(self):
        service = MySQLService()
        with patch.object(service, "get_tables", return_value=["resumes", "skills"]):
            with pytest.raises(ValueError) as excinfo:
                service.get_table_schema("non_existent_table")
            assert "does not exist" in str(excinfo.value)


class TestMySQLAgentTools:
    """测试暴露给 LangGraph Agent 的 MySQL 工具集"""

    def test_mysql_schema_tool_list_tables(self):
        tool = MySQLSchemaTool()
        assert tool.name == "sql_db_schema"
        assert "resume_db" in tool.description

        with patch("app.agent.langgraph.demo.tools.mysql_tool.get_mysql_service") as mock_get_db:
            mock_db = MagicMock()
            mock_db.database = "resume_db"
            mock_db.get_tables.return_value = ["resumes", "job_positions"]
            mock_get_db.return_value = mock_db

            output = tool._run(table_name=None)
            assert "resumes" in output
            assert "job_positions" in output

    def test_mysql_query_tool_safe_execution(self):
        tool = MySQLQueryTool()
        assert tool.name == "sql_db_query"

        with patch("app.agent.langgraph.demo.tools.mysql_tool.get_mysql_service") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute_query.return_value = {
                "status": "success",
                "columns": ["id", "candidate_name", "skills"],
                "row_count": 1,
                "rows": [{"id": 1, "candidate_name": "张三", "skills": "Python, LangGraph"}],
            }
            mock_get_db.return_value = mock_db

            output = tool._run(query="SELECT * FROM resumes LIMIT 1;")
            assert "张三" in output
            assert "LangGraph" in output

    def test_mysql_query_tool_ddl_blocking(self):
        tool = MySQLQueryTool()
        with patch("app.agent.langgraph.demo.tools.mysql_tool.get_mysql_service") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute_query.return_value = {"error": "DDL command 'DROP' is forbidden for security safety."}
            mock_get_db.return_value = mock_db

            output = tool._run(query="DROP TABLE resumes;")
            assert "安全拦截" in output


class TestMySQLHTTPRoutes:
    """测试 MySQL 数据库 HTTP API 接口"""

    def test_db_status_and_query_endpoints(self):
        app = create_app(get_config())
        client = TestClient(app)

        with patch("app.http.routes.db_routes.get_mysql_service") as mock_get_db:
            mock_db = MagicMock()
            mock_db.test_connection.return_value = (True, "Connected to MySQL 5.7.35, database 'resume_db' ready")
            mock_db.get_tables.return_value = ["resumes", "skills"]
            mock_db.database = "resume_db"
            mock_db.host = "124.222.9.212"
            mock_db.port = 3306
            mock_db.execute_query.return_value = {
                "status": "success",
                "columns": ["count"],
                "row_count": 1,
                "rows": [{"count": 42}],
            }
            mock_get_db.return_value = mock_db

            # 1. 检查状态接口
            status_resp = client.get("/api/v1/db/status")
            assert status_resp.status_code == 200
            s_data = status_resp.json()
            assert s_data["status"] == "connected"
            assert s_data["database"] == "resume_db"
            assert "resumes" in s_data["tables"]

            # 2. 查询接口
            query_resp = client.post("/api/v1/db/query", json={"query": "SELECT COUNT(*) FROM resumes;"})
            assert query_resp.status_code == 200
            q_data = query_resp.json()
            assert q_data["status"] == "success"
            assert q_data["rows"][0]["count"] == 42
