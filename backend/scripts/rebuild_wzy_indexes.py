"""
WZY模块向量索引重建脚本 (学生实现版本)
学科: math, physics
功能: 从数据库读取WZY模块相关题目，重建FAISS和BM25索引

TODO: 本脚本为框架代码，需要学生完成以下部分的实现
      可参考 rebuild_tony_indexes.py (完整实现) 或 rebuild_rpj_indexes.py (框架模板)
"""

import asyncio
import logging
from pathlib import Path
from typing import List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import select
from backend.core.db.session import async_session_maker
from backend.core.db.models import Question, SubjectEnum
from backend.core.services.embedding_service import get_embedding_service
from backend.core.services.vector_store_service import get_vector_store_service
from backend.modules.wzy.config import settings

WZY_SUBJECTS = ["math", "physics"]


async def fetch_wzy_questions():
    """
    TODO: 从数据库获取WZY模块的math和physics学科题目
    提示: Question.subject.in_([SubjectEnum.MATH, SubjectEnum.PHYSICS])
    """
    logger.info(f"正在从数据库获取WZY模块题目 (学科: {WZY_SUBJECTS})...")
    raise NotImplementedError("TODO: 学生需要实现fetch_wzy_questions函数")


async def rebuild_faiss_index(questions: List[Question]):
    """TODO: 重建WZY模块的FAISS向量索引"""
    logger.info("开始重建WZY模块FAISS索引...")
    raise NotImplementedError("TODO: 学生需要实现rebuild_faiss_index函数")


async def rebuild_bm25_index(questions: List[Question]):
    """TODO: 重建WZY模块的BM25关键词索引"""
    logger.info("开始重建WZY模块BM25索引...")
    raise NotImplementedError("TODO: 学生需要实现rebuild_bm25_index函数")


async def main():
    logger.info("=" * 60)
    logger.info("WZY模块向量索引重建工具 (数学、物理)")
    logger.info(f"模块: {settings.MODULE_NAME}")
    logger.info(f"支持学科: {', '.join(WZY_SUBJECTS)}")
    logger.warning("⚠️  本脚本为框架代码，需要学生完成实现")
    logger.info("=" * 60)

    try:
        questions = await fetch_wzy_questions()
        if not questions:
            logger.warning("数据库中没有WZY模块的题目")
            return
        await rebuild_faiss_index(questions)
        await rebuild_bm25_index(questions)
        logger.info("🎉 WZY模块所有索引重建完成！")
    except NotImplementedError as e:
        logger.error(f"❌ {e}")
        logger.info("💡 请参考 backend/scripts/rebuild_tony_indexes.py 完成实现")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 错误: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
