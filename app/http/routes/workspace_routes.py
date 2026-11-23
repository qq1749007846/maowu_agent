from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.code_runner_service import get_code_runner_service

logger = logging.getLogger(__name__)

workspace_router = APIRouter(prefix="/api/v1/workspace", tags=["Workspace"])


@workspace_router.get("/download/{filename:path}")
async def download_workspace_file(filename: str):
    """
    直接下载或访问工作区中的实体文件（如生成的 .xlsx, .csv, .png, .pdf 等）
    """
    service = get_code_runner_service()
    try:
        file_path = service._resolve_safe_path(filename)
    except PermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"工作区中未找到文件 '{filename}'")

    media_type, _ = mimetypes.guess_type(str(file_path))
    if not media_type:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=media_type,
    )


@workspace_router.get("/files")
async def list_workspace_files():
    """获取工作区所有文件列表"""
    service = get_code_runner_service()
    return {"files": service.list_files()}
