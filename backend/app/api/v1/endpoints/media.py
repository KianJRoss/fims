import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/{file_path:path}")
def get_media_file(file_path: str):
    media_root = os.getenv("MEDIA_ROOT", "/app/media")
    media_root_abs = os.path.abspath(media_root)
    full_path = os.path.abspath(os.path.normpath(os.path.join(media_root_abs, file_path)))
    if os.path.commonpath([media_root_abs, full_path]) != media_root_abs:
        raise HTTPException(status_code=400, detail="Invalid media path")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(full_path)
