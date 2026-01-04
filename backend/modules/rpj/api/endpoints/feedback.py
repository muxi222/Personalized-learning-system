"""
用户反馈API (RPJ模块 - 精简版)
用户反馈收集API - 仅支持语文、英语、道法
"""

import logging
import json
import os
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.modules.rpj.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

# RPJ模块支持的学科（与系统 SubjectEnum 保持一致）
RPJ_SUBJECTS = ["chinese", "english", "politics"]

def validate_rpj_subject(subject: str) -> None:
    """验证学科是否属于RPJ模块支持的学科"""
    if subject.lower() not in RPJ_SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"学科 '{subject}' 不支持RPJ模块。支持的学科: {RPJ_SUBJECTS}"
        )

def get_user_feedback_dir(user_id: int) -> str:
    """获取用户反馈目录"""
    feedback_dir = f"data/rpj/feedback/user_{user_id}"
    os.makedirs(feedback_dir, exist_ok=True)
    return feedback_dir

def save_feedback_data(user_id: int, feedback_id: int, data: dict) -> str:
    """保存反馈数据"""
    feedback_dir = get_user_feedback_dir(user_id)
    data_file = os.path.join(feedback_dir, f"feedback_{feedback_id}.json")

    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data_file

# ============ Request/Response Models ============

class FeedbackCreate(BaseModel):
    """创建反馈请求"""
    feedback_type: str = Field(..., description="反馈类型: helpful(有帮助), not_helpful(没帮助), suggestion(建议)")
    rating: int = Field(..., ge=1, le=5, description="评分: 1-5星")
    comment: Optional[str] = Field(None, description="评论")
    subject: str = Field(..., description="学科: chinese, english, politics")

class FeedbackResponse(BaseModel):
    """反馈响应"""
    id: int
    user_id: int
    feedback_type: str
    rating: int
    comment: Optional[str]
    subject: str
    created_at: str

class FeedbackStats(BaseModel):
    """反馈统计"""
    total_feedbacks: int
    helpful_count: int
    not_helpful_count: int
    suggestion_count: int
    average_rating: float

# ============ Core API Endpoints ============

@router.post("/", response_model=FeedbackResponse)
async def create_feedback(
    feedback_data: FeedbackCreate,
    user_id: int = Depends(get_current_user_id),
):
    """
    提交反馈

    收集用户对AI分析结果的评价：
    - 反馈类型: helpful(有帮助), not_helpful(没帮助), suggestion(建议)
    - 评分: 1-5星
    - 评论: 可选文字说明
    - 学科: chinese, english, politics
    """
    try:
        # 验证学科
        validate_rpj_subject(feedback_data.subject)

        # 生成反馈ID
        import time
        feedback_id = int(time.time() * 1000) % 10000

        # 创建反馈数据
        feedback = {
            "id": feedback_id,
            "user_id": user_id,
            "feedback_type": feedback_data.feedback_type,
            "rating": feedback_data.rating,
            "comment": feedback_data.comment,
            "subject": feedback_data.subject.lower(),
            "created_at": datetime.now().isoformat(),
        }

        # 保存反馈
        save_feedback_data(user_id, feedback_id, feedback)

        logger.info(f"用户 {user_id} 提交了 {feedback_data.subject} 反馈，ID: {feedback_id}")

        return FeedbackResponse(**feedback)

    except Exception as e:
        logger.error(f"创建反馈失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建反馈失败: {str(e)}")

## 统计接口已移动到：backend/modules/rpj/api/endpoints/stats/feedback.py（学生实现）

@router.get("/recent")
async def get_recent_feedbacks(
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    subject: Optional[str] = Query(None, description="学科筛选: chinese, english, politics"),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取最近反馈

    返回用户最近的反馈记录，用于查看反馈历史。
    """
    try:
        # 验证学科
        if subject:
            validate_rpj_subject(subject)

        # 获取用户反馈目录
        feedback_dir = get_user_feedback_dir(user_id)
        if not os.path.exists(feedback_dir):
            return {"feedbacks": []}

        # 收集所有反馈
        all_feedbacks = []
        for filename in os.listdir(feedback_dir):
            if filename.endswith(".json") and filename.startswith("feedback_"):
                filepath = os.path.join(feedback_dir, filename)

                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        feedback_data = json.load(f)

                    # 学科筛选
                    if subject and feedback_data.get("subject") != subject.lower():
                        continue

                    all_feedbacks.append(feedback_data)

                except Exception as e:
                    logger.warning(f"加载反馈文件失败 {filepath}: {e}")

        # 按创建时间倒序排序
        all_feedbacks.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # 限制数量
        recent_feedbacks = all_feedbacks[:limit]

        return {
            "total": len(all_feedbacks),
            "count": len(recent_feedbacks),
            "feedbacks": recent_feedbacks
        }

    except Exception as e:
        logger.error(f"获取最近反馈失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取最近反馈失败: {str(e)}")
