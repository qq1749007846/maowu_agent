from __future__ import annotations

import logging
import mimetypes
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.services.code_runner_service import get_code_runner_service

logger = logging.getLogger(__name__)

workspace_router = APIRouter(prefix="/api/v1/workspace", tags=["Workspace"])


@workspace_router.get("/download/{filename:path}")
async def download_workspace_file(filename: str):
    """
    直接下载或访问工作区中的实体文件（如生成的 .xlsx, .csv, .png, .pdf 等）
    自动支持 URL 解码、同名模糊查找与 RFC 6266 国际化文件名防乱码下载
    """
    service = get_code_runner_service()
    decoded_name = urllib.parse.unquote(filename).strip()

    try:
        file_path = service._resolve_safe_path(decoded_name)
    except PermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err

    # 若精确路径不存在，进行智能别名/模糊匹配查找（避免前后缀微调导致 404）
    if not file_path.exists() or not file_path.is_file():
        stem = Path(decoded_name).stem.strip()
        candidates = [
            f for f in service.workspace_dir.iterdir()
            if f.is_file() and (stem in f.name or f.stem in stem)
        ]
        if candidates:
            file_path = candidates[0]
        else:
            raise HTTPException(status_code=404, detail=f"工作区中未找到文件 '{decoded_name}'")

    media_type, _ = mimetypes.guess_type(str(file_path))
    if not media_type:
        if file_path.suffix.lower() == ".xlsx":
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif file_path.suffix.lower() == ".csv":
            media_type = "text/csv; charset=utf-8"
        else:
            media_type = "application/octet-stream"

    # 规范 RFC 6266 + ASCII fallback 头，彻底解决 Edge/Chrome 提示“无法从网站上提取文件”问题
    quoted_name = urllib.parse.quote(file_path.name)
    suffix = file_path.suffix or ".bin"
    ascii_fallback = f"export{suffix}"
    headers = {
        "Content-Disposition": f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quoted_name}',
        "Access-Control-Expose-Headers": "Content-Disposition",
    }

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers=headers,
    )


@workspace_router.post("/upload/{filename:path}")
async def upload_workspace_file(filename: str, request: Request):
    """支持将文件二进制流安全同步上传至工作区沙箱"""
    service = get_code_runner_service()
    save_path = service._resolve_safe_path(filename)
    content = await request.body()
    save_path.write_bytes(content)
    return {"success": True, "filename": filename, "size_bytes": len(content)}


@workspace_router.get("/files")
async def list_workspace_files():
    """获取工作区所有文件列表"""
    service = get_code_runner_service()
    return {"files": service.list_files()}
