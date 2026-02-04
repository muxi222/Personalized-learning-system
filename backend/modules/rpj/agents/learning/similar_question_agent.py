"""
相似题目推荐Agent - Similar Question Agent (RPJ模块 - 学生实现版本)

基于 backend/modules/tony/agents/similar_question_agent.py 实现
专门支持语文、英语、道法三个学科的相似题目推荐
"""

import logging
import json
import os
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from langgraph.graph import StateGraph, END

from backend.core.agents.state import AgentState
from backend.core.agents.base_agent import BaseAgent
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)


class SimilarQuestionAgentState(AgentState):
    """
    相似题目推荐Agent专用状态
    针对语文、英语、道法学科优化
    """
    # 输入数据
    question_id: Optional[int] = None  # 题目ID
    question_text: str = ""  # 题目文本
    user_id: Optional[int] = None
    task_id: str = ""
    subject: str = "chinese"  # 学科
    
    # 查询参数
    top_k: int = 5  # 返回数量
    similarity_threshold: float = 0.6  # 相似度阈值
    use_hybrid_search: bool = True  # 是否使用混合搜索
    
    # 处理过程
    embedding: List[float] = []  # 查询题目的向量
    search_results: List[Dict[str, Any]] = []  # 搜索结果
    filtered_results: List[Dict[str, Any]] = []  # 过滤后的结果
    
    # 推荐结果
    recommended_questions: List[Dict[str, Any]] = []  # 推荐的相似题目
    recommendation_reasons: Dict[int, str] = {}  # 推荐理由
    practice_plan: Dict[str, Any] = {}  # 练习计划
    
    # 进度跟踪
    current_step: str = ""
    progress: float = 0.0
    errors: List[str] = []


# ============ 相似度计算函数 ============

def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    计算文本相似度（基于词频和重叠）
    """
    import re
    from collections import Counter
    
    # 分词函数
    def tokenize(text: str) -> List[str]:
        # 中文分词（简单按字分）和英文分词
        words = []
        for char in text:
            if '\u4e00-\u9fff' in char:  # 中文
                words.append(char)
            else:
                # 英文按单词分
                english_words = re.findall(r'[a-zA-Z]+', text)
                words.extend(english_words)
        return words
    
    # 分词
    words1 = tokenize(text1.lower())
    words2 = tokenize(text2.lower())
    
    if not words1 or not words2:
        return 0.0
    
    # 计算词频
    freq1 = Counter(words1)
    freq2 = Counter(words2)
    
    # 计算重叠度
    common_words = set(words1) & set(words2)
    if not common_words:
        return 0.0
    
    # Jaccard相似度
    union = set(words1) | set(words2)
    jaccard_sim = len(common_words) / len(union)
    
    # 余弦相似度（基于词频）
    dot_product = sum(freq1[word] * freq2[word] for word in common_words)
    norm1 = sum(freq1[word] ** 2 for word in words1) ** 0.5
    norm2 = sum(freq2[word] ** 2 for word in words2) ** 0.5
    
    if norm1 == 0 or norm2 == 0:
        cosine_sim = 0.0
    else:
        cosine_sim = dot_product / (norm1 * norm2)
    
    # 综合相似度
    similarity = 0.7 * cosine_sim + 0.3 * jaccard_sim
    return similarity


def calculate_vector_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    计算向量相似度（余弦相似度）
    """
    import math
    
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    
    # 点积
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    
    # 模长
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / (norm1 * norm2)


def hybrid_similarity(text_sim: float, vector_sim: float, 
                      text_weight: float = 0.4, vector_weight: float = 0.6) -> float:
    """
    混合相似度计算
    """
    return text_weight * text_sim + vector_weight * vector_sim


# ============ 学科专用相似度函数 ============

def chinese_question_similarity(question1: Dict[str, Any], question2: Dict[str, Any]) -> float:
    """
    语文题目相似度计算
    """
    # 基础文本相似度
    text_sim = calculate_text_similarity(
        question1.get("text", ""),
        question2.get("text", "")
    )
    
    # 题型匹配加分
    type1 = question1.get("question_type", "")
    type2 = question2.get("question_type", "")
    if type1 == type2 and type1:
        text_sim += 0.2
    
    # 知识点匹配
    kp1 = set(question1.get("knowledge_points", []))
    kp2 = set(question2.get("knowledge_points", []))
    if kp1 and kp2:
        kp_overlap = len(kp1 & kp2) / len(kp1 | kp2)
        text_sim += 0.3 * kp_overlap
    
    return min(text_sim, 1.0)


def english_question_similarity(question1: Dict[str, Any], question2: Dict[str, Any]) -> float:
    """
    英语题目相似度计算
    """
    # 基础文本相似度
    text_sim = calculate_text_similarity(
        question1.get("text", ""),
        question2.get("text", "")
    )
    
    # 语法点匹配
    grammar1 = set(question1.get("grammar_points", []))
    grammar2 = set(question2.get("grammar_points", []))
    if grammar1 and grammar2:
        grammar_overlap = len(grammar1 & grammar2) / len(grammar1 | grammar2)
        text_sim += 0.4 * grammar_overlap
    
    # 题型匹配
    if question1.get("question_type") == question2.get("question_type"):
        text_sim += 0.1
    
    return min(text_sim, 1.0)


def morality_question_similarity(question1: Dict[str, Any], question2: Dict[str, Any]) -> float:
    """
    道法题目相似度计算
    """
    # 基础文本相似度
    text_sim = calculate_text_similarity(
        question1.get("text", ""),
        question2.get("text", "")
    )
    
    # 政治概念匹配
    concepts1 = set(question1.get("political_concepts", []))
    concepts2 = set(question2.get("political_concepts", []))
    if concepts1 and concepts2:
        concept_overlap = len(concepts1 & concepts2) / len(concepts1 | concepts2)
        text_sim += 0.5 * concept_overlap
    
    # 题型匹配
    if question1.get("question_type") == question2.get("question_type"):
        text_sim += 0.2
    
    return min(text_sim, 1.0)


# ============ Graph Nodes 实现 ============

async def query_embedding(state: SimilarQuestionAgentState) -> Dict[str, Any]:
    """
    查询题目向量节点 - 获取查询题目的向量表示
    """
    logger.info(f"[Query Embedding] Task {state.get('task_id')}: 获取题目向量")
    
    question_id = state.get("question_id")
    question_text = state.get("question_text", "")
    subject = state.get("subject", "chinese")
    
    if not question_text and not question_id:
        return {
            "errors": ["需要提供题目文本或题目ID"],
            "current_step": "query_embedding",
            "progress": 10.0,
        }
    
    try:
        embedding = []
        
        if question_id:
            # 从向量库中查询题目向量
            vector_dir = f"data/rpj/vectors/{subject}"
            vector_file = f"{vector_dir}/vector_{question_id}.json"
            
            if os.path.exists(vector_file):
                with open(vector_file, 'r', encoding='utf-8') as f:
                    vector_data = json.load(f)
                embedding = vector_data.get("embedding", [])
                logger.info(f"[Query Embedding] 从文件加载向量，维度: {len(embedding)}")
        
        if not embedding and question_text:
            # 生成查询题目的向量
            # TODO: 调用Embedding服务
            # 这里使用模拟向量
            
            import random
            embedding_dim = 384
            embedding = [random.uniform(-1, 1) for _ in range(embedding_dim)]
            
            # 归一化
            import math
            norm = math.sqrt(sum(x * x for x in embedding))
            if norm > 0:
                embedding = [x / norm for x in embedding]
            
            logger.info(f"[Query Embedding] 生成新向量，维度: {len(embedding)}")
        
        return {
            "embedding": embedding,
            "embedding_dim": len(embedding),
            "current_step": "query_embedding",
            "progress": 30.0,
        }
        
    except Exception as e:
        logger.error(f"[Query Embedding] 错误: {e}")
        return {
            "errors": [f"向量查询失败: {str(e)}"],
            "current_step": "query_embedding",
            "progress": 10.0,
        }


async def search_similar_questions(state: SimilarQuestionAgentState) -> Dict[str, Any]:
    """
    搜索相似题目节点 - 在题库中搜索相似题目
    """
    logger.info(f"[Search Similar Questions] Task {state.get('task_id')}: 搜索相似题目")
    
    question_text = state.get("question_text", "")
    question_id = state.get("question_id")
    embedding = state.get("embedding", [])
    subject = state.get("subject", "chinese")
    top_k = state.get("top_k", 5)
    similarity_threshold = state.get("similarity_threshold", 0.6)
    
    if not question_text and not embedding:
        return {
            "search_results": [],
            "current_step": "search_similar_questions",
            "progress": 50.0,
        }
    
    try:
        search_results = []
        
        # 从题目库中加载题目
        question_dir = f"data/rpj/questions/{subject}"
        vector_dir = f"data/rpj/vectors/{subject}"
        
        if not os.path.exists(question_dir):
            return {
                "search_results": [],
                "current_step": "search_similar_questions",
                "progress": 50.0,
            }
        
        # 遍历所有题目文件
        question_files = []
        for root, dirs, files in os.walk(question_dir):
            for file in files:
                if file.endswith(".json"):
                    question_files.append(os.path.join(root, file))
        
        logger.info(f"[Search Similar Questions] 在 {subject} 学科中找到 {len(question_files)} 道题目")
        
        for q_file in question_files:
            try:
                with open(q_file, 'r', encoding='utf-8') as f:
                    question_data = json.load(f)
                
                # 跳过查询题目本身
                q_id = question_data.get("question_id")
                if question_id and q_id == question_id:
                    continue
                
                q_text = question_data.get("question_body", "")
                q_knowledge_points = question_data.get("knowledge_points", [])
                q_difficulty = question_data.get("difficulty", "")
                q_type = question_data.get("question_type", "")
                
                # 计算相似度
                similarity = 0.0
                
                # 文本相似度
                text_sim = calculate_text_similarity(question_text, q_text)
                
                # 向量相似度（如果有向量）
                vector_sim = 0.0
                if embedding:
                    # 尝试加载题目向量
                    vector_file = f"{vector_dir}/vector_{q_id}.json"
                    if os.path.exists(vector_file):
                        with open(vector_file, 'r', encoding='utf-8') as vf:
                            vector_data = json.load(vf)
                        q_embedding = vector_data.get("embedding", [])
                        if q_embedding and len(q_embedding) == len(embedding):
                            vector_sim = calculate_vector_similarity(embedding, q_embedding)
                
                # 混合相似度
                if state.get("use_hybrid_search", True):
                    similarity = hybrid_similarity(text_sim, vector_sim)
                else:
                    similarity = text_sim
                
                # 应用学科专用相似度计算
                subject_specific_sim = 0.0
                if subject == "chinese":
                    subject_specific_sim = chinese_question_similarity(
                        {"text": question_text, "knowledge_points": []},
                        {"text": q_text, "knowledge_points": q_knowledge_points, "question_type": q_type}
                    )
                elif subject == "english":
                    subject_specific_sim = english_question_similarity(
                        {"text": question_text, "grammar_points": []},
                        {"text": q_text, "grammar_points": q_knowledge_points, "question_type": q_type}
                    )
                elif subject == "morality":
                    subject_specific_sim = morality_question_similarity(
                        {"text": question_text, "political_concepts": []},
                        {"text": q_text, "political_concepts": q_knowledge_points, "question_type": q_type}
                    )
                
                # 综合相似度
                final_similarity = 0.7 * similarity + 0.3 * subject_specific_sim
                
                if final_similarity >= similarity_threshold:
                    search_results.append({
                        "question_id": q_id,
                        "similarity": final_similarity,
                        "text": q_text[:100] + "..." if len(q_text) > 100 else q_text,
                        "full_text": q_text,
                        "knowledge_points": q_knowledge_points,
                        "difficulty": q_difficulty,
                        "question_type": q_type,
                        "source_file": q_file,
                    })
                    
            except Exception as e:
                logger.warning(f"处理题目文件失败: {q_file}, 错误: {e}")
        
        # 按相似度排序
        search_results.sort(key=lambda x: x["similarity"], reverse=True)
        
        logger.info(f"[Search Similar Questions] 找到 {len(search_results)} 道相似题目")
        
        return {
            "search_results": search_results,
            "current_step": "search_similar_questions",
            "progress": 70.0,
        }
        
    except Exception as e:
        logger.error(f"[Search Similar Questions] 错误: {e}")
        return {
            "errors": [f"搜索失败: {str(e)}"],
            "search_results": [],
            "current_step": "search_similar_questions",
            "progress": 50.0,
        }


async def filter_results(state: SimilarQuestionAgentState) -> Dict[str, Any]:
    """
    过滤结果节点 - 根据各种条件过滤搜索结果
    """
    logger.info(f"[Filter Results] Task {state.get('task_id')}: 过滤结果")
    
    search_results = state.get("search_results", [])
    top_k = state.get("top_k", 5)
    
    if not search_results:
        return {
            "filtered_results": [],
            "current_step": "filter_results",
            "progress": 80.0,
        }
    
    try:
        filtered_results = []
        
        # 1. 去重（基于题目ID）
        seen_ids = set()
        for result in search_results:
            q_id = result.get("question_id")
            if q_id not in seen_ids:
                seen_ids.add(q_id)
                filtered_results.append(result)
        
        # 2. 限制数量
        filtered_results = filtered_results[:top_k * 2]  # 先多留一些，用于后续过滤
        
        # 3. 多样性过滤（避免过于相似的题目）
        diverse_results = []
        for i, result1 in enumerate(filtered_results):
            # 检查是否与已选题目过于相似
            too_similar = False
            for result2 in diverse_results:
                sim = calculate_text_similarity(
                    result1.get("full_text", ""),
                    result2.get("full_text", "")
                )
                if sim > 0.8:  # 相似度超过0.8认为过于相似
                    too_similar = True
                    break
            
            if not too_similar:
                diverse_results.append(result1)
            
            if len(diverse_results) >= top_k:
                break
        
        # 4. 难度分布（尽量包含不同难度）
        difficulty_groups = {"easy": [], "medium": [], "hard": []}
        for result in diverse_results:
            difficulty = result.get("difficulty", "").lower()
            if "easy" in difficulty or "初级" in difficulty:
                difficulty_groups["easy"].append(result)
            elif "hard" in difficulty or "高级" in difficulty:
                difficulty_groups["hard"].append(result)
            else:
                difficulty_groups["medium"].append(result)
        
        # 确保每个难度至少有一题（如果有的话）
        final_results = []
        for difficulty in ["easy", "medium", "hard"]:
            if difficulty_groups[difficulty]:
                final_results.append(difficulty_groups[difficulty][0])
        
        # 补充其他题目直到达到top_k
        for result in diverse_results:
            if result not in final_results and len(final_results) < top_k:
                final_results.append(result)
        
        logger.info(f"[Filter Results] 过滤后得到 {len(final_results)} 道题目")
        
        return {
            "filtered_results": final_results,
            "current_step": "filter_results",
            "progress": 80.0,
        }
        
    except Exception as e:
        logger.error(f"[Filter Results] 错误: {e}")
        return {
            "errors": [f"过滤失败: {str(e)}"],
            "filtered_results": search_results[:top_k],
            "current_step": "filter_results",
            "progress": 80.0,
        }


async def generate_recommendations(state: SimilarQuestionAgentState) -> Dict[str, Any]:
    """
    生成推荐节点 - 为每个相似题目生成推荐理由
    """
    logger.info(f"[Generate Recommendations] Task {state.get('task_id')}: 生成推荐")
    
    filtered_results = state.get("filtered_results", [])
    question_text = state.get("question_text", "")
    subject = state.get("subject", "chinese")
    
    if not filtered_results:
        return {
            "recommended_questions": [],
            "recommendation_reasons": {},
            "current_step": "generate_recommendations",
            "progress": 90.0,
        }
    
    try:
        recommended_questions = []
        recommendation_reasons = {}
        
        for i, result in enumerate(filtered_results):
            q_id = result.get("question_id")
            similarity = result.get("similarity", 0)
            knowledge_points = result.get("knowledge_points", [])
            difficulty = result.get("difficulty", "")
            q_type = result.get("question_type", "")
            
            # 生成推荐理由
            reason = generate_recommendation_reason(
                subject=subject,
                similarity=similarity,
                knowledge_points=knowledge_points,
                difficulty=difficulty,
                question_type=q_type,
                index=i+1
            )
            
            recommendation_reasons[q_id] = reason
            
            # 构建推荐题目信息
            recommended_question = {
                "question_id": q_id,
                "similarity_score": similarity,
                "content": result.get("text", ""),
                "full_content": result.get("full_text", ""),
                "knowledge_points": knowledge_points,
                "difficulty": difficulty,
                "question_type": q_type,
                "recommendation_reason": reason,
                "practice_order": i + 1,
            }
            
            recommended_questions.append(recommended_question)
        
        logger.info(f"[Generate Recommendations] 生成了 {len(recommended_questions)} 条推荐")
        
        return {
            "recommended_questions": recommended_questions,
            "recommendation_reasons": recommendation_reasons,
            "current_step": "generate_recommendations",
            "progress": 90.0,
        }
        
    except Exception as e:
        logger.error(f"[Generate Recommendations] 错误: {e}")
        return {
            "errors": [f"推荐生成失败: {str(e)}"],
            "recommended_questions": [],
            "recommendation_reasons": {},
            "current_step": "generate_recommendations",
            "progress": 90.0,
        }


async def create_practice_plan(state: SimilarQuestionAgentState) -> Dict[str, Any]:
    """
    创建练习计划节点 - 基于推荐题目生成练习计划
    """
    logger.info(f"[Create Practice Plan] Task {state.get('task_id')}: 创建练习计划")
    
    recommended_questions = state.get("recommended_questions", [])
    question_text = state.get("question_text", "")
    subject = state.get("subject", "chinese")
    
    if not recommended_questions:
        return {
            "practice_plan": {},
            "current_step": "create_practice_plan",
            "progress": 100.0,
        }
    
    try:
        # 分析知识点分布
        all_knowledge_points = []
        for q in recommended_questions:
            all_knowledge_points.extend(q.get("knowledge_points", []))
        
        # 统计知识点频率
        from collections import Counter
        kp_counter = Counter(all_knowledge_points)
        top_knowledge_points = [kp for kp, count in kp_counter.most_common(3)]
        
        # 难度分布
        difficulty_count = {"easy": 0, "medium": 0, "hard": 0}
        for q in recommended_questions:
            diff = q.get("difficulty", "").lower()
            if "easy" in diff or "初级" in diff:
                difficulty_count["easy"] += 1
            elif "hard" in diff or "高级" in diff:
                difficulty_count["hard"] += 1
            else:
                difficulty_count["medium"] += 1
        
        # 创建练习计划
        practice_plan = {
            "subject": subject,
            "total_questions": len(recommended_questions),
            "estimated_time": len(recommended_questions) * 10,  # 估计每道题10分钟
            "focus_knowledge_points": top_knowledge_points,
            "difficulty_distribution": difficulty_count,
            "recommended_schedule": generate_practice_schedule(
                subject=subject,
                total_questions=len(recommended_questions),
                difficulty_count=difficulty_count
            ),
            "learning_objectives": generate_learning_objectives(subject, top_knowledge_points),
            "tips": generate_practice_tips(subject),
        }
        
        # 添加题目列表（仅ID和基本信息）
        practice_plan["question_list"] = [
            {
                "question_id": q["question_id"],
                "practice_order": q["practice_order"],
                "difficulty": q["difficulty"],
                "estimated_time": 10,  # 每道题10分钟
            }
            for q in recommended_questions
        ]
        
        logger.info(f"[Create Practice Plan] 创建了{subject}练习计划，包含{len(recommended_questions)}道题")
        
        return {
            "practice_plan": practice_plan,
            "current_step": "create_practice_plan",
            "progress": 100.0,
        }
        
    except Exception as e:
        logger.error(f"[Create Practice Plan] 错误: {e}")
        return {
            "errors": [f"练习计划创建失败: {str(e)}"],
            "practice_plan": {},
            "current_step": "create_practice_plan",
            "progress": 100.0,
        }


# ============ 辅助函数 ============

def generate_recommendation_reason(
    subject: str,
    similarity: float,
    knowledge_points: List[str],
    difficulty: str,
    question_type: str,
    index: int
) -> str:
    """
    生成推荐理由
    """
    if subject == "chinese":
        if similarity > 0.8:
            reason = f"此题与原题高度相似（相似度{similarity:.2%}），都考察了{knowledge_points[0] if knowledge_points else '相关知识点'}。"
        elif similarity > 0.6:
            reason = f"此题与原题相似度较高（{similarity:.2%}），可以帮助你巩固{knowledge_points[0] if knowledge_points else '相关'}知识点。"
        else:
            reason = f"此题与原题有一定关联（相似度{similarity:.2%}），可以拓展你的解题思路。"
        
        if question_type:
            reason += f" 此题是{question_type}题型，有助于你掌握这类题目的解题方法。"
    
    elif subject == "english":
        if similarity > 0.8:
            reason = f"This question is highly similar to the original one ({similarity:.2%}), both testing {knowledge_points[0] if knowledge_points else 'related knowledge points'}."
        elif similarity > 0.6:
            reason = f"This question has good similarity ({similarity:.2%}), which can help you consolidate {knowledge_points[0] if knowledge_points else 'relevant'} knowledge."
        else:
            reason = f"This question is somewhat related ({similarity:.2%}), which can expand your problem-solving skills."
        
        if question_type:
            reason += f" This is a {question_type} question, helping you master this type of exercise."
    
    elif subject == "morality":
        if similarity > 0.8:
            reason = f"此题与原题高度相似（相似度{similarity:.2%}），都涉及{knowledge_points[0] if knowledge_points else '相关政治概念'}。"
        elif similarity > 0.6:
            reason = f"此题与原题相似度较高（{similarity:.2%}），可以帮助你理解{knowledge_points[0] if knowledge_points else '相关'}概念。"
        else:
            reason = f"此题与原题有一定关联（相似度{similarity:.2%}），可以拓展你的思维广度。"
        
        if question_type:
            reason += f" 此题是{question_type}题型，有助于提高你的论述能力。"
    
    else:
        reason = f"推荐此题（相似度{similarity:.2%}），有助于巩固相关知识。"
    
    # 添加难度提示
    if "easy" in difficulty.lower() or "初级" in difficulty:
        reason += " 题目难度较低，适合巩固基础。"
    elif "hard" in difficulty.lower() or "高级" in difficulty:
        reason += " 题目有一定难度，适合挑战自我。"
    
    return reason


def generate_practice_schedule(
    subject: str,
    total_questions: int,
    difficulty_count: Dict[str, int]
) -> List[Dict[str, Any]]:
    """
    生成练习计划表
    """
    schedule = []
    
    # 根据题目数量决定练习天数
    if total_questions <= 3:
        days = 1
    elif total_questions <= 6:
        days = 2
    else:
        days = 3
    
    questions_per_day = total_questions // days + (1 if total_questions % days > 0 else 0)
    
    for day in range(1, days + 1):
        day_schedule = {
            "day": day,
            "focus": f"完成{questions_per_day}道练习题",
            "estimated_time": questions_per_day * 10,
            "suggested_time": "晚上19:00-20:00",
            "objectives": [],
        }
        
        if subject == "chinese":
            day_schedule["objectives"] = [
                "理解题目考查的知识点",
                "掌握解题思路和方法",
                "总结错题经验"
            ]
        elif subject == "english":
            day_schedule["objectives"] = [
                "Understand the knowledge points",
                "Master problem-solving methods",
                "Summarize mistakes"
            ]
        elif subject == "morality":
            day_schedule["objectives"] = [
                "理解政治概念和原理",
                "掌握答题规范和格式",
                "联系实际案例分析"
            ]
        
        schedule.append(day_schedule)
    
    return schedule


def generate_learning_objectives(subject: str, knowledge_points: List[str]) -> List[str]:
    """
    生成学习目标
    """
    if subject == "chinese":
        objectives = [
            "掌握相关知识点和解题方法",
            "提高阅读理解能力",
            "加强文言文翻译能力",
            "提升作文写作水平"
        ]
        
        if knowledge_points:
            objectives.insert(0, f"重点掌握{knowledge_points[0]}")
    
    elif subject == "english":
        objectives = [
            "Master key vocabulary and grammar",
            "Improve reading comprehension",
            "Enhance writing skills",
            "Practice listening and speaking"
        ]
        
        if knowledge_points:
            objectives.insert(0, f"Focus on {knowledge_points[0]}")
    
    elif subject == "morality":
        objectives = [
            "理解政治概念和原理",
            "掌握案例分析方法",
            "提高论述表达能力",
            "关注时事政治"
        ]
        
        if knowledge_points:
            objectives.insert(0, f"深入理解{knowledge_points[0]}")
    
    else:
        objectives = ["巩固相关知识，提高解题能力"]
    
    return objectives


def generate_practice_tips(subject: str) -> List[str]:
    """
    生成练习建议
    """
    if subject == "chinese":
        return [
            "先独立完成题目，再看答案解析",
            "总结每道题的解题思路",
            "建立错题本，定期复习",
            "多读优秀范文，积累素材"
        ]
    
    elif subject == "english":
        return [
            "Practice questions independently first",
            "Summarize problem-solving strategies",
            "Maintain an error notebook",
            "Read English materials regularly"
        ]
    
    elif subject == "morality":
        return [
            "先理解概念，再做题",
            "注意答题规范和格式",
            "多关注时事新闻",
            "理论联系实际分析"
        ]
    
    else:
        return [
            "认真审题，理解题意",
            "独立思考，不要急于看答案",
            "总结错误原因，避免再犯",
            "定期复习，巩固知识"
        ]


# ============ Graph Definition ============

def create_similar_question_graph():
    """
    创建相似题目推荐Agent的工作流图
    
    流程:
    1. query_embedding: 查询题目向量
    2. search_similar_questions: 搜索相似题目
    3. filter_results: 过滤搜索结果
    4. generate_recommendations: 生成推荐
    5. create_practice_plan: 创建练习计划
    """
    workflow = StateGraph(SimilarQuestionAgentState)
    
    # 添加节点
    workflow.add_node("query_embedding", query_embedding)
    workflow.add_node("search_similar_questions", search_similar_questions)
    workflow.add_node("filter_results", filter_results)
    workflow.add_node("generate_recommendations", generate_recommendations)
    workflow.add_node("create_practice_plan", create_practice_plan)
    
    # 定义工作流
    workflow.set_entry_point("query_embedding")
    workflow.add_edge("query_embedding", "search_similar_questions")
    workflow.add_edge("search_similar_questions", "filter_results")
    workflow.add_edge("filter_results", "generate_recommendations")
    workflow.add_edge("generate_recommendations", "create_practice_plan")
    workflow.add_edge("create_practice_plan", END)
    
    return workflow.compile()


# 懒加载编译的图
_similar_question_graph = None


def get_similar_question_graph():
    """获取相似题目推荐Agent图（懒加载）"""
    global _similar_question_graph
    if _similar_question_graph is None:
        _similar_question_graph = create_similar_question_graph()
    return _similar_question_graph


class SimilarQuestionAgent(BaseAgent):
    """
    RPJ相似题目推荐Agent类
    
    专门支持语文、英语、道法三个学科的相似题目推荐
    """
    
    def __init__(self):
        # 只支持语文、英语、道法
        supported_subjects = ["chinese", "english", "morality"]
        super().__init__(subjects=supported_subjects)
        self.graph = get_similar_question_graph()
        logger.info(f"[{settings.MODULE_NAME.upper()}] RPJ SimilarQuestionAgent 初始化完成，支持学科: {supported_subjects}")
    
    async def process(
        self,
        question_text: Optional[str] = None,
        question_id: Optional[int] = None,
        user_id: Optional[int] = None,
        task_id: str = "",
        subject: str = "chinese",
        top_k: int = 5,
        similarity_threshold: float = 0.6,
        use_hybrid_search: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        处理相似题目推荐的主方法
        
        Args:
            question_text: 题目文本
            question_id: 题目ID
            user_id: 用户ID
            task_id: 任务ID
            subject: 学科类型 (chinese, english, morality)
            top_k: 返回的相似题目数量
            similarity_threshold: 相似度阈值
            use_hybrid_search: 是否使用混合搜索
            
        Returns:
            处理结果字典
        """
        logger.info(f"[RPJ SimilarQuestionAgent] 开始处理任务 {task_id}, 学科: {subject}")
        
        # 验证学科
        if not self.validate_subject(subject):
            return {
                "task_id": task_id,
                "success": False,
                "errors": [f"学科 '{subject}' 不支持，支持的学科: {self.subjects}"],
            }
        
        # 必须提供题目文本或题目ID
        if not question_text and not question_id:
            return {
                "task_id": task_id,
                "success": False,
                "errors": ["必须提供题目文本或题目ID"],
            }
        
        # 初始化状态
        initial_state: SimilarQuestionAgentState = {
            "question_id": question_id,
            "question_text": question_text or "",
            "user_id": user_id,
            "task_id": task_id,
            "subject": subject,
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "use_hybrid_search": use_hybrid_search,
            "errors": [],
        }
        
        # 执行工作流
        final_state = None
        try:
            async for state in self.graph.astream(initial_state):
                for node_name, node_output in state.items():
                    if isinstance(node_output, dict):
                        # 合并状态
                        final_state = {**initial_state, **(final_state or {}), **node_output}
        except Exception as e:
            logger.error(f"[RPJ SimilarQuestionAgent] 工作流执行错误: {e}")
            return {
                "task_id": task_id,
                "success": False,
                "errors": [f"处理失败: {str(e)}"],
            }
        
        # 构建返回结果
        if final_state:
            result = {
                "task_id": task_id,
                "success": not bool(final_state.get("errors", [])),
                "query_question": question_text or f"题目ID: {question_id}",
                "subject": subject,
                "total_found": len(final_state.get("search_results", [])),
                "total_recommended": len(final_state.get("recommended_questions", [])),
                "recommended_questions": final_state.get("recommended_questions", []),
                "practice_plan": final_state.get("practice_plan", {}),
                "search_metrics": {
                    "similarity_threshold": similarity_threshold,
                    "top_k": top_k,
                    "use_hybrid_search": use_hybrid_search,
                },
                "errors": final_state.get("errors", []),
                "progress": final_state.get("progress", 0),
                "current_step": final_state.get("current_step", ""),
            }
        else:
            result = {
                "task_id": task_id,
                "success": False,
                "errors": ["处理失败，未生成有效结果"],
            }
        
        logger.info(f"[RPJ SimilarQuestionAgent] 任务 {task_id} 处理完成，成功: {result['success']}, 推荐题目数: {result['total_recommended']}")
        return result
    
    async def get_knowledge_recommendations(
        self,
        knowledge_points: List[str],
        subject: str = "chinese",
        user_id: Optional[int] = None,
        top_k: int = 5
    ) -> Dict[str, Any]:
        """
        基于知识点推荐题目
        
        Args:
            knowledge_points: 知识点列表
            subject: 学科类型
            user_id: 用户ID
            top_k: 返回数量
            
        Returns:
            题目推荐结果
        """
        logger.info(f"[RPJ SimilarQuestionAgent] 基于知识点推荐题目，学科: {subject}, 知识点: {knowledge_points}")
        
        # 验证学科
        if not self.validate_subject(subject):
            return {
                "success": False,
                "errors": [f"学科 '{subject}' 不支持"],
            }
        
        # 从题库中查找包含指定知识点的题目
        question_dir = f"data/rpj/questions/{subject}"
        if not os.path.exists(question_dir):
            return {
                "success": True,
                "knowledge_points": knowledge_points,
                "recommended_questions": [],
                "total_found": 0,
            }
        
        try:
            recommended_questions = []
            knowledge_point_set = set(knowledge_points)
            
            # 遍历题目文件
            for root, dirs, files in os.walk(question_dir):
                for file in files:
                    if file.endswith(".json"):
                        filepath = os.path.join(root, file)
                        
                        with open(filepath, 'r', encoding='utf-8') as f:
                            question_data = json.load(f)
                        
                        # 检查知识点匹配
                        q_knowledge_points = set(question_data.get("knowledge_points", []))
                        if knowledge_point_set & q_knowledge_points:  # 有交集
                            match_count = len(knowledge_point_set & q_knowledge_points)
                            match_ratio = match_count / len(knowledge_point_set) if knowledge_point_set else 0
                            
                            recommended_questions.append({
                                "question_id": question_data.get("question_id"),
                                "match_score": match_ratio,
                                "content": question_data.get("question_body", "")[:100] + "...",
                                "knowledge_points": list(q_knowledge_points),
                                "difficulty": question_data.get("difficulty", ""),
                                "match_knowledge_points": list(knowledge_point_set & q_knowledge_points),
                            })
            
            # 按匹配度排序
            recommended_questions.sort(key=lambda x: x["match_score"], reverse=True)
            recommended_questions = recommended_questions[:top_k]
            
            # 生成推荐理由
            for q in recommended_questions:
                match_kps = q.get("match_knowledge_points", [])
                if match_kps:
                    q["recommendation_reason"] = f"此题涉及知识点：{', '.join(match_kps[:3])}"
                else:
                    q["recommendation_reason"] = "此题包含相关知识点"
            
            return {
                "success": True,
                "knowledge_points": knowledge_points,
                "recommended_questions": recommended_questions,
                "total_found": len(recommended_questions),
                "summary": f"找到{len(recommended_questions)}道包含指定知识点的题目",
            }
            
        except Exception as e:
            logger.error(f"[RPJ SimilarQuestionAgent] 知识点推荐错误: {e}")
            return {
                "success": False,
                "errors": [f"知识点推荐失败: {str(e)}"],
            }
    
    async def analyze_question_pattern(
        self,
        question_text: str,
        subject: str = "chinese"
    ) -> Dict[str, Any]:
        """
        分析题目模式
        
        Args:
            question_text: 题目文本
            subject: 学科类型
            
        Returns:
            题目模式分析结果
        """
        logger.info(f"[RPJ SimilarQuestionAgent] 分析题目模式，学科: {subject}")
        
        # 验证学科
        if not self.validate_subject(subject):
            return {
                "success": False,
                "errors": [f"学科 '{subject}' 不支持"],
            }
        
        try:
            # 提取题目特征
            features = {
                "subject": subject,
                "length": len(question_text),
                "word_count": len(question_text.split()),
                "has_question_mark": "?" in question_text or "？" in question_text,
                "has_chinese": any('\u4e00-\u9fff' in char for char in question_text),
                "has_english": any(c.isalpha() for c in question_text),
                "has_numbers": any(c.isdigit() for c in question_text),
            }
            
            # 题型识别
            question_type = "unknown"
            if subject == "chinese":
                if "文言文" in question_text or "古文" in question_text:
                    question_type = "classical_chinese"
                elif "作文" in question_text or "写作" in question_text:
                    question_type = "composition"
                elif "阅读" in question_text and "理解" in question_text:
                    question_type = "reading_comprehension"
                elif "选择" in question_text:
                    question_type = "multiple_choice"
                elif "填空" in question_text:
                    question_type = "fill_in_blank"
            
            elif subject == "english":
                question_text_lower = question_text.lower()
                if "multiple choice" in question_text_lower or "choose" in question_text_lower:
                    question_type = "multiple_choice"
                elif "cloze" in question_text_lower:
                    question_type = "cloze_test"
                elif "reading" in question_text_lower and "comprehension" in question_text_lower:
                    question_type = "reading_comprehension"
                elif "writing" in question_text_lower or "composition" in question_text_lower:
                    question_type = "writing"
                elif "translation" in question_text_lower:
                    question_type = "translation"
            
            elif subject == "morality":
                if "选择" in question_text:
                    question_type = "multiple_choice"
                elif "简答" in question_text:
                    question_type = "short_answer"
                elif "论述" in question_text:
                    question_type = "essay"
                elif "案例" in question_text and "分析" in question_text:
                    question_type = "case_analysis"
                elif "辨析" in question_text:
                    question_type = "analysis"
            
            features["question_type"] = question_type
            
            # 难度估计
            difficulty = "medium"
            text_length = len(question_text)
            if text_length < 50:
                difficulty = "easy"
            elif text_length > 200:
                difficulty = "hard"
            
            features["difficulty"] = difficulty
            
            # 知识点提取（简单关键词匹配）
            knowledge_keywords = []
            if subject == "chinese":
                chinese_keywords = ["修辞", "文言文", "古诗", "现代文", "作文", "阅读理解"]
                knowledge_keywords = [kw for kw in chinese_keywords if kw in question_text]
            elif subject == "english":
                english_keywords = ["grammar", "vocabulary", "reading", "writing", "listening", "translation"]
                knowledge_keywords = [kw for kw in english_keywords if kw.lower() in question_text.lower()]
            elif subject == "morality":
                morality_keywords = ["社会主义核心价值观", "法律", "道德", "政治", "经济", "文化"]
                knowledge_keywords = [kw for kw in morality_keywords if kw in question_text]
            
            features["knowledge_keywords"] = knowledge_keywords
            
            return {
                "success": True,
                "question_text": question_text[:100] + "..." if len(question_text) > 100 else question_text,
                "features": features,
                "analysis": f"这是一道{subject}学科的{question_type}题型，难度{difficulty}",
            }
            
        except Exception as e:
            logger.error(f"[RPJ SimilarQuestionAgent] 题目模式分析错误: {e}")
            return {
                "success": False,
                "errors": [f"题目模式分析失败: {str(e)}"],
            }