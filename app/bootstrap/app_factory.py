from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import time
from uuid import uuid4

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# 全局最近 HTTP 访问记录环形缓冲区（最多保留 100 条）
_RECENT_REQUESTS: deque[dict] = deque(maxlen=100)

# from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator as PrometheusInstrumentator

from app.container import Container
from app.http.middleware.cors_middleware import CORSConfig, setup_cors_middleware
from app.proactive import proactive_scheduler
from app.subagents import dispatcher, init_subagents
from app.utils.utils import is_valid_uuid4

from ..http.routes import (
    astrbot_router,
    db_router,
    health_router,
    proactive_router,
    runs_router,
    task_note_router,
    thread_router,
    web_watch_router,
    workspace_router,
)
from .agent_registry import register_agents
from .config import AppConfig

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动异步子代理事件循环
    init_subagents(dispatcher)
    await dispatcher.start()
    # 启动主动交互事件调度器
    await proactive_scheduler.start()
    yield
    # 优雅关闭调度器
    await proactive_scheduler.stop()
    await dispatcher.stop()


def create_app(config: AppConfig) -> FastAPI:
    Container()
    register_agents()

    app = FastAPI(
        title="MaoWu Agent",
        description="Tech & Career Growth Mentor Agent Runtime with Sub-Agents & AstrBot integration",
        version="0.2.0",
        debug=config.debug,
        lifespan=lifespan,
    )

    cors_config = CORSConfig(
        allow_origins=config.cors_origins,
        allow_credentials=config.cors_allow_credentials,
        allow_methods=config.cors_allow_methods,
        allow_headers=config.cors_allow_headers,
    )
    setup_cors_middleware(app, cors_config)

    app.add_middleware(
        CorrelationIdMiddleware,
        header_name="X-Request-ID",
        update_request_header=True,
        generator=lambda: uuid4().hex,
        validator=is_valid_uuid4,
        transformer=lambda a: a,
    )

    # 挂载核心 API
    app.include_router(runs_router, prefix="/api/v1")
    app.include_router(thread_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")

    # 挂载 AstrBot 与子代理路由（支持标准 OpenAI /v1/chat/completions 及 /api/v1/subagents/tasks）
    app.include_router(astrbot_router)

    # 挂载主动关怀与复盘调度路由
    app.include_router(proactive_router)

    # 挂载 MySQL 简历数据库路由
    app.include_router(db_router)

    # 挂载私人工作区文件下载与管理路由
    app.include_router(workspace_router)

    # 挂载私人待办事项 (TODO) 与备忘录路由
    app.include_router(task_note_router)

    # 挂载网页抓取与变动监控哨兵路由
    app.include_router(web_watch_router)

    # 挂载静态资源与根路径前端交互页面
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def request_audit_middleware(request: Request, call_next):
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        ua = request.headers.get("user-agent", "")[:120]
        method = request.method
        path = request.url.path
        query = str(request.url.query)

        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        _RECENT_REQUESTS.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "method": method,
            "path": path,
            "query": query,
            "status_code": response.status_code,
            "client_ip": client_ip,
            "user_agent": ua,
            "duration_ms": duration_ms,
        })
        return response

    @app.get("/api/v1/debug/recent-requests", tags=["Diagnostics"])
    async def get_recent_requests(limit: int = 50):
        """实时获取最近收到的 HTTP 请求日志，用于快速定位客户端对接异常与 405/404 路由"""
        logs = list(_RECENT_REQUESTS)[-limit:]
        logs.reverse()
        return {"total_buffered": len(_RECENT_REQUESTS), "recent_requests": logs}

    @app.get("/", include_in_schema=False)
    async def serve_index():
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"status": "ok", "message": "MaoWu Agent API is running."}

    # FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/v1/health*,/docs,/metrics,/openapi.json")
    PrometheusInstrumentator(
        excluded_handlers=["/docs", "/metrics", "/api/v1/health*", "/openapi.json"],
    ).instrument(app).expose(app)

    return app
