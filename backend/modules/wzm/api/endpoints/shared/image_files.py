"""WZM - Image Files API（学生实现版 / Stub）

仅保留主要入口 endpoints 的定义，删除具体实现。
参考：`backend/modules/tony/api/endpoints/shared/image_files.py`
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Path, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.modules.wzm.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/")
async def list_image_files(page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 图片文件入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: list_image_files")

@router.get("/{image_id}")
async def get_image_file(image_id: int = Path(...), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 图片文件入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_image_file")

@router.delete("/{image_id}", status_code=204)
async def delete_image_file(image_id: int = Path(...), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 图片文件入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: delete_image_file")

