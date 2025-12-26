"""
RPJ模块向量索引重建脚本 (学生实现版本)
学科: chinese, english, politics
功能: 从数据库读取RPJ模块相关题目，重建FAISS和BM25索引

TODO: 本脚本为框架代码，需要学生完成以下部分的实现
"""

import asyncio
import logging
from pathlib import Path
from typing import List

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 添加项目根目录到路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import select
from backend.core.db.session import async_session_maker
from backend.core.db.models import Question, SubjectEnum
from backend.core.services.embedding_service import get_embedding_service
from backend.core.services.vector_store_service import get_vector_store_service
from backend.modules.rpj.config import settings


# RPJ模块支持的学科
RPJ_SUBJECTS = ["chinese", "english", "politics"]


async def fetch_rpj_questions():
    """
    从数据库获取RPJ模块的所有题目

    TODO: 实现此函数
    需要做的事情:
    1. 使用async_session_maker创建数据库会话
    2. 构建SQL查询，筛选RPJ模块的学科 (chinese, english, politics)
       提示: Question.subject.in_([SubjectEnum.CHINESE, SubjectEnum.ENGLISH, SubjectEnum.POLITICS])
    3. 执行查询并返回结果列表
    4. 记录日志：获取了多少道题目

    参考: backend/scripts/rebuild_tony_indexes.py 中的 fetch_tony_questions()

    Returns:
        List[Question]: RPJ模块题目列表
    """
    logger.info(f"正在从数据库获取RPJ模块题目 (学科: {RPJ_SUBJECTS})...")

    # TODO: 在这里实现数据库查询逻辑
    # async with async_session_maker() as session:
    #     stmt = select(Question).where(...)
    #     result = await session.execute(stmt)
    #     questions = result.scalars().all()
    #     return list(questions)

    raise NotImplementedError("TODO: 学生需要实现fetch_rpj_questions函数")


async def rebuild_faiss_index(questions: List[Question]):
    """
    重建RPJ模块的FAISS向量索引

    TODO: 实现此函数
    需要做的事情:
    1. 获取embedding_service和vector_store_service实例
    2. 使用settings.module_vector_path作为索引路径
    3. 初始化向量存储，force_recreate=True清空现有索引
    4. 遍历每道题目：
       a. 构建索引文本 (content + knowledge_points + tags)
       b. 调用embedding_service.embed_text()生成embedding
       c. 构建metadata字典
       d. 调用vector_store.add_documents()添加到索引
    5. 记录日志：处理进度和最终结果

    参考: backend/scripts/rebuild_tony_indexes.py 中的 rebuild_faiss_index()

    Args:
        questions: 题目列表
    """
    logger.info("开始重建RPJ模块FAISS索引...")

    # TODO: 在这里实现FAISS索引重建逻辑
    # embedding_service = get_embedding_service()
    # vector_store = get_vector_store_service()
    # index_path = settings.module_vector_path
    # await vector_store.initialize(index_path=index_path, force_recreate=True)
    # ...

    raise NotImplementedError("TODO: 学生需要实现rebuild_faiss_index函数")


async def rebuild_bm25_index(questions: List[Question]):
    """
    重建RPJ模块的BM25关键词索引

    TODO: 实现此函数
    需要做的事情:
    1. 导入BM25Service
    2. 设置BM25索引路径: f"./data/bm25/{settings.MODULE_NAME}"
    3. 创建目录(如果不存在)
    4. 初始化BM25Service
    5. 准备文档列表、metadata列表、doc_ids列表
    6. 调用bm25_service.build_index()重建索引
    7. 记录日志：索引了多少道题目

    参考: backend/scripts/rebuild_tony_indexes.py 中的 rebuild_bm25_index()

    Args:
        questions: 题目列表
    """
    logger.info("开始重建RPJ模块BM25索引...")

    # TODO: 在这里实现BM25索引重建逻辑
    # from backend.core.services.bm25_service import BM25Service
    # bm25_path = f"./data/bm25/{settings.MODULE_NAME}"
    # Path(bm25_path).mkdir(parents=True, exist_ok=True)
    # ...

    raise NotImplementedError("TODO: 学生需要实现rebuild_bm25_index函数")


async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("RPJ模块向量索引重建工具")
    logger.info(f"模块: {settings.MODULE_NAME}")
    logger.info(f"支持学科: {', '.join(RPJ_SUBJECTS)}")
    logger.info("=" * 60)
    logger.warning("⚠️  本脚本为框架代码，需要学生完成实现")
    logger.info("=" * 60)

    try:
        # 1. 获取RPJ模块题目
        questions = await fetch_rpj_questions()

        if not questions:
            logger.warning("⚠️  数据库中没有RPJ模块的题目，索引重建已跳过")
            return

        # 2. 重建FAISS索引
        await rebuild_faiss_index(questions)

        # 3. 重建BM25索引
        await rebuild_bm25_index(questions)

        logger.info("=" * 60)
        logger.info("🎉 RPJ模块所有索引重建完成！")
        logger.info("=" * 60)

    except NotImplementedError as e:
        logger.error(f"❌ {e}")
        logger.info("💡 请参考 backend/scripts/rebuild_tony_indexes.py 完成实现")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 索引重建过程中发生错误: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
