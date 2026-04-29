"""
XMX (Economics) 检索准召率评估器.

指标说明:
- hit@k: 前 k 个结果中是否包含至少一个相关经济学题目。
- precision@k / recall@k: 经济学知识检索的准/召指标。
- mrr@k: 第一个相关结果的倒数排名。
- ndcg@k: 排序质量（评价检索出的经济学案例是否按相关度排序）。

模式:
1) 手动标注 (Manual): 传入 --labels (指向 economics_retrieval_labels.jsonl)
2) 弱监督 (Weak Supervision): 自动寻找共享相同经济学“知识点”的题目作为相关项。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

# 路径修复
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../../"))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 导入 Tony 脚本中通用的 IR 指标计算逻辑和基础类
from training.modules.tony.eval.retrieval_hit_rate import (
    _load_questions,
    _precision_at_k,
    _recall_at_k,
    _mrr_at_k,
    _ndcg_at_k,
    _ap_at_k,
    _InMemoryTfidfIndex,
    _retrieve_local,
    _retrieve_mcp,
    _kps_list,
    _subject_value
)

async def _amain(args: argparse.Namespace) -> Dict[str, Any]:
    # 1. 加载题目数据 (限制在经济学范围内或全量加载后过滤)
    # XMX 业务中，我们需要确保评估的是经济学相关的检索质量
    all_q = await _load_questions(max_n=args.max_questions)
    if not all_q:
        return {"error": "no questions found in database"}

    # 确定评估的用户范围 (检索通常是 User-scoped)
    user_id = int(args.user_id or (all_q[0].user_id if hasattr(all_q[0], "user_id") else 1))
    
    # 过滤出当前用户的经济学题目
    all_q_user = [
        q for q in all_q 
        if int(getattr(q, "user_id", 0) or 0) == user_id
    ]

    # 2. 构建 XMX 专属的内存索引 (用于在没有外部向量数据库时进行评估)
    # 针对经济学常见的知识点进行分桶
    inmem_index_by_subject: Dict[str, _InMemoryTfidfIndex] = {
        "__all__": _InMemoryTfidfIndex.build(all_q_user)
    }
    
    # 经济学细分领域索引 (如有需要可扩展微观/宏观)
    economics_subfields = ["macroeconomics", "microeconomics", "international_trade", "finance", "economics"]
    for sub in economics_subfields:
        q_sub = [q for q in all_q_user if (_subject_value(q) or "").strip().lower() == sub]
        if q_sub:
            inmem_index_by_subject[sub] = _InMemoryTfidfIndex.build(q_sub)

    # 3. 构造测试用例 (Cases)
    cases: List[Tuple[int, Set[int], str, Optional[str]]] = []
    
    if args.labels:
        # 模式1: 从 JSONL 加载手动标注的经济学相关性标签
        with open(args.labels, "r", encoding="utf-8") as f:
            q_by_id = {int(q.id): q for q in all_q_user}
            for line in f:
                row = json.loads(line)
                qid = int(row["query_question_id"])
                rel = set(int(x) for x in (row.get("relevant_question_ids") or []))
                q = q_by_id.get(qid)
                if q:
                    cases.append((qid, rel, q.content, _subject_value(q)))
    else:
        # 模式2: 弱监督 (Weak Supervision)
        # 如果两个经济学题目共享至少一个知识点(knowledge_point)，则认为它们相关
        sampled = all_q_user[:]
        random.shuffle(sampled)
        for q in sampled[:args.max_questions]:
            rel_ids = set()
            q_kps = set(_kps_list(q))
            if not q_kps: continue
            
            for other in all_q_user:
                if other.id == q.id: continue
                if q_kps.intersection(set(_kps_list(other))):
                    rel_ids.add(int(other.id))
            
            if rel_ids:
                query_text = f"{q.content}\n经济学知识点：{'；'.join(q_kps)}"
                cases.append((int(q.id), rel_ids, query_text, _subject_value(q)))

    if not cases:
        return {"error": "no evaluation cases found for xmx"}

    # 4. 执行检索并计算指标
    k = args.k
    hits, total = 0, 0
    metrics_sums = {"p": 0.0, "r": 0.0, "mrr": 0.0, "ndcg": 0.0, "ap": 0.0}
    counts = {"p": 0, "r": 0, "ndcg": 0, "ap": 0}

    for qid, rel, text, subj in cases:
        # 调用检索后端 (Local Hybrid 或 MCP)
        if args.mcp_url:
            got = await _retrieve_mcp(mcp_url=args.mcp_url, query_text=text, user_id=user_id, subject=subj, k=k, exclude_ids=[qid])
        else:
            # 默认使用本地 Hybrid 或 TF-IDF 降级方案
            got = await _retrieve_local(
                query_text=text, user_id=user_id, subject=subj, k=k, exclude_ids=[qid],
                inmem_index_by_subject=inmem_index_by_subject,
                allow_runtime_hybrid=True # 允许在环境支持时使用 FAISS
            )
        
        total += 1
        if any(gid in rel for gid in got): hits += 1
        
        # 计算各项 IR 指标
        p = _precision_at_k(got, rel, k)
        if p is not None: metrics_sums["p"] += p; counts["p"] += 1
        
        r = _recall_at_k(got, rel, k)
        if r is not None: metrics_sums["r"] += r; counts["r"] += 1
        
        metrics_sums["mrr"] += _mrr_at_k(got, rel, k)
        
        ndcg = _ndcg_at_k(got, rel, k)
        if ndcg is not None: metrics_sums["ndcg"] += ndcg; counts["ndcg"] += 1
        
        ap = _ap_at_k(got, rel, k)
        if ap is not None: metrics_sums["ap"] += ap; counts["ap"] += 1

    # 5. 输出结果
    return {
        "module": "xmx",
        "subject": "economics",
        "k": k,
        "cases_analyzed": total,
        "hit_at_k": hits / total if total > 0 else 0,
        "precision_at_k": metrics_sums["p"] / counts["p"] if counts["p"] > 0 else 0,
        "recall_at_k": metrics_sums["r"] / counts["r"] if counts["r"] > 0 else 0,
        "mrr_at_k": metrics_sums["mrr"] / total if total > 0 else 0,
        "ndcg_at_k": metrics_sums["ndcg"] / counts["ndcg"] if counts["ndcg"] > 0 else 0,
        "map_at_k": metrics_sums["ap"] / counts["ap"] if counts["ap"] > 0 else 0,
        "evaluation_strategy": "weak_supervision_via_knowledge_points" if not args.labels else "manual_labeled"
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--max-questions", type=int, default=100)
    p.add_argument("--labels", type=str, default=None)
    p.add_argument("--mcp-url", type=str, default=None)
    p.add_argument("--user-id", type=int, default=None)
    p.add_argument("--out", type=str, default="")
    args = p.parse_args()

    import asyncio
    out = asyncio.run(_amain(args))
    
    # 打印结果并保存
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    main()