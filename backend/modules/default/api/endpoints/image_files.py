"""
Default Module - Image Files Endpoints

Serve uploaded images by image_files.id across modules.
This fixes mismatched images in the cross-subject question list.
"""

import os
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse
from jose import jwt, JWTError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, asc

from backend.modules.default.api.deps import get_db, get_optional_user_id, get_current_user_id
from backend.modules.default.config import settings
from backend.core.crud import crud_image_file
from backend.core.db.models import Question

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/image-files/{image_id}/content")
async def get_image_file_content(
    image_id: int = Path(..., description="ImageFile.id"),
    token: Optional[str] = Query(None, description="JWT token (for <img> tag access)"),
    current_user_id: Optional[int] = Depends(get_optional_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Get image binary content by ImageFile.id.
    Supports token in query param because <img> cannot attach Authorization headers easily.
    """
    # Parse token from query if needed
    if token and current_user_id is None:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id_str: str = payload.get("sub")
            if user_id_str:
                current_user_id = int(user_id_str)
        except JWTError as e:
            logger.warning(f"Failed to parse token from query param: {e}")
        except Exception as e:
            logger.warning(f"Failed to parse token from query param: {e}")

    image = await crud_image_file.get_image_file(db, image_id, current_user_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # If no auth info, restrict in production
    if current_user_id is None and not settings.is_development:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})

    file_path = image.file_path
    original_stored_path = file_path

    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_file_dir, "../../../../../"))

    possible_paths = []
    if os.path.isabs(file_path):
        possible_paths.append(file_path)
    else:
        normalized = file_path.lstrip("./").lstrip("/")
        possible_paths.extend(
            [
                os.path.join(project_root, normalized),
                os.path.join(os.getcwd(), normalized),
                os.path.join("./data/uploads", normalized),
            ]
        )

    found_path = None
    for p in possible_paths:
        if os.path.exists(p):
            found_path = p
            break

    if not found_path:
        raise HTTPException(status_code=404, detail=f"Image file not found: {original_stored_path}")

    media_type = image.mime_type
    if not media_type:
        ext = os.path.splitext(found_path)[1].lower().lstrip(".")
        mime_types = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "heic": "image/heic",
        }
        media_type = mime_types.get(ext, "image/jpeg")

    return FileResponse(found_path, media_type=media_type, filename=os.path.basename(found_path))


class ImageQuestionGroupStats(BaseModel):
    total: int
    correct: int
    # Backward/forward compatibility:
    # - frontend may read `wrong`/`unknown`
    # - backend may use `incorrect`
    incorrect: int
    wrong: int
    unknown: int


class ImageQuestionGroupQuestionItem(BaseModel):
    id: int
    title: Optional[str] = None
    content: Optional[str] = None
    subject: Optional[str] = None
    difficulty: Optional[str] = None
    source_image_id: Optional[int] = None
    upload_index: Optional[int] = None
    is_correct: Optional[bool] = None
    score: Optional[float] = None
    max_score: Optional[float] = None
    image_urls: List[str] = []


class ImageQuestionGroupResponse(BaseModel):
    image_id: int
    image_url: str
    stats: ImageQuestionGroupStats
    questions: List[ImageQuestionGroupQuestionItem]


class DeleteImageQuestionGroupResponse(BaseModel):
    image_id: int
    deleted_questions: int
    deleted_image: bool


def _build_image_file_content_url(image_id: int) -> str:
    base = (getattr(settings, "PUBLIC_API_BASE_URL", "") or "").rstrip("/")
    if base:
        return f"{base}/api/v1/image-files/{image_id}/content"
    return f"/api/v1/image-files/{image_id}/content"

def _coerce_bool(v: object) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        # SQLite may store booleans as 0/1
        return bool(int(v))
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "t", "yes", "y", "1", "correct", "right"):
            return True
        if s in ("false", "f", "no", "n", "0", "wrong", "incorrect"):
            return False
    return None

def _norm_text(s: object) -> str:
    if not isinstance(s, str):
        return ""
    # normalize whitespace for rough comparison
    return " ".join(s.strip().split()).lower()


def _infer_is_correct_from_answers(student_answer: object, correct_answer: object) -> Optional[bool]:
    sa = _norm_text(student_answer)
    ca = _norm_text(correct_answer)
    if not sa or not ca:
        return None
    return True if sa == ca else False


@router.get("/image-files/{image_id}/questions", response_model=ImageQuestionGroupResponse)
async def get_image_file_questions(
    image_id: int = Path(..., description="ImageFile.id"),
    current_user_id: Optional[int] = Depends(get_optional_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    List all questions that were extracted from a single uploaded image (ImageFile.id),
    with correctness statistics. This endpoint is in default module for cross-module access.
    """
    if current_user_id is None and not settings.is_development:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})

    image = await crud_image_file.get_image_file(db, image_id, current_user_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    stmt = (
        select(Question)
        .where(Question.user_id == current_user_id)
        .where(Question.source_image_id == image_id)
        .order_by(
            asc(Question.upload_index).nulls_last(),
            asc(Question.id),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()

    correct = 0
    incorrect = 0
    items: List[ImageQuestionGroupQuestionItem] = []
    for q in rows:
        is_correct = _coerce_bool(getattr(q, "is_correct", None))
        # Fallback: infer from score/max_score when is_correct missing
        if is_correct is None:
            try:
                score = float(q.score) if q.score is not None else None
                max_score = float(q.max_score) if q.max_score is not None else None
            except Exception:
                score, max_score = None, None
            if isinstance(score, (int, float)) and isinstance(max_score, (int, float)) and max_score > 0:
                # Treat full score as correct, otherwise incorrect
                is_correct = True if score >= max_score else False
        # Fallback: infer from student_answer vs correct_answer (rough)
        if is_correct is None:
            is_correct = _infer_is_correct_from_answers(
                getattr(q, "student_answer", None),
                getattr(q, "correct_answer", None),
            )

        if is_correct is True:
            correct += 1
        elif is_correct is False:
            incorrect += 1

        # Prefer image_files id content endpoint when we know source_image_id
        image_urls: List[str] = []
        if q.source_image_id:
            image_urls = [_build_image_file_content_url(int(q.source_image_id))]

        items.append(
            ImageQuestionGroupQuestionItem(
                id=q.id,
                title=q.title,
                content=q.content,
                subject=(q.subject.value if getattr(q.subject, "value", None) else q.subject),
                difficulty=(q.difficulty.value if getattr(q.difficulty, "value", None) else q.difficulty),
                source_image_id=q.source_image_id,
                upload_index=q.upload_index,
                is_correct=is_correct,
                score=q.score,
                max_score=q.max_score,
                image_urls=image_urls,
            )
        )

    total = len(items)
    unknown = max(0, total - correct - incorrect)
    return ImageQuestionGroupResponse(
        image_id=image_id,
        image_url=_build_image_file_content_url(image_id),
        stats=ImageQuestionGroupStats(
            total=total,
            correct=correct,
            incorrect=incorrect,
            wrong=incorrect,
            unknown=unknown,
        ),
        questions=items,
    )


@router.delete("/image-files/{image_id}", response_model=DeleteImageQuestionGroupResponse)
async def delete_image_question_group(
    image_id: int = Path(..., description="ImageFile.id（错题本图片维度）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Delete a wrongbook "image group": remove all Questions whose source_image_id == image_id,
    then delete the corresponding image_files row (file_type='questions') if it becomes orphaned.

    Note: This endpoint lives in default module to support cross-subject wrongbook UI.
    """
    from sqlalchemy import delete
    from backend.core.db.models import AgentTask, Feedback, Question as QuestionModel

    # Ensure image exists and belongs to user (avoid leaking existence across users)
    img = await crud_image_file.get_image_file(db, image_id, user_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")

    # Collect question ids for this image group
    qids = [
        int(x)
        for x in (
            await db.execute(
                select(QuestionModel.id)
                .where(QuestionModel.user_id == int(user_id))
                .where(QuestionModel.source_image_id == int(image_id))
            )
        ).scalars().all()
        if x is not None
    ]

    # Delete tasks/feedback/questions in chunks (SQLite param limit safety)
    def chunks(arr: List[int], size: int = 300):
        for i in range(0, len(arr), size):
            yield arr[i : i + size]

    for part in chunks(qids):
        await db.execute(delete(AgentTask).where(AgentTask.question_id.in_(part)))
        await db.execute(delete(Feedback).where(Feedback.question_id.in_(part)))
        await db.execute(
            delete(QuestionModel).where(
                QuestionModel.user_id == int(user_id),
                QuestionModel.id.in_(part),
            )
        )

    deleted_questions = len(qids)

    # Mark image_files row for deletion if it becomes orphaned after question deletion.
    orphan_paths: List[str] = []
    try:
        orphan_paths = await crud_image_file.mark_delete_orphan_question_images(
            db,
            user_id=int(user_id),
            image_ids=[int(image_id)],
        )
    except Exception as e:
        logger.warning(f"[DEFAULT] mark_delete_orphan_question_images skipped/failed: {e}")

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"[DEFAULT] delete_image_question_group commit failed: {e}")
        raise HTTPException(status_code=500, detail="删除失败")

    # After successful commit, delete physical files (best-effort).
    deleted_image = False
    try:
        if orphan_paths:
            stats = crud_image_file.delete_files_best_effort(orphan_paths)
            deleted_image = bool(stats.get("deleted", 0) > 0)
            logger.info(f"[DEFAULT] deleted orphan question image files: {stats}")
    except Exception as e:
        logger.warning(f"[DEFAULT] delete orphan question image files failed: {e}")

    return DeleteImageQuestionGroupResponse(
        image_id=int(image_id),
        deleted_questions=int(deleted_questions),
        deleted_image=bool(deleted_image or bool(orphan_paths)),
    )

