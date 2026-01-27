"""
Questions API Endpoints - Default Module
错题相关API（通用模块，支持所有学科）
"""

import logging
from typing import Optional, List, Dict, Any, Union
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.crud import crud_question, crud_image_file
from backend.core.db.models import ImageFile
from backend.core.schemas.question import (
    QuestionResponse,
    QuestionDetail,
    QuestionListResponse,
    QuestionGroup,
    QuestionGroupedListResponse,
    QuestionChaptersResponse,
    SubjectChapterStats,
    ChapterCount,
    QuestionKnowledgePointsResponse,
    SubjectKnowledgePointStats,
    KnowledgePointCount,
)
from backend.modules.default.api.deps import get_current_user_id
from backend.modules.default.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

def _norm_text(s: object) -> str:
    if not isinstance(s, str):
        return ""
    return " ".join(s.strip().split()).lower()


def _infer_is_correct_from_answers(student_answer: object, correct_answer: object) -> Optional[bool]:
    """
    Best-effort inference when DB `is_correct` is missing:
    - only infer when both answers are non-empty strings
    - normalize whitespace + lowercase
    """
    sa = _norm_text(student_answer)
    ca = _norm_text(correct_answer)
    if not sa or not ca:
        return None
    return True if sa == ca else False

@router.get("/review/due", response_model=List[QuestionResponse])
async def get_due_for_review(
    request: Request,
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    subject: Optional[str] = Query(None, description="学科筛选（可选，空表示所有学科）"),
    chapter: Optional[str] = Query(None, description="题目类型/章节筛选（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取需要复习的错题（跨学科）
    - 不传 subject：统计所有学科
    - 传 subject：仅返回该学科
    """
    from datetime import datetime
    from sqlalchemy import select, or_
    from backend.core.db.models import Question, SubjectEnum
    import httpx

    SUBJECT_TO_MODULE = {
        "chinese": "rpj",
        "english": "rpj",
        "politics": "rpj",
        "economics": "xmx",
        "math": "wzy",
        "physics": "wzy",
        "chemistry": "wzm",
        "history": "tony",
        "geography": "tony",
        "other": "tony",
    }
    MODULE_PORTS = {
        "rpj": 6001,
        "xmx": 6002,
        "wzy": 6003,
        "wzm": 6004,
        "tony": 6005,
    }

    if subject == "":
        subject = None
    if chapter == "":
        chapter = None
    if subject and subject not in settings.SUBJECTS:
        raise HTTPException(status_code=400, detail=f"Subject '{subject}' is not supported. Supported subjects: {settings.SUBJECTS}")

    # 选择学科：仍然访问 default，由 default 转发到对应子模块
    if subject:
        module = SUBJECT_TO_MODULE.get(subject)
        port = MODULE_PORTS.get(module) if module else None
        if module and port:
            url = f"http://127.0.0.1:{port}/api/v1/questions/review/due"
            headers = {}
            auth = request.headers.get("authorization")
            if auth:
                headers["authorization"] = auth

            params = {"limit": limit, "subject": subject}
            if chapter:
                params["chapter"] = chapter

            try:
                # Localhost intra-service call; do not route through env proxies.
                async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                    resp = await client.get(url, params=params, headers=headers)
            except Exception as e:
                logger.error(f"[DEFAULT] proxy review due failed: module={module}, subject={subject}, err={e}")
                raise HTTPException(status_code=502, detail=f"Failed to proxy review due to module '{module}'")

            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            try:
                return resp.json()
            except Exception:
                raise HTTPException(status_code=502, detail=f"Invalid response from module '{module}'")

    now = datetime.utcnow()
    q = (
        select(Question)
        .where(Question.user_id == user_id)
        .where((Question.next_review_at <= now) | (Question.next_review_at.is_(None)))
        .where(Question.mastery_level < 0.9)
        .order_by(Question.mastery_level.asc(), Question.next_review_at.asc())
        .limit(limit)
    )
    if subject:
        q = q.where(Question.subject == SubjectEnum(subject))
    if chapter:
        if chapter == "未分类":
            q = q.where(or_(Question.chapter.is_(None), Question.chapter == ""))
        else:
            q = q.where(Question.chapter == chapter)

    result = await db.execute(q)
    questions = list(result.scalars().all())

    items: List[QuestionResponse] = []
    for qobj in questions:
        item = QuestionResponse.model_validate(qobj)
        item.image_urls = await build_question_image_urls_default(db, user_id=user_id, qobj=qobj)
        # expose source_image_id when possible (for frontend linking)
        if getattr(item, "source_image_id", None) is None:
            try:
                paths = list(getattr(qobj, "image_urls", None) or [])
                if paths:
                    img = await crud_image_file.get_image_by_path(db, str(paths[0]))
                    if img and img.user_id == int(user_id):
                        item.source_image_id = int(img.id)
            except Exception:
                pass
        items.append(item)
    return items

def build_question_image_url(question_id: int, image_index: int) -> str:
    """
    将数据库中的图片路径转换为可公网访问的图片URL。
    统一由 default 模块输出图片内容。
    """
    base = (settings.PUBLIC_API_BASE_URL or "http://localhost:6100").rstrip("/")
    return f"{base}/api/v1/questions/images/{question_id}?image_index={image_index}"

def _path_variants(p: str) -> list[str]:
    """
    Normalize legacy path formats.
    We historically stored paths with/without leading "./", so try a few variants
    when mapping Question.image_urls -> ImageFile.file_path.
    """
    s = str(p or "")
    if not s:
        return []
    out = [s]
    # strip leading ./ (one or multiple)
    stripped = s.lstrip("./")
    if stripped and stripped not in out:
        out.append(stripped)
    # add ./ prefix back (common legacy)
    if not s.startswith("./"):
        dot = f"./{s.lstrip('/')}"
        if dot not in out:
            out.append(dot)
    return out

def _looks_like_url(p: str) -> bool:
    s = str(p or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("/api/")

def normalize_question_image_urls(question_id: int, image_urls) -> list[str]:
    if not image_urls:
        return []
    return [build_question_image_url(question_id, idx) for idx in range(len(image_urls))]


def build_image_file_content_url(image_id: int) -> str:
    base = (settings.PUBLIC_API_BASE_URL or "http://localhost:6100").rstrip("/")
    return f"{base}/api/v1/image-files/{image_id}/content"


async def build_question_image_urls_default(
    db: AsyncSession,
    *,
    user_id: int,
    qobj,
) -> list[str]:
    """
    Prefer image_files.id for cross-module list to avoid mismatched images.
    Fallback to /questions/images/{question_id}?image_index=... if mapping is missing.
    """
    paths = list(getattr(qobj, "image_urls", None) or [])
    if not paths:
        return []

    sid = getattr(qobj, "source_image_id", None)
    if sid:
        url = build_image_file_content_url(int(sid))
        return [url for _ in range(len(paths))]

    out: list[str] = []
    for idx, p in enumerate(paths):
        # If stored value is already a URL (legacy), keep it rather than generating a broken file-path endpoint.
        if _looks_like_url(p):
            out.append(str(p))
            continue

        img = None
        for pv in _path_variants(str(p)):
            img = await crud_image_file.get_image_by_path(db, pv)
            if img:
                break
        if img and img.user_id == int(user_id):
            out.append(build_image_file_content_url(int(img.id)))
        else:
            # Legacy fallback: this endpoint reads from question.image_urls and expects filesystem paths.
            out.append(build_question_image_url(int(getattr(qobj, "id", 0) or 0), int(idx)))
    return out

class BatchDeleteQuestionsRequest(BaseModel):
    # 二选一：
    # - 按题目维度删除：question_ids
    # - 按图片维度删除：image_ids（删除与该 source_image_id 关联的所有错题）
    # - 按筛选条件删除：subject/difficulty/search/chapter/knowledge_point（任意组合，至少一个非空）
    question_ids: Optional[List[int]] = None
    image_ids: Optional[List[int]] = None
    subject: Optional[str] = None
    chapter: Optional[str] = None
    knowledge_point: Optional[str] = None
    difficulty: Optional[str] = None
    search: Optional[str] = None

class BatchDeleteQuestionsResponse(BaseModel):
    deleted_count: int
    failed_count: int
    failed_ids: List[int]

@router.get("/chapters", response_model=QuestionChaptersResponse)
async def get_question_chapters(
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    difficulty: Optional[str] = Query(None, description="难度筛选（可选）"),
    search: Optional[str] = Query(None, description="关键词搜索（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题“题目类型/章节（chapter）”统计（带数量）
    用于前端下拉框动态展示。
    """
    from sqlalchemy import select, func
    from sqlalchemy.sql import literal
    from backend.core.db.models import Question, SubjectEnum, DifficultyEnum

    # 规范化空字符串
    if subject == "":
        subject = None
    if difficulty == "":
        difficulty = None
    if search == "":
        search = None

    q_subject = Question.subject
    q_chapter = func.coalesce(Question.chapter, literal("未分类"))
    stmt = (
        select(q_subject, q_chapter, func.count().label("cnt"))
        .where(Question.user_id == user_id)
        .group_by(q_subject, q_chapter)
        .order_by(q_subject, func.count().desc())
    )

    if subject:
        stmt = stmt.where(Question.subject == SubjectEnum(subject))
    if difficulty:
        stmt = stmt.where(Question.difficulty == DifficultyEnum(difficulty))
    if search:
        stmt = stmt.where(Question.content.ilike(f"%{search}%"))

    rows = (await db.execute(stmt)).all()

    by_subject: Dict[str, Dict[str, int]] = {}
    for subj_enum, chapter_name, cnt in rows:
        subj = getattr(subj_enum, "value", str(subj_enum))
        by_subject.setdefault(subj, {})
        by_subject[subj][chapter_name] = int(cnt or 0)

    items: List[SubjectChapterStats] = []
    for subj, chapters_map in by_subject.items():
        chapters = [ChapterCount(chapter=ch, count=c) for ch, c in sorted(chapters_map.items(), key=lambda x: x[1], reverse=True)]
        items.append(
            SubjectChapterStats(
                subject=subj,  # pydantic enum will coerce
                total=sum(ch.count for ch in chapters),
                chapters=chapters,
            )
        )

    return QuestionChaptersResponse(items=items)


@router.get("/knowledge-points", response_model=QuestionKnowledgePointsResponse)
async def get_question_knowledge_points(
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    difficulty: Optional[str] = Query(None, description="难度筛选（可选）"),
    search: Optional[str] = Query(None, description="关键词搜索（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题知识点（knowledge_points）统计（带数量）
    用于前端按学科展示“分类/知识点”下拉框。
    """
    from collections import Counter, defaultdict
    from sqlalchemy import select
    from backend.core.db.models import Question, SubjectEnum, DifficultyEnum

    if subject == "":
        subject = None
    if difficulty == "":
        difficulty = None
    if search == "":
        search = None

    stmt = select(Question.subject, Question.knowledge_points).where(Question.user_id == user_id)
    if subject:
        if subject not in settings.SUBJECTS:
            raise HTTPException(status_code=400, detail=f"Subject '{subject}' is not supported. Supported subjects: {settings.SUBJECTS}")
        stmt = stmt.where(Question.subject == SubjectEnum(subject))
    if difficulty:
        stmt = stmt.where(Question.difficulty == DifficultyEnum(difficulty))
    if search:
        stmt = stmt.where(Question.content.ilike(f"%{search}%"))

    # 保护：最多统计 5000 条（避免全表过大）
    stmt = stmt.limit(5000)
    rows = (await db.execute(stmt)).all()

    by_subject_counter: dict[str, Counter] = defaultdict(Counter)
    by_subject_total: dict[str, int] = defaultdict(int)

    for subj_enum, kps in rows:
        subj = getattr(subj_enum, "value", str(subj_enum))
        kp_list = kps or []
        # 每题至少归类到一个分组
        if not kp_list:
            by_subject_counter[subj]["未分类"] += 1
            by_subject_total[subj] += 1
            continue

        # 去重、去空
        unique = []
        for kp in kp_list:
            if not kp:
                continue
            s = str(kp).strip()
            if not s:
                continue
            if s not in unique:
                unique.append(s)

        if not unique:
            by_subject_counter[subj]["未分类"] += 1
            by_subject_total[subj] += 1
            continue

        for kp in unique:
            by_subject_counter[subj][kp] += 1
        by_subject_total[subj] += 1

    items: List[SubjectKnowledgePointStats] = []
    for subj, counter in by_subject_counter.items():
        kps = [
            KnowledgePointCount(knowledge_point=kp, count=cnt)
            for kp, cnt in counter.most_common()
        ]
        items.append(
            SubjectKnowledgePointStats(
                subject=subj,
                total=by_subject_total.get(subj, 0),
                knowledge_points=kps,
            )
        )

    return QuestionKnowledgePointsResponse(items=items)

@router.get("/", response_model=Union[QuestionListResponse, QuestionGroupedListResponse])
async def list_questions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    subject: Optional[str] = Query(None, description="学科筛选（可选，支持所有学科）"),
    difficulty: Optional[str] = Query(None, description="难度筛选"),
    chapter: Optional[str] = Query(None, description="题目类型/章节筛选（可选）"),
    knowledge_point: Optional[str] = Query(None, description="知识点筛选（可选）"),
    search: Optional[str] = Query(None, description="关键词搜索"),
    start_date: Optional[datetime] = Query(None, description="开始时间(ISO8601)，用于按创建时间筛选"),
    end_date: Optional[datetime] = Query(None, description="结束时间(ISO8601)，用于按创建时间筛选"),
    group_by: str = Query("upload", description="分组方式: upload(按上传图片/文本), chapter(按题目类型), knowledge_point(按知识点), none(不分组)"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题列表（通用模块，支持所有学科）

    支持分页、筛选和搜索。可以通过 subject 参数筛选特定学科的错题。
    如果不提供 subject 参数，则返回所有学科的错题。
    """
    # group_by=none：保持原有“平铺列表”逻辑（按题目分页）
    if group_by == "none":
        skip = (page - 1) * page_size

        # 如果提供了 subject 参数，验证是否在支持的学科列表中
        if subject:
            if subject not in settings.SUBJECTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Subject '{subject}' is not supported. "
                           f"Supported subjects: {settings.SUBJECTS}"
                )

        questions, total = await crud_question.get_questions(
            db,
            user_id=user_id,
            skip=skip,
            limit=page_size,
            subject=subject,
            difficulty=difficulty,
            chapter=chapter,
            search=search,
            start_date=start_date,
            end_date=end_date,
        )

        logger.info(
            f"[DEFAULT] 查询错题列表(平铺): user_id={user_id}, subject={subject}, "
            f"page={page}, page_size={page_size}, total={total}"
        )

        # Bulk resolve file_path -> image_files.id for this page (avoid N+1)
        path_to_image_id: dict[str, int] = {}
        try:
            from sqlalchemy import select

            all_paths: set[str] = set()
            for q in questions:
                if getattr(q, "source_image_id", None):
                    continue
                for p in (getattr(q, "image_urls", None) or []):
                    if p:
                        # Skip URL-like values; they are not file paths stored in image_files.
                        if _looks_like_url(p):
                            continue
                        for pv in _path_variants(str(p)):
                            all_paths.add(pv)
            if all_paths:
                stmt = select(ImageFile).where(ImageFile.user_id == int(user_id), ImageFile.file_path.in_(list(all_paths)))
                imgs = (await db.execute(stmt)).scalars().all()
                path_to_image_id = {}
                for img in imgs:
                    if not img or not img.file_path:
                        continue
                    for pv in _path_variants(str(img.file_path)):
                        path_to_image_id[pv] = int(img.id)
        except Exception:
            path_to_image_id = {}

        items: List[QuestionResponse] = []
        for q in questions:
            item = QuestionResponse.model_validate(q)
            paths = list(getattr(q, "image_urls", None) or [])
            if not paths:
                item.image_urls = []
            else:
                sid = getattr(q, "source_image_id", None)
                if sid:
                    url = build_image_file_content_url(int(sid))
                    item.image_urls = [url for _ in range(len(paths))]
                else:
                    urls: List[str] = []
                    for idx, p in enumerate(paths):
                        if _looks_like_url(p):
                            urls.append(str(p))
                            continue
                        img_id = None
                        for pv in _path_variants(str(p)):
                            img_id = path_to_image_id.get(pv)
                            if img_id:
                                break
                        if img_id:
                            urls.append(build_image_file_content_url(int(img_id)))
                        else:
                            urls.append(build_question_image_url(int(q.id), int(idx)))
                    item.image_urls = urls
                    first_img_id = None
                    if paths and (not _looks_like_url(paths[0])):
                        for pv in _path_variants(str(paths[0])):
                            first_img_id = path_to_image_id.get(pv)
                            if first_img_id:
                                break
                    if first_img_id and getattr(item, "source_image_id", None) is None:
                        item.source_image_id = int(first_img_id)

            # Fill is_correct if missing (based on answers)
            try:
                if getattr(item, "is_correct", None) is None:
                    item.is_correct = _infer_is_correct_from_answers(
                        getattr(item, "student_answer", None),
                        getattr(item, "correct_answer", None),
                    )
            except Exception:
                pass
            items.append(item)

        return QuestionListResponse(total=total, page=page, page_size=page_size, items=items)

    # group_by=upload/chapter/knowledge_point：用于“错题本”展示的分组逻辑（按组分页）
    if group_by not in ("upload", "chapter", "knowledge_point"):
        raise HTTPException(status_code=400, detail="group_by must be one of: upload, chapter, knowledge_point, none")

    # 如果提供了 subject 参数，验证是否在支持的学科列表中
    if subject:
        if subject not in settings.SUBJECTS:
            raise HTTPException(
                status_code=400,
                detail=f"Subject '{subject}' is not supported. "
                       f"Supported subjects: {settings.SUBJECTS}"
            )

    # 为了按组分页，需要先取出足够多的题目再聚合
    # 保护：最多拉取 5000 条用于分组（超出会导致分组不完整，需要后续优化为SQL聚合）
    max_fetch = 5000
    questions, total_questions = await crud_question.get_questions(
        db,
        user_id=user_id,
        skip=0,
        limit=max_fetch,
        subject=subject,
        difficulty=difficulty,
        chapter=chapter,
        search=search,
        start_date=start_date,
        end_date=end_date,
    )
    if total_questions > max_fetch:
        logger.warning(f"[DEFAULT] grouped list truncated: total_questions={total_questions} > max_fetch={max_fetch}")

    # 分组
    groups: Dict[str, Dict[str, Any]] = {}
    # knowledge_point 筛选（按题目包含该知识点）
    if knowledge_point == "":
        knowledge_point = None

    def _kp_contains(q, kp: str) -> bool:
        if kp == "未分类":
            return not (getattr(q, "knowledge_points", None) or [])
        kps = getattr(q, "knowledge_points", None) or []
        return kp in kps

    filtered_questions = questions
    if group_by == "knowledge_point" and knowledge_point:
        filtered_questions = [q for q in questions if _kp_contains(q, knowledge_point)]

    for q in filtered_questions:
        q_subject = getattr(q.subject, "value", q.subject)
        q_chapter = getattr(q, "chapter", None) or "未分类"
        q_kps = getattr(q, "knowledge_points", None) or []
        kp_primary = (q_kps[0] if q_kps else None) or "未分类"
        q_image_urls = getattr(q, "image_urls", None) or []
        upload_type = "image" if q_image_urls else "text"
        # 优先使用 upload_group_id（保证同一次上传分组稳定，且可用于文本录入）
        upload_gid = getattr(q, "upload_group_id", None)
        if upload_gid:
            upload_key = f"upload:{upload_gid}"
        else:
            upload_key = q_image_urls[0] if q_image_urls else f"text:{q.id}"

        if group_by == "upload":
            group_key = f"{q_subject}:{upload_key}"
        elif group_by == "chapter":
            group_key = f"{q_subject}:{q_chapter}"
        else:
            group_key = f"{q_subject}:{(knowledge_point or kp_primary)}"

        if group_key not in groups:
            groups[group_key] = {
                "group_key": group_key,
                "group_by": group_by,
                "subject": q_subject,
                "chapter": q_chapter if group_by == "chapter" else None,
                "knowledge_point": (knowledge_point or kp_primary) if group_by == "knowledge_point" else None,
                "upload_type": upload_type,
                "preview_image_url": None,
                "tags": [],
                "count": 0,
                "questions": [],
                "_q_pairs": [] if group_by == "upload" else None,
                "_sort_ts": getattr(q, "created_at", None),
                "_tags_set": set(),
            }

        item = QuestionResponse.model_validate(q)
        item.image_urls = await build_question_image_urls_default(db, user_id=user_id, qobj=q)
        if getattr(item, "source_image_id", None) is None:
            try:
                if q_image_urls:
                    img = await crud_image_file.get_image_by_path(db, str(q_image_urls[0]))
                    if img and img.user_id == int(user_id):
                        item.source_image_id = int(img.id)
            except Exception:
                pass

        # Fill is_correct if missing (based on answers)
        try:
            if getattr(item, "is_correct", None) is None:
                item.is_correct = _infer_is_correct_from_answers(
                    getattr(item, "student_answer", None),
                    getattr(item, "correct_answer", None),
                )
        except Exception:
            pass

        if group_by == "upload":
            order_idx = getattr(q, "upload_index", None)
            order_val = int(order_idx) if isinstance(order_idx, int) else (10**9)
            # tie-breaker: id 升序，确保稳定
            groups[group_key]["_q_pairs"].append((order_val, int(getattr(q, "id", 0) or 0), item))
        else:
            groups[group_key]["questions"].append(item)
        # 聚合 tags
        try:
            tgs = getattr(q, "tags", None) or []
            if isinstance(tgs, str):
                tgs = [x.strip() for x in tgs.split(",") if x.strip()]
            if isinstance(tgs, list):
                for t in tgs:
                    if t is None:
                        continue
                    s = str(t).strip()
                    if s:
                        groups[group_key]["_tags_set"].add(s)
        except Exception:
            pass
        groups[group_key]["count"] += 1
        if not groups[group_key]["preview_image_url"] and item.image_urls:
            groups[group_key]["preview_image_url"] = item.image_urls[0]
        # 更新排序时间戳
        if getattr(q, "created_at", None) and (groups[group_key]["_sort_ts"] is None or q.created_at > groups[group_key]["_sort_ts"]):
            groups[group_key]["_sort_ts"] = q.created_at

    # 排序 + 分页（按组）
    group_list = sorted(groups.values(), key=lambda x: x.get("_sort_ts") or 0, reverse=True)
    # group_by=upload：组内按 upload_index 升序（与试卷中题目顺序一致）
    if group_by == "upload":
        for g in group_list:
            pairs = g.get("_q_pairs") or []
            g["questions"] = [it for _, __, it in sorted(pairs, key=lambda x: (x[0], x[1]))]
            g["tags"] = sorted(list(g.get("_tags_set") or set()))
            g["created_at"] = g.get("_sort_ts")
    else:
        for g in group_list:
            g["tags"] = sorted(list(g.get("_tags_set") or set()))
            g["created_at"] = g.get("_sort_ts")
    total_groups = len(group_list)
    group_skip = (page - 1) * page_size
    page_groups = group_list[group_skip: group_skip + page_size]

    return QuestionGroupedListResponse(
        total=total_groups,
        total_questions=total_questions,
        total_groups=total_groups,
        page=page,
        page_size=page_size,
        group_by=group_by,
        items=[
            QuestionGroup(
                group_key=g["group_key"],
                group_by=g["group_by"],
                subject=g["subject"],
                chapter=g["chapter"],
                knowledge_point=g.get("knowledge_point"),
                upload_type=g["upload_type"],
                preview_image_url=g["preview_image_url"],
                created_at=g.get("created_at"),
                tags=g.get("tags") or [],
                count=g["count"],
                questions=g["questions"],
            )
            for g in page_groups
        ],
    )

@router.get("/{question_id}", response_model=QuestionDetail)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题详情（通用模块，支持所有学科）
    """
    question = await crud_question.get_question(db, question_id, user_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    logger.info(f"[DEFAULT] 获取错题详情: question_id={question_id}, user_id={user_id}")

    resp = QuestionDetail.model_validate(question)
    resp.image_urls = await build_question_image_urls_default(db, user_id=user_id, qobj=question)
    if getattr(resp, "source_image_id", None) is None:
        try:
            paths = list(getattr(question, "image_urls", None) or [])
            if paths:
                img = await crud_image_file.get_image_by_path(db, str(paths[0]))
                if img and img.user_id == int(user_id):
                    resp.source_image_id = int(img.id)
        except Exception:
            pass
    return resp

@router.post("/batch-delete", response_model=BatchDeleteQuestionsResponse)
async def batch_delete_questions(
    request: BatchDeleteQuestionsRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    批量删除错题（跨学科）
    统一由 default 模块处理，无需路由到各个学科模块。
    """
    from sqlalchemy import delete
    from backend.core.db.models import AgentTask, Feedback

    deleted_count = 0
    failed_count = 0
    failed_ids: List[int] = []
    affected_image_ids: List[int] = []
    orphan_image_paths_to_delete: List[str] = []

    # 规范化空字符串
    if request.subject == "":
        request.subject = None
    if request.chapter == "":
        request.chapter = None
    if request.knowledge_point == "":
        request.knowledge_point = None
    if request.difficulty == "":
        request.difficulty = None
    if request.search == "":
        request.search = None

    # ===== 1) 按题目维度删除 =====
    if request.question_ids and request.image_ids:
        raise HTTPException(status_code=400, detail="question_ids 和 image_ids 不能同时提供")

    if request.question_ids:
        for qid in request.question_ids:
            try:
                question = await crud_question.get_question(db, qid, user_id=user_id)
                if not question:
                    failed_count += 1
                    failed_ids.append(qid)
                    continue

                # 删除关联的任务与反馈（避免外键约束）
                await db.execute(delete(AgentTask).where(AgentTask.question_id == qid))
                await db.execute(delete(Feedback).where(Feedback.question_id == qid))

                # 图片引用计数 - 尽力处理（失败不阻塞删除）
                try:
                    for path in (question.image_urls or []):
                        await crud_image_file.decrement_reference_count_by_path(db, path)
                except Exception as e:
                    logger.warning(f"[DEFAULT] decrement image refcount failed for question {qid}: {e}")

                if getattr(question, "source_image_id", None):
                    affected_image_ids.append(int(question.source_image_id))

                ok = await crud_question.delete_question(db, question_id=qid, user_id=user_id)
                if ok:
                    deleted_count += 1
                else:
                    failed_count += 1
                    failed_ids.append(qid)
            except Exception as e:
                failed_count += 1
                failed_ids.append(qid)
                logger.error(f"[DEFAULT] batch_delete_questions failed for {qid}: {e}")

    # ===== 2) 按图片维度删除（source_image_id）=====
    elif request.image_ids:
        from sqlalchemy import select, and_
        from backend.core.db.models import Question, AgentTask, Feedback
        from sqlalchemy import delete

        # 规范化 image_ids
        uniq: list[int] = []
        seen = set()
        for x in (request.image_ids or []):
            try:
                ix = int(x)
            except Exception:
                continue
            if ix <= 0 or ix in seen:
                continue
            seen.add(ix)
            uniq.append(ix)

        if not uniq:
            return BatchDeleteQuestionsResponse(deleted_count=0, failed_count=0, failed_ids=[])

        qs = list(
            (await db.execute(
                select(Question)
                .where(and_(Question.user_id == int(user_id), Question.source_image_id.in_(uniq)))
            )).scalars().all()
        )
        qids = [int(q.id) for q in qs]
        if not qids:
            return BatchDeleteQuestionsResponse(deleted_count=0, failed_count=0, failed_ids=[])

        # 图片引用计数 - 尽力处理（失败不阻塞删除）
        for q in qs:
            try:
                for path in (q.image_urls or []):
                    await crud_image_file.decrement_reference_count_by_path(db, path)
            except Exception as e:
                logger.warning(f"[DEFAULT] decrement image refcount failed for question {q.id}: {e}")
            if getattr(q, "source_image_id", None):
                affected_image_ids.append(int(q.source_image_id))

        # 批量删除任务/反馈/题目（分批，避免 sqlite 变量上限）
        def chunks(arr: List[int], size: int = 300):
            for i in range(0, len(arr), size):
                yield arr[i:i + size]

        for part in chunks(qids):
            await db.execute(delete(AgentTask).where(AgentTask.question_id.in_(part)))
            await db.execute(delete(Feedback).where(Feedback.question_id.in_(part)))
            await db.execute(delete(Question).where(and_(Question.user_id == int(user_id), Question.id.in_(part))))

        deleted_count = len(qids)

    # ===== 2) 按筛选条件删除（subject/difficulty/search/chapter/knowledge_point）=====
    else:
        from sqlalchemy import select, and_, or_
        from backend.core.db.models import Question, SubjectEnum, DifficultyEnum

        # 至少提供一个筛选条件，避免误删全部
        if not any([request.subject, request.difficulty, request.search, request.chapter, request.knowledge_point]):
            raise HTTPException(status_code=400, detail="请至少提供一个筛选条件（subject/difficulty/search/chapter/knowledge_point）或 question_ids")

        stmt = select(Question).where(Question.user_id == user_id)

        if request.subject:
            if request.subject not in settings.SUBJECTS:
                raise HTTPException(status_code=400, detail=f"Subject '{request.subject}' is not supported. Supported subjects: {settings.SUBJECTS}")
            stmt = stmt.where(Question.subject == SubjectEnum(request.subject))

        if request.difficulty:
            stmt = stmt.where(Question.difficulty == DifficultyEnum(request.difficulty))

        if request.search:
            stmt = stmt.where(Question.content.ilike(f"%{request.search}%"))

        if request.chapter:
            if request.chapter == "未分类":
                stmt = stmt.where(or_(Question.chapter.is_(None), Question.chapter == ""))
            else:
                stmt = stmt.where(Question.chapter == request.chapter)

        # 对 knowledge_point 的筛选：SQLite JSON membership 难以通用SQL处理，这里用 Python 过滤
        qs = list((await db.execute(stmt)).scalars().all())

        if request.knowledge_point:
            if request.knowledge_point == "未分类":
                qs = [q for q in qs if not (getattr(q, "knowledge_points", None) or [])]
            else:
                qs = [q for q in qs if request.knowledge_point in (getattr(q, "knowledge_points", None) or [])]

        qids = [q.id for q in qs]
        if not qids:
            return BatchDeleteQuestionsResponse(deleted_count=0, failed_count=0, failed_ids=[])

        # 图片引用计数 - 尽力处理（失败不阻塞删除）
        for q in qs:
            try:
                for path in (q.image_urls or []):
                    await crud_image_file.decrement_reference_count_by_path(db, path)
            except Exception as e:
                logger.warning(f"[DEFAULT] decrement image refcount failed for question {q.id}: {e}")
            if getattr(q, "source_image_id", None):
                affected_image_ids.append(int(q.source_image_id))

        # 批量删除任务/反馈/题目（分批，避免 sqlite 变量上限）
        def chunks(arr: List[int], size: int = 300):
            for i in range(0, len(arr), size):
                yield arr[i:i + size]

        for part in chunks(qids):
            await db.execute(delete(AgentTask).where(AgentTask.question_id.in_(part)))
            await db.execute(delete(Feedback).where(Feedback.question_id.in_(part)))
            await db.execute(delete(Question).where(and_(Question.user_id == user_id, Question.id.in_(part))))

        deleted_count = len(qids)

    # If deleting makes some uploaded images orphaned, delete corresponding image_files rows.
    try:
        orphan_image_paths_to_delete = await crud_image_file.mark_delete_orphan_question_images(
            db,
            user_id=int(user_id),
            image_ids=affected_image_ids,
        )
    except Exception as e:
        logger.warning(f"[DEFAULT] mark_delete_orphan_question_images skipped/failed: {e}")

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"[DEFAULT] batch_delete_questions commit failed: {e}")
        raise HTTPException(status_code=500, detail="批量删除失败")

    # After successful commit, delete physical files (best-effort).
    try:
        if orphan_image_paths_to_delete:
            stats = crud_image_file.delete_files_best_effort(orphan_image_paths_to_delete)
            logger.info(f"[DEFAULT] deleted orphan question image files: {stats}")
    except Exception as e:
        logger.warning(f"[DEFAULT] delete orphan question image files failed: {e}")

    return BatchDeleteQuestionsResponse(
        deleted_count=deleted_count,
        failed_count=failed_count,
        failed_ids=failed_ids,
    )

@router.get("/images/{question_id}")
async def get_question_image(
    question_id: int,
    image_index: int = Query(0, ge=0, description="图片索引（从0开始）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题录入的图片（通用模块，支持所有学科）

    用于展示录入错题功能上传的图片。
    统一由 default 模块处理，无需路由到各个学科模块。
    """
    import os
    from fastapi.responses import FileResponse
    from fastapi.responses import RedirectResponse
    from backend.core.crud import crud_question

    # 获取错题记录
    question = await crud_question.get_question(db, question_id, user_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # 获取图片URL列表
    image_urls = question.image_urls or []
    if not image_urls or image_index >= len(image_urls):
        raise HTTPException(status_code=404, detail="Image not found")

    image_path = image_urls[image_index]

    # If legacy data stored a URL instead of a filesystem path, redirect to it.
    try:
        s = str(image_path or "").strip()
        if s.startswith("/api/"):
            base = (settings.PUBLIC_API_BASE_URL or "http://localhost:6100").rstrip("/")
            return RedirectResponse(url=f"{base}{s}", status_code=307)
        if s.lower().startswith("http://") or s.lower().startswith("https://"):
            return RedirectResponse(url=s, status_code=307)
    except Exception:
        pass

    # 处理路径（支持相对路径和绝对路径）
    if not os.path.isabs(image_path):
        # 如果是相对路径，尝试多种可能的路径
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_file_dir, "../../../../.."))
        
        # 移除开头的 ./ 或 /
        normalized = image_path.lstrip("./").lstrip("/")
        
        # 尝试多个可能的路径
        possible_paths = [
            os.path.join(project_root, normalized),
            os.path.join(os.getcwd(), normalized),
            os.path.join("./data/uploads", normalized),
        ]
        
        found_path = None
        for path in possible_paths:
            if os.path.exists(path):
                found_path = path
                break
        
        if not found_path:
            raise HTTPException(status_code=404, detail=f"Image file not found: {image_path}")
        
        image_path = found_path

    # 检查文件是否存在
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Image file not found")

    # 根据文件扩展名确定 MIME 类型
    ext = os.path.splitext(image_path)[1].lower().lstrip('.')
    mime_types = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'webp': 'image/webp',
        'heic': 'image/heic',
    }
    media_type = mime_types.get(ext, 'image/jpeg')

    # 返回图片文件
    return FileResponse(
        image_path,
        media_type=media_type,
        filename=os.path.basename(image_path)
    )
