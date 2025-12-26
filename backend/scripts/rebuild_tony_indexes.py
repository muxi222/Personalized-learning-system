"""
TONY模块向量索引重建脚本
学科: history, geography, other
功能: 从数据库读取TONY模块相关题目，重建FAISS和BM25索引
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
from backend.modules.tony.config import settings


# TONY模块支持的学科
TONY_SUBJECTS = ["history", "geography", "other"]


async def fetch_tony_questions():
    """
    从数据库获取TONY模块的所有题目
    Returns:
        List[Question]: TONY模块题目列表
    """
    logger.info(f"正在从数据库获取TONY模块题目 (学科: {TONY_SUBJECTS})...")

    async with async_session_maker() as session:
        # 构建查询 - 筛选TONY模块的学科
        stmt = select(Question).where(
            Question.subject.in_([
                SubjectEnum.HISTORY,
                SubjectEnum.GEOGRAPHY,
                SubjectEnum.OTHER
            ])
        )

        result = await session.execute(stmt)
        questions = result.scalars().all()

        logger.info(f"成功获取 {len(questions)} 道TONY模块题目")
        return list(questions)


async def rebuild_faiss_index(questions: List[Question]):
    """
    重建TONY模块的FAISS向量索引
    Args:
        questions: 题目列表
    """
    logger.info("开始重建TONY模块FAISS索引...")

    embedding_service = get_embedding_service()
    vector_store = get_vector_store_service()

    # 使用TONY模块的向量存储路径
    index_path = settings.module_vector_path
    logger.info(f"FAISS索引路径: {index_path}")

    # 初始化向量存储（会清空现有索引）
    await vector_store.initialize(index_path=index_path, force_recreate=True)

    # 逐个添加题目到向量索引
    success_count = 0
    for i, question in enumerate(questions, 1):
        try:
            # 构建索引文本
            text_to_embed = f"{question.content}"
            if question.knowledge_points:
                text_to_embed += f"\n知识点: {', '.join(question.knowledge_points)}"
            if question.tags:
                text_to_embed += f"\n标签: {', '.join(question.tags)}"

            # 生成embedding
            embedding = await embedding_service.embed_text(text_to_embed)

            if embedding:
                # 添加到向量存储
                metadata = {
                    "question_id": str(question.id),
                    "subject": question.subject.value,
                    "difficulty": question.difficulty.value if question.difficulty else "medium",
                    "knowledge_points": ",".join(question.knowledge_points) if question.knowledge_points else "",
                    "user_id": question.user_id,
                }

                await vector_store.add_documents(
                    texts=[text_to_embed],
                    embeddings=[embedding],
                    metadatas=[metadata],
                    ids=[str(question.id)]
                )

                success_count += 1

                if i % 10 == 0:
                    logger.info(f"已处理 {i}/{len(questions)} 道题目...")
            else:
                logger.warning(f"题目ID {question.id} 生成embedding失败")

        except Exception as e:
            logger.error(f"处理题目ID {question.id} 时出错: {e}")
            continue

    logger.info(f"✅ FAISS索引重建完成！成功添加 {success_count}/{len(questions)} 道题目")


async def rebuild_bm25_index(questions: List[Question]):
    """
    重建TONY模块的BM25关键词索引
    Args:
        questions: 题目列表
    """
    logger.info("开始重建TONY模块BM25索引...")

    from backend.core.services.bm25_service import BM25Service

    bm25_path = f"./data/bm25/{settings.MODULE_NAME}"
    logger.info(f"BM25索引路径: {bm25_path}")

    # 确保目录存在
    Path(bm25_path).mkdir(parents=True, exist_ok=True)

    # 初始化BM25服务
    bm25_service = BM25Service(index_path=bm25_path)

    # 准备文档
    documents = []
    metadatas = []
    doc_ids = []

    for question in questions:
        # 构建文档文本
        doc_text = f"{question.content}"
        if question.knowledge_points:
            doc_text += f" {' '.join(question.knowledge_points)}"
        if question.tags:
            doc_text += f" {' '.join(question.tags)}"

        documents.append(doc_text)
        metadatas.append({
            "question_id": str(question.id),
            "subject": question.subject.value,
            "difficulty": question.difficulty.value if question.difficulty else "medium",
        })
        doc_ids.append(str(question.id))

    # 重建BM25索引
    bm25_service.build_index(documents, metadatas, doc_ids)

    logger.info(f"✅ BM25索引重建完成！共索引 {len(documents)} 道题目")


async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("TONY模块向量索引重建工具")
    logger.info(f"模块: {settings.MODULE_NAME}")
    logger.info(f"支持学科: {', '.join(TONY_SUBJECTS)}")
    logger.info("=" * 60)

    try:
        # 1. 获取TONY模块题目
        questions = await fetch_tony_questions()

        if not questions:
            logger.warning("⚠️  数据库中没有TONY模块的题目，索引重建已跳过")
            return

        # 2. 重建FAISS索引
        await rebuild_faiss_index(questions)

        # 3. 重建BM25索引
        await rebuild_bm25_index(questions)

        logger.info("=" * 60)
        logger.info("🎉 TONY模块所有索引重建完成！")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ 索引重建过程中发生错误: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
