#!/bin/bash
# =============================================================================
# WZY 模块完整实现脚本
# 功能：创建 wzy 模块的所有目录结构和文件
# 使用方法：
#   chmod +x setup_wzy_module.sh
#   ./setup_wzy_module.sh
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { printf "${BLUE}[INFO]${NC} %s\n" "$1"; }
log_ok() { printf "${GREEN}[OK]${NC} %s\n" "$1"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
log_err() { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

# 获取项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 检查是否在项目根目录
if [ ! -d "${PROJECT_ROOT}/backend" ] || [ ! -d "${PROJECT_ROOT}/training" ]; then
    log_err "未在项目根目录中运行！请确保在包含 backend/ 和 training/ 的目录中运行。"
    exit 1
fi

# 1. 修改 pipeline.sh 以支持 wzy 模块
modify_pipeline_script() {
    log_info "修改 pipeline.sh 以支持 wzy 模块..."
    
    PIPELINE_SCRIPT="${PROJECT_ROOT}/deploy/scripts/pipeline.sh"
    
    if [ ! -f "${PIPELINE_SCRIPT}" ]; then
        log_err "找不到 pipeline.sh 文件：${PIPELINE_SCRIPT}"
        return 1
    fi
    
    # 备份原文件
    cp "${PIPELINE_SCRIPT}" "${PIPELINE_SCRIPT}.backup.$(date +%Y%m%d_%H%M%S)"
    
    # 修改 ensure_training_module_supported 函数
    sed -i 's/if \[\[ "\$MODULE" != "tony" \&\& "\$MODULE" != "wzm" \]\]; then/if [[ "$MODULE" != "tony" && "$MODULE" != "wzm" && "$MODULE" != "wzy" ]]; then/' "${PIPELINE_SCRIPT}"
    
    log_ok "pipeline.sh 修改完成"
}

# 2. 创建目录结构
create_directories() {
    log_info "创建 wzy 模块目录结构..."
    
    # 主要目录
    DIRS=(
        "training/modules/wzy/graphrag/scripts"
        "training/modules/wzy/embedding/scripts"
        "training/modules/wzy/datasets/scripts"
        "training/modules/wzy/fine_tuning/scripts"
        "training/modules/wzy/fine_tuning/configs"
        "training/modules/wzy/eval"
        "training/modules/wzy/serving"
        "data/training/wzy/graphrag"
        "data/training/wzy/datasets/sft"
        "data/training/wzy/datasets/preference"
        "data/training/wzy/checkpoints/sft_lora"
        "data/training/wzy/checkpoints/dpo_lora"
        "data/training/wzy/eval"
        "data/faiss/wzy"
        "data/bm25/wzy"
    )
    
    for dir in "${DIRS[@]}"; do
        mkdir -p "${PROJECT_ROOT}/${dir}"
        log_info "创建目录: ${dir}"
    done
    
    log_ok "目录结构创建完成"
}

# 3. 创建 GraphRAG 脚本
create_graphrag_scripts() {
    log_info "创建 GraphRAG 脚本..."
    
    cat > "${PROJECT_ROOT}/training/modules/wzy/graphrag/scripts/build_kb.py" << 'EOF'
#!/usr/bin/env python3
"""
wzy 模块的 GraphRAG 知识库构建脚本
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

def build_kb(args):
    """构建知识图谱"""
    output_dir = Path("data/training/wzy/graphrag")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Building GraphRAG KB for wzy module")
    print(f"Build index: {args.build_index}")
    print(f"Embedding backend: {args.embedding_backend}")
    print(f"Limit: {args.limit if args.limit > 0 else 'No limit'}")
    
    # 模拟数据 - 在实际应用中应替换为真实数据
    graph = {
        "nodes": [
            {"id": "node_1", "type": "concept", "content": "数学基础概念", "properties": {"subject": "math"}},
            {"id": "node_2", "type": "concept", "content": "代数方程", "properties": {"subject": "math"}},
            {"id": "node_3", "type": "concept", "content": "几何图形", "properties": {"subject": "math"}},
            {"id": "node_4", "type": "question", "content": "如何解一元二次方程？", "properties": {"difficulty": "medium"}},
            {"id": "node_5", "type": "question", "content": "什么是勾股定理？", "properties": {"difficulty": "easy"}}
        ],
        "edges": [
            {"source": "node_1", "target": "node_2", "type": "contains"},
            {"source": "node_1", "target": "node_3", "type": "contains"},
            {"source": "node_2", "target": "node_4", "type": "related_to"},
            {"source": "node_3", "target": "node_5", "type": "related_to"}
        ],
        "metadata": {
            "module": "wzy",
            "version": "1.0.0",
            "created_at": "2024-01-01T00:00:00Z",
            "node_count": 5,
            "edge_count": 4
        }
    }
    
    output_file = output_dir / "graph.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Graph saved to {output_file}")
    
    # 如果需要构建索引
    if args.build_index:
        print("Building retriever index...")
        
        faiss_dir = Path("data/faiss/wzy")
        bm25_dir = Path("data/bm25/wzy")
        faiss_dir.mkdir(parents=True, exist_ok=True)
        bm25_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建示例索引文件
        corpus = [
            {"id": "doc_1", "content": "一元二次方程的解法：ax²+bx+c=0"},
            {"id": "doc_2", "content": "勾股定理：a²+b²=c²"},
            {"id": "doc_3", "content": "三角函数基本公式"}
        ]
        
        # 保存 BM25 语料库
        bm25_corpus_file = bm25_dir / "corpus.jsonl"
        with open(bm25_corpus_file, 'w', encoding='utf-8') as f:
            for doc in corpus:
                f.write(json.dumps(doc, ensure_ascii=False) + "\n")
        
        # 创建 FAISS 索引占位符
        faiss_index_file = faiss_dir / "index.faiss"
        with open(faiss_index_file, 'w') as f:
            f.write("FAISS index placeholder")
        
        print(f"✓ FAISS index dir: {faiss_dir}")
        print(f"✓ BM25 index dir: {bm25_dir}")
        
        if args.embedding_backend == "hash":
            print("Using hash-based embeddings (simulated)")
        elif args.embedding_backend == "sentence-transformers":
            print(f"Using sentence-transformers: {args.embedding_model or 'default'}")

def main():
    parser = argparse.ArgumentParser(description="Build GraphRAG KB for wzy module")
    parser.add_argument("--build-index", action="store_true", help="Build retriever index")
    parser.add_argument("--embedding-backend", default="hash", 
                       choices=["hash", "sentence-transformers"],
                       help="Embedding backend to use")
    parser.add_argument("--embedding-model", default="", 
                       help="Model name for sentence-transformers")
    parser.add_argument("--limit", type=int, default=0, 
                       help="Limit number of documents (0 for no limit)")
    args = parser.parse_args()
    
    build_kb(args)

if __name__ == "__main__":
    main()
EOF

    chmod +x "${PROJECT_ROOT}/training/modules/wzy/graphrag/scripts/build_kb.py"
    
    log_ok "GraphRAG 脚本创建完成"
}

# 4. 创建嵌入索引脚本
create_embedding_scripts() {
    log_info "创建嵌入索引脚本..."
    
    cat > "${PROJECT_ROOT}/training/modules/wzy/embedding/scripts/build_index.py" << 'EOF'
#!/usr/bin/env python3
"""
wzy 模块的嵌入索引构建脚本
"""
import argparse
import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

def build_index(args):
    """构建检索索引"""
    print(f"Building embedding index for wzy module")
    print(f"Embedding backend: {args.embedding_backend}")
    print(f"Embedding model: {args.embedding_model or 'default'}")
    print(f"Limit: {args.limit if args.limit > 0 else 'No limit'}")
    
    # 创建目录
    faiss_dir = Path("data/faiss/wzy")
    bm25_dir = Path("data/bm25/wzy")
    faiss_dir.mkdir(parents=True, exist_ok=True)
    bm25_dir.mkdir(parents=True, exist_ok=True)
    
    # 模拟语料库数据
    corpus = [
        {"id": "doc_1", "content": "数学是研究数量、结构、变化以及空间等概念的学科。"},
        {"id": "doc_2", "content": "代数是用符号表示数和关系，并研究这些符号之间的运算规律。"},
        {"id": "doc_3", "content": "几何研究空间中的形状、大小、相对位置等性质。"},
        {"id": "doc_4", "content": "一元二次方程的标准形式为 ax²+bx+c=0。"},
        {"id": "doc_5", "content": "勾股定理指出，在直角三角形中，两直角边的平方和等于斜边的平方。"}
    ]
    
    if args.limit > 0:
        corpus = corpus[:args.limit]
        print(f"Limited to {len(corpus)} documents")
    
    # 保存 BM25 语料库
    bm25_corpus_file = bm25_dir / "corpus.jsonl"
    with open(bm25_corpus_file, 'w', encoding='utf-8') as f:
        for doc in corpus:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    
    # 根据嵌入后端处理
    if args.embedding_backend == "hash":
        print("Using hash-based embeddings (simulated)")
        # 创建模拟的 FAISS 索引
        faiss_index_file = faiss_dir / "index.faiss"
        with open(faiss_index_file, 'w') as f:
            f.write("Hash-based FAISS index (simulated)\n")
            f.write(f"Documents: {len(corpus)}\n")
            f.write(f"Embedding dim: 128 (simulated)\n")
        
    elif args.embedding_backend == "sentence-transformers":
        print(f"Using sentence-transformers with model: {args.embedding_model}")
        
        try:
            # 实际使用时取消注释
            # from sentence_transformers import SentenceTransformer
            # model = SentenceTransformer(args.embedding_model)
            # embeddings = model.encode([doc["content"] for doc in corpus])
            
            # 模拟嵌入
            import numpy as np
            np.random.seed(42)
            embeddings = np.random.randn(len(corpus), 384).astype('float32')
            
            # 保存嵌入
            embeddings_file = faiss_dir / "embeddings.npy"
            np.save(embeddings_file, embeddings)
            
            # 创建模拟的 FAISS 索引
            faiss_index_file = faiss_dir / "index.faiss"
            with open(faiss_index_file, 'w') as f:
                f.write(f"Sentence-transformer FAISS index (simulated)\n")
                f.write(f"Model: {args.embedding_model}\n")
                f.write(f"Documents: {len(corpus)}\n")
                f.write(f"Embedding dim: 384\n")
                
        except Exception as e:
            print(f"Warning: Could not use sentence-transformers: {e}")
            print("Falling back to hash-based embeddings")
    
    # 保存元数据
    metadata = {
        "module": "wzy",
        "embedding_backend": args.embedding_backend,
        "embedding_model": args.embedding_model or "hash",
        "document_count": len(corpus),
        "created_at": "2024-01-01T00:00:00Z"
    }
    
    metadata_file = faiss_dir / "metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"✓ FAISS index dir: {faiss_dir}")
    print(f"✓ BM25 index dir: {bm25_dir}")
    print(f"✓ Total documents indexed: {len(corpus)}")

def main():
    parser = argparse.ArgumentParser(description="Build embedding index for wzy module")
    parser.add_argument("--embedding-backend", default="hash", 
                       choices=["hash", "sentence-transformers"],
                       help="Embedding backend to use")
    parser.add_argument("--embedding-model", default="", 
                       help="Model name for sentence-transformers")
    parser.add_argument("--limit", type=int, default=0, 
                       help="Limit number of documents (0 for no limit)")
    args = parser.parse_args()
    
    build_index(args)

if __name__ == "__main__":
    main()
EOF

    chmod +x "${PROJECT_ROOT}/training/modules/wzy/embedding/scripts/build_index.py"
    
    log_ok "嵌入索引脚本创建完成"
}

# 5. 创建数据集脚本
create_dataset_scripts() {
    log_info "创建数据集脚本..."
    
    # 5.1 SFT 数据集脚本
    cat > "${PROJECT_ROOT}/training/modules/wzy/datasets/scripts/prepare_sft.py" << 'EOF'
#!/usr/bin/env python3
"""
wzy 模块的 SFT 数据集准备脚本
"""
import argparse
import json
import sys
import sqlite3
from pathlib import Path
from typing import List, Dict, Any
import random

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

def load_from_database(subjects: List[str] = None, limit: int = 0) -> List[Dict[str, Any]]:
    """从数据库加载数据（模拟）"""
    # 在实际应用中，这里应该连接真实数据库
    # 示例数据
    sample_data = [
        {
            "prompt": "解方程: 2x + 5 = 13",
            "response": "首先，将方程两边同时减去5：2x = 8。然后两边同时除以2：x = 4。所以方程的解是 x = 4。",
            "subject": "math",
            "difficulty": "easy"
        },
        {
            "prompt": "什么是勾股定理？",
            "response": "勾股定理是一个基本的几何定理，指出在直角三角形中，两条直角边的平方和等于斜边的平方。即 a² + b² = c²，其中c是斜边，a和b是直角边。",
            "subject": "math",
            "difficulty": "easy"
        },
        {
            "prompt": "如何计算圆的面积？",
            "response": "圆的面积公式是 A = πr²，其中r是圆的半径，π是圆周率（约等于3.14159）。例如，半径为5的圆的面积是 25π ≈ 78.54。",
            "subject": "math",
            "difficulty": "medium"
        },
        {
            "prompt": "解释一下微积分基本定理",
            "response": "微积分基本定理建立了微分和积分之间的联系。它有两个部分：第一部分表明，一个连续函数的不定积分是其原函数；第二部分表明，定积分可以通过求原函数在区间端点的值之差来计算。",
            "subject": "math",
            "difficulty": "hard"
        },
        {
            "prompt": "什么是线性代数中的特征值和特征向量？",
            "response": "特征值和特征向量是线性代数中的重要概念。对于一个方阵A，如果存在非零向量v和标量λ，使得 Av = λv，那么λ称为A的特征值，v称为对应的特征向量。它们反映了线性变换的性质。",
            "subject": "math",
            "difficulty": "hard"
        }
    ]
    
    # 过滤学科
    if subjects:
        filtered_data = [d for d in sample_data if d.get("subject") in subjects]
    else:
        filtered_data = sample_data
    
    # 限制数量
    if limit > 0 and limit < len(filtered_data):
        filtered_data = filtered_data[:limit]
    
    return filtered_data

def load_extra_sft_data(extra_dir: str) -> List[Dict[str, Any]]:
    """从额外目录加载 SFT 数据"""
    extra_data = []
    extra_path = Path(extra_dir)
    
    if extra_path.exists() and extra_path.is_dir():
        for jsonl_file in extra_path.glob("*.jsonl"):
            try:
                with open(jsonl_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            extra_data.append(json.loads(line))
            except Exception as e:
                print(f"Warning: Could not read {jsonl_file}: {e}")
    
    return extra_data

def prepare_sft(args):
    """准备 SFT 数据集"""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Preparing SFT datasets for wzy module")
    print(f"Output directory: {output_dir}")
    
    # 从数据库加载数据
    subjects = args.subjects.split(",") if args.subjects else []
    sft_data = load_from_database(subjects, args.limit)
    
    # 加载额外数据
    if args.extra_sft_dir:
        print(f"Loading extra SFT data from: {args.extra_sft_dir}")
        extra_data = load_extra_sft_data(args.extra_sft_dir)
        sft_data.extend(extra_data)
        print(f"Added {len(extra_data)} extra samples")
    
    print(f"Total SFT samples: {len(sft_data)}")
    
    # 按学科分组并保存
    subject_groups = {}
    for item in sft_data:
        subject = item.get("subject", "general")
        if subject not in subject_groups:
            subject_groups[subject] = []
        subject_groups[subject].append(item)
    
    for subject, items in subject_groups.items():
        subject_dir = output_dir / subject
        subject_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = subject_dir / "train.jsonl"
        with open(output_file, 'w', encoding='utf-8') as f:
            for item in items:
                # 转换为标准格式
                formatted_item = {
                    "prompt": item["prompt"],
                    "response": item["response"],
                    "metadata": {
                        "subject": item.get("subject", "general"),
                        "difficulty": item.get("difficulty", "medium"),
                        "source": item.get("source", "database")
                    }
                }
                f.write(json.dumps(formatted_item, ensure_ascii=False) + "\n")
        
        print(f"  - {subject}: {len(items)} samples -> {output_file}")
    
    # 如果需要，也保存旧格式
    if args.legacy_output:
        legacy_file = Path(args.legacy_output)
        legacy_file.parent.mkdir(parents=True, exist_ok=True)
        with open(legacy_file, 'w', encoding='utf-8') as f:
            for item in sft_data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"Legacy format saved to: {legacy_file}")
    
    # 如果需要，保存切分后的数据集
    if args.write_split_artifacts:
        split_dir = output_dir / "split_artifacts"
        split_dir.mkdir(parents=True, exist_ok=True)
        
        # 按80/20划分训练/验证集
        all_data = []
        for subject, items in subject_groups.items():
            all_data.extend(items)
        
        random.shuffle(all_data)
        split_idx = int(len(all_data) * 0.8)
        
        train_data = all_data[:split_idx]
        val_data = all_data[split_idx:]
        
        with open(split_dir / "train.jsonl", 'w', encoding='utf-8') as f:
            for item in train_data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        
        with open(split_dir / "validation.jsonl", 'w', encoding='utf-8') as f:
            for item in val_data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        
        print(f"Split artifacts saved to: {split_dir}")
        print(f"  - Train: {len(train_data)} samples")
        print(f"  - Validation: {len(val_data)} samples")

def main():
    parser = argparse.ArgumentParser(description="Prepare SFT datasets for wzy module")
    parser.add_argument("--output-dir", default="data/training/wzy/datasets/sft",
                       help="Output directory for SFT datasets")
    parser.add_argument("--legacy-output", default="",
                       help="Legacy output file path (optional)")
    parser.add_argument("--extra-sft-dir", default="",
                       help="Extra SFT data directory to merge")
    parser.add_argument("--subjects", default="",
                       help="Comma-separated list of subjects to include")
    parser.add_argument("--limit", type=int, default=0,
                       help="Limit number of samples (0 for no limit)")
    parser.add_argument("--write-split-artifacts", action="store_true",
                       help="Write train/validation split artifacts")
    args = parser.parse_args()
    
    prepare_sft(args)
    print("✓ SFT datasets prepared successfully")

if __name__ == "__main__":
    main()
EOF

    # 5.2 偏好数据集脚本
    cat > "${PROJECT_ROOT}/training/modules/wzy/datasets/scripts/prepare_preferences.py" << 'EOF'
#!/usr/bin/env python3
"""
wzy 模块的偏好数据集准备脚本（用于 DPO）
"""
import argparse
import json
import sys
import random
from pathlib import Path
from typing import List, Dict, Any

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

def load_from_database(subjects: List[str] = None, limit: int = 0) -> List[Dict[str, Any]]:
    """从数据库加载偏好数据（模拟）"""
    # 在实际应用中，这里应该连接真实数据库，查询 feedbacks 表
    # 示例数据
    sample_feedback = [
        {
            "prompt": "解方程: 3x - 7 = 8",
            "chosen": "首先，将方程两边同时加上7：3x = 15。然后两边同时除以3：x = 5。所以方程的解是 x = 5。",
            "rejected": "3x - 7 = 8，所以 3x = 8 - 7 = 1，x = 1/3。",
            "subject": "math",
            "reason": "正确的解法应该是加7而不是减7"
        },
        {
            "prompt": "什么是二次函数？",
            "chosen": "二次函数是形如 f(x) = ax² + bx + c（其中a≠0）的函数。它的图像是一个抛物线，开口方向由a的正负决定。",
            "rejected": "二次函数就是有平方的函数，比如 x²。",
            "subject": "math",
            "reason": "回答不够完整，缺少标准形式和图像特性"
        },
        {
            "prompt": "如何计算等差数列的和？",
            "chosen": "等差数列的和公式为 S_n = n/2 × (a₁ + a_n)，其中n是项数，a₁是首项，a_n是末项。或者使用 S_n = n/2 × [2a₁ + (n-1)d]，其中d是公差。",
            "rejected": "等差数列的和就是所有数加起来。",
            "subject": "math",
            "reason": "没有提供具体的计算公式"
        }
    ]
    
    # 如果是演示模式，生成更多样本
    if subjects and "demo" in subjects:
        # 生成演示数据
        demo_prompts = [
            "计算 2³",
            "什么是质数？",
            "解释一下概率的基本概念",
            "如何求函数的导数？",
            "什么是矩阵的秩？"
        ]
        
        good_responses = [
            "2³ = 2 × 2 × 2 = 8",
            "质数是大于1的自然数，除了1和它自身外，不能被其他自然数整除的数。",
            "概率是衡量事件发生可能性的数值，范围在0到1之间。0表示不可能发生，1表示必然发生。",
            "导数是函数在某一点的瞬时变化率，表示函数图像在该点的切线斜率。",
            "矩阵的秩是其行向量或列向量的最大线性无关组中向量的个数，反映了矩阵的线性独立性。"
        ]
        
        bad_responses = [
            "2³ = 6",
            "质数就是奇数。",
            "概率就是可能性，可能是0%到100%。",
            "导数就是函数的值。",
            "矩阵的秩就是矩阵的大小。"
        ]
        
        for i, prompt in enumerate(demo_prompts):
            sample_feedback.append({
                "prompt": prompt,
                "chosen": good_responses[i % len(good_responses)],
                "rejected": bad_responses[i % len(bad_responses)],
                "subject": "math",
                "reason": "演示数据"
            })
    
    # 过滤学科
    if subjects:
        filtered_data = [d for d in sample_feedback if d.get("subject") in subjects]
    else:
        filtered_data = sample_feedback
    
    # 限制数量
    if limit > 0 and limit < len(filtered_data):
        filtered_data = filtered_data[:limit]
    
    return filtered_data

def generate_demo_data(n: int = 100, seed: int = 42) -> List[Dict[str, Any]]:
    """生成演示偏好数据"""
    random.seed(seed)
    
    math_prompts = [
        "计算圆的周长公式",
        "什么是三角函数？",
        "解释一下指数函数",
        "如何解二元一次方程组？",
        "什么是微积分中的极限？",
        "解释一下向量的点积",
        "什么是复数？",
        "如何计算排列组合？",
        "解释一下正态分布",
        "什么是傅里叶变换？"
    ]
    
    good_templates = [
        "{}的正确公式是 {}",
        "{}是{}，它具有以下性质：{}",
        "{}可以通过{}方法来求解，具体步骤是：{}",
        "{}的定义是{}，它在{}中有重要应用。"
    ]
    
    bad_templates = [
        "{}就是{}",
        "我不太清楚{}",
        "{}可能是{}吧",
        "这个问题很简单，{}"
    ]
    
    demo_data = []
    for i in range(n):
        prompt = random.choice(math_prompts)
        
        # 生成好坏回答
        good_response = random.choice(good_templates).format(
            prompt.split("？")[0] if "？" in prompt else prompt,
            random.choice(["一个重要的概念", "一个数学工具", "一个基本公式"]),
            random.choice(["用于解决实际问题", "在多个领域有应用", "是数学的基础"])
        )
        
        bad_response = random.choice(bad_templates).format(
            prompt.split("？")[0] if "？" in prompt else prompt,
            random.choice(["不知道", "不确定", "可能是这样"])
        )
        
        demo_data.append({
            "prompt": prompt,
            "chosen": good_response,
            "rejected": bad_response,
            "subject": "math",
            "is_demo": True,
            "demo_id": f"demo_{i}"
        })
    
    return demo_data

def prepare_preferences(args):
    """准备偏好数据集"""
    output_dir = Path("data/training/wzy/datasets/preference")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Preparing preference datasets for wzy module")
    
    if args.demo:
        print(f"Generating {args.demo_n} demo preference samples (seed: {args.demo_seed})")
        preference_data = generate_demo_data(args.demo_n, args.demo_seed)
    else:
        # 从数据库加载
        subjects = []
        if args.subjects:
            subjects = args.subjects.split(",")
        
        preference_data = load_from_database(subjects, args.limit)
    
    print(f"Total preference samples: {len(preference_data)}")
    
    # 保存为 DPO 格式
    output_file = output_dir / "train.jsonl"
    with open(output_file, 'w', encoding='utf-8') as f:
        for item in preference_data:
            # DPO 标准格式
            dpo_item = {
                "prompt": item["prompt"],
                "chosen": item["chosen"],
                "rejected": item["rejected"]
            }
            f.write(json.dumps(dpo_item, ensure_ascii=False) + "\n")
    
    print(f"✓ Preference dataset saved to {output_file}")
    
    # 同时保存完整元数据版本
    metadata_file = output_dir / "train_with_metadata.jsonl"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        for item in preference_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    print(f"✓ Full metadata saved to {metadata_file}")

def main():
    parser = argparse.ArgumentParser(description="Prepare preference datasets for wzy module")
    parser.add_argument("--sqlite", default="data/sqlite/app.db",
                       help="SQLite database path")
    parser.add_argument("--output", default="data/training/wzy/datasets/preference/train.jsonl",
                       help="Output file path")
    parser.add_argument("--subjects", default="",
                       help="Comma-separated list of subjects")
    parser.add_argument("--limit", type=int, default=0,
                       help="Limit number of samples (0 for no limit)")
    parser.add_argument("--demo", action="store_true",
                       help="Generate demo data")
    parser.add_argument("--demo-n", type=int, default=100,
                       help="Number of demo samples to generate")
    parser.add_argument("--demo-seed", type=int, default=42,
                       help="Random seed for demo generation")
    args = parser.parse_args()
    
    prepare_preferences(args)
    print("✓ Preference datasets prepared successfully")

if __name__ == "__main__":
    main()
EOF

    chmod +x "${PROJECT_ROOT}/training/modules/wzy/datasets/scripts/prepare_sft.py"
    chmod +x "${PROJECT_ROOT}/training/modules/wzy/datasets/scripts/prepare_preferences.py"
    
    log_ok "数据集脚本创建完成"
}

# 6. 创建训练脚本
create_training_scripts() {
    log_info "创建训练脚本..."
    
    # 6.1 SFT 训练脚本
    cat > "${PROJECT_ROOT}/training/modules/wzy/fine_tuning/scripts/train_sft.py" << 'EOF'
#!/usr/bin/env python3
"""
wzy 模块的 SFT 训练脚本
"""
import argparse
import json
import sys
import os
from pathlib import Path
from typing import Dict, Any

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

def load_config(config_path: str) -> Dict[str, Any]:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def train_sft(args):
    """运行 SFT 训练"""
    print(f"Starting SFT training for wzy module")
    
    # 读取配置文件
    config_path = Path("training/modules/wzy/fine_tuning/configs/sft_qwen3_14b_lora.json")
    
    if not config_path.exists():
        log_warn("Config file not found, creating default...")
        # 创建默认配置文件
        config = {
            "model_name_or_path": "OpenPipe/Qwen3-14B-Instruct",
            "output_dir": "data/training/wzy/checkpoints/sft_lora",
            "dataset_path": "data/training/wzy/datasets/sft",
            "lora_r": 32,
            "lora_alpha": 64,
            "lora_dropout": 0.1,
            "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj"],
            "bias": "none",
            "task_type": "CAUSAL_LM",
            "num_train_epochs": 3,
            "per_device_train_batch_size": 4,
            "per_device_eval_batch_size": 4,
            "gradient_accumulation_steps": 4,
            "warmup_steps": 100,
            "learning_rate": 2e-4,
            "fp16": True,
            "logging_steps": 10,
            "save_steps": 100,
            "eval_steps": 100,
            "save_total_limit": 3,
            "report_to": "none",
            "dataloader_num_workers": 4,
            "remove_unused_columns": False,
            "optim": "adamw_torch"
        }
        
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        print(f"Default config created at {config_path}")
    
    config = load_config(config_path)
    print(f"Loaded config from {config_path}")
    
    # 根据命令行参数更新配置
    if args.subject:
        # 使用特定学科的数据集
        dataset_path = Path(config["dataset_path"]) / args.subject / "train.jsonl"
        if dataset_path.exists():
            config["dataset_path"] = str(dataset_path)
            print(f"Using subject-specific dataset: {dataset_path}")
        else:
            print(f"Warning: Subject dataset not found: {dataset_path}")
            print(f"Using default dataset: {config['dataset_path']}")
    
    # 设置输出目录
    if args.subject:
        output_dir = Path(config["output_dir"]) / args.subject
    else:
        output_dir = Path(config["output_dir"]) / "general"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    config["output_dir"] = str(output_dir)
    
    # 检查数据集
    dataset_path = Path(config["dataset_path"])
    if not dataset_path.exists():
        print(f"Error: Dataset not found: {dataset_path}")
        print("Please run datasets preparation first:")
        print("  ./deploy/scripts/pipeline.sh datasets --module wzy")
        return
    
    # 计算数据集大小
    sample_count = 0
    if dataset_path.suffix == '.jsonl':
        with open(dataset_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    sample_count += 1
    
    print(f"Dataset: {dataset_path} ({sample_count} samples)")
    print(f"Output directory: {output_dir}")
    print(f"Training configuration:")
    print(f"  - Model: {config['model_name_or_path']}")
    print(f"  - LoRA rank (r): {config['lora_r']}")
    print(f"  - LoRA alpha: {config['lora_alpha']}")
    print(f"  - Epochs: {config['num_train_epochs']}")
    print(f"  - Batch size: {config['per_device_train_batch_size']}")
    print(f"  - Learning rate: {config['learning_rate']}")
    
    # 在实际训练中，这里应该调用训练代码
    # 由于这是示例，我们只创建适配器配置
    print("\n[Simulating SFT training...]")
    
    # 创建适配器配置
    adapter_config = {
        "base_model_name_or_path": config["model_name_or_path"],
        "bias": config.get("bias", "none"),
        "fan_in_fan_out": False,
        "inference_mode": False,
        "lora_alpha": config["lora_alpha"],
        "lora_dropout": config["lora_dropout"],
        "modules_to_save": None,
        "r": config["lora_r"],
        "target_modules": config["target_modules"],
        "task_type": config["task_type"]
    }
    
    adapter_config_file = output_dir / "adapter_config.json"
    with open(adapter_config_file, 'w', encoding='utf-8') as f:
        json.dump(adapter_config, f, indent=2)
    
    # 创建训练参数文件
    training_args = {
        "num_train_epochs": config["num_train_epochs"],
        "per_device_train_batch_size": config["per_device_train_batch_size"],
        "gradient_accumulation_steps": config["gradient_accumulation_steps"],
        "learning_rate": config["learning_rate"],
        "fp16": config["fp16"],
        "dataset_size": sample_count,
        "total_steps": sample_count * config["num_train_epochs"] // 
                       (config["per_device_train_batch_size"] * config["gradient_accumulation_steps"])
    }
    
    training_args_file = output_dir / "training_args.json"
    with open(training_args_file, 'w', encoding='utf-8') as f:
        json.dump(training_args, f, indent=2)
    
    # 创建占位符检查点文件
    checkpoint_files = [
        "adapter_model.bin",
        "adapter_model.safetensors",
        "README.md",
        "special_tokens_map.json",
        "tokenizer_config.json"
    ]
    
    for filename in checkpoint_files:
        filepath = output_dir / filename
        if filename.endswith(".json"):
            content = {"note": f"Placeholder for {filename}"}
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(content, f, indent=2)
        elif filename == "README.md":
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# WZY SFT LoRA Adapter\n\n")
                f.write(f"Subject: {args.subject or 'general'}\n")
                f.write(f"Base model: {config['model_name_or_path']}\n")
                f.write(f"LoRA rank: {config['lora_r']}\n")
                f.write(f"Training samples: {sample_count}\n")
        else:
            with open(filepath, 'w') as f:
                f.write(f"Placeholder for {filename}\n")
    
    print(f"\n✓ SFT training simulation completed")
    print(f"✓ Checkpoint saved to {output_dir}")
    print(f"\nTo use this adapter with vLLM:")
    print(f"  ./deploy/scripts/pipeline.sh serve-model --module wzy up")
    print(f"  Model ID: wzy-sft-{args.subject or 'general'}")

def main():
    parser = argparse.ArgumentParser(description="Run SFT training for wzy module")
    parser.add_argument("--subject", default="", help="Subject for training (e.g., math, physics)")
    parser.add_argument("--config", default="", help="Custom config file path")
    args = parser.parse_args()
    
    train_sft(args)

if __name__ == "__main__":
    main()
EOF

    # 6.2 DPO 训练脚本
    cat > "${PROJECT_ROOT}/training/modules/wzy/fine_tuning/scripts/train_dpo.py" << 'EOF'
#!/usr/bin/env python3
"""
wzy 模块的 DPO 训练脚本
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

def load_config(config_path: str) -> Dict[str, Any]:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def train_dpo(args):
    """运行 DPO 训练"""
    print(f"Starting DPO training for wzy module")
    
    # 读取配置文件
    config_path = Path("training/modules/wzy/fine_tuning/configs/dpo_qwen3_14b_lora.json")
    
    if not config_path.exists():
        log_warn("Config file not found, creating default...")
        # 创建默认配置文件
        config = {
            "model_name_or_path": "OpenPipe/Qwen3-14B-Instruct",
            "sft_model_path": "data/training/wzy/checkpoints/sft_lora",
            "output_dir": "data/training/wzy/checkpoints/dpo_lora",
            "dataset_path": "data/training/wzy/datasets/preference/train.jsonl",
            "lora_r": 32,
            "lora_alpha": 64,
            "lora_dropout": 0.1,
            "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj"],
            "bias": "none",
            "task_type": "CAUSAL_LM",
            "num_train_epochs": 2,
            "per_device_train_batch_size": 2,
            "per_device_eval_batch_size": 2,
            "gradient_accumulation_steps": 4,
            "warmup_steps": 50,
            "learning_rate": 1e-5,
            "beta": 0.1,
            "fp16": True,
            "logging_steps": 10,
            "save_steps": 100,
            "eval_steps": 100,
            "save_total_limit": 3,
            "report_to": "none",
            "dataloader_num_workers": 4,
            "remove_unused_columns": False,
            "optim": "adamw_torch"
        }
        
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        print(f"Default config created at {config_path}")
    
    config = load_config(config_path)
    print(f"Loaded config from {config_path}")
    
    # 检查数据集
    dataset_path = Path(config["dataset_path"])
    if not dataset_path.exists():
        print(f"Error: Preference dataset not found: {dataset_path}")
        print("Please run datasets preparation first:")
        print("  ./deploy/scripts/pipeline.sh datasets --module wzy")
        print("Or generate demo data:")
        print("  ./deploy/scripts/pipeline.sh datasets --module wzy --demo --demo-n 100")
        return
    
    # 计算数据集大小
    sample_count = 0
    with open(dataset_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                sample_count += 1
    
    if sample_count == 0:
        print(f"Error: Empty preference dataset: {dataset_path}")
        return
    
    # 设置输出目录
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Dataset: {dataset_path} ({sample_count} preference pairs)")
    print(f"Output directory: {output_dir}")
    print(f"Training configuration:")
    print(f"  - Base model: {config['model_name_or_path']}")
    print(f"  - SFT model: {config.get('sft_model_path', 'None')}")
    print(f"  - LoRA rank (r): {config['lora_r']}")
    print(f"  - DPO beta: {config['beta']}")
    print(f"  - Epochs: {config['num_train_epochs']}")
    print(f"  - Batch size: {config['per_device_train_batch_size']}")
    print(f"  - Learning rate: {config['learning_rate']}")
    
    # 限制训练步数（用于冒烟测试）
    if args.max_steps > 0:
        print(f"\n[SMOKE TEST MODE] Limiting to {args.max_steps} steps")
        config["max_steps"] = args.max_steps
        config["num_train_epochs"] = 1
    
    # 在实际训练中，这里应该调用 DPO 训练代码
    # 由于这是示例，我们只创建适配器配置
    print("\n[Simulating DPO training...]")
    
    # 创建适配器配置
    adapter_config = {
        "base_model_name_or_path": config["model_name_or_path"],
        "bias": config.get("bias", "none"),
        "fan_in_fan_out": False,
        "inference_mode": False,
        "lora_alpha": config["lora_alpha"],
        "lora_dropout": config["lora_dropout"],
        "modules_to_save": None,
        "r": config["lora_r"],
        "target_modules": config["target_modules"],
        "task_type": config["task_type"],
        "dpo_beta": config["beta"]
    }
    
    adapter_config_file = output_dir / "adapter_config.json"
    with open(adapter_config_file, 'w', encoding='utf-8') as f:
        json.dump(adapter_config, f, indent=2)
    
    # 创建训练参数文件
    training_args = {
        "num_train_epochs": config["num_train_epochs"],
        "per_device_train_batch_size": config["per_device_train_batch_size"],
        "gradient_accumulation_steps": config["gradient_accumulation_steps"],
        "learning_rate": config["learning_rate"],
        "beta": config["beta"],
        "fp16": config["fp16"],
        "dataset_size": sample_count,
        "total_steps": sample_count * config["num_train_epochs"] // 
                       (config["per_device_train_batch_size"] * config["gradient_accumulation_steps"])
    }
    
    if args.max_steps > 0:
        training_args["max_steps"] = args.max_steps
    
    training_args_file = output_dir / "training_args.json"
    with open(training_args_file, 'w', encoding='utf-8') as f:
        json.dump(training_args, f, indent=2)
    
    # 创建占位符检查点文件
    checkpoint_files = [
        "adapter_model.bin",
        "adapter_model.safetensors",
        "README.md",
        "special_tokens_map.json",
        "tokenizer_config.json"
    ]
    
    for filename in checkpoint_files:
        filepath = output_dir / filename
        if filename.endswith(".json"):
            content = {"note": f"Placeholder for {filename}"}
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(content, f, indent=2)
        elif filename == "README.md":
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# WZY DPO LoRA Adapter\n\n")
                f.write(f"Base model: {config['model_name_or_path']}\n")
                f.write(f"LoRA rank: {config['lora_r']}\n")
                f.write(f"DPO beta: {config['beta']}\n")
                f.write(f"Preference pairs: {sample_count}\n")
        else:
            with open(filepath, 'w') as f:
                f.write(f"Placeholder for {filename}\n")
    
    print(f"\n✓ DPO training simulation completed")
    print(f"✓ Checkpoint saved to {output_dir}")
    print(f"\nTo use this adapter with vLLM:")
    print(f"  ./deploy/scripts/pipeline.sh serve-model --module wzy up")
    print(f"  Model ID: wzy-dpo")

def main():
    parser = argparse.ArgumentParser(description="Run DPO training for wzy module")
    parser.add_argument("--max-steps", type=int, default=-1, 
                       help="Maximum training steps (for smoke test)")
    parser.add_argument("--config", default="", help="Custom config file path")
    args = parser.parse_args()
    
    train_dpo(args)

if __name__ == "__main__":
    main()
EOF

    chmod +x "${PROJECT_ROOT}/training/modules/wzy/fine_tuning/scripts/train_sft.py"
    chmod +x "${PROJECT_ROOT}/training/modules/wzy/fine_tuning/scripts/train_dpo.py"
    
    log_ok "训练脚本创建完成"
}

# 7. 创建评估脚本
create_eval_script() {
    log_info "创建评估脚本..."
    
    cat > "${PROJECT_ROOT}/training/modules/wzy/eval/run_model_eval.py" << 'EOF'
#!/usr/bin/env python3
"""
wzy 模块的模型评估脚本
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Dict, Any
import random

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

def load_eval_dataset() -> List[Dict[str, Any]]:
    """加载评估数据集"""
    eval_file = Path("data/training/wzy/eval/model_eval.jsonl")
    
    if not eval_file.exists():
        # 创建示例评估数据
        eval_data = [
            {
                "prompt": "计算 2³ 的值",
                "reference": "8",
                "type": "math",
                "difficulty": "easy",
                "explanation": "2³ = 2 × 2 × 2 = 8"
            },
            {
                "prompt": "什么是质数？请举例说明",
                "reference": "质数是大于1的自然数，除了1和它自身外，不能被其他自然数整除的数。例如：2, 3, 5, 7, 11等。",
                "type": "math",
                "difficulty": "easy",
                "explanation": "质数只有两个正因数：1和它本身"
            },
            {
                "prompt": "如何计算圆的面积？",
                "reference": "圆的面积公式是 A = πr²，其中r是圆的半径，π是圆周率（约等于3.14159）。",
                "type": "math",
                "difficulty": "medium",
                "explanation": "面积与半径的平方成正比"
            },
            {
                "prompt": "解释一下勾股定理",
                "reference": "勾股定理指出，在直角三角形中，两条直角边的平方和等于斜边的平方。即 a² + b² = c²，其中c是斜边，a和b是直角边。",
                "type": "math",
                "difficulty": "medium",
                "explanation": "直角三角形的基本定理"
            },
            {
                "prompt": "什么是微积分基本定理？",
                "reference": "微积分基本定理建立了微分和积分之间的联系。它有两个部分：第一部分表明，一个连续函数的不定积分是其原函数；第二部分表明，定积分可以通过求原函数在区间端点的值之差来计算。",
                "type": "math",
                "difficulty": "hard",
                "explanation": "连接微分和积分的桥梁"
            },
            {
                "prompt": "解方程: 3x - 7 = 8",
                "reference": "首先，将方程两边同时加上7：3x = 15。然后两边同时除以3：x = 5。所以方程的解是 x = 5。",
                "type": "math",
                "difficulty": "easy",
                "explanation": "线性方程求解"
            },
            {
                "prompt": "什么是二次函数？它的图像有什么特点？",
                "reference": "二次函数是形如 f(x) = ax² + bx + c（其中a≠0）的函数。它的图像是一个抛物线，开口方向由a的正负决定：当a>0时开口向上，当a<0时开口向下。顶点坐标为 (-b/2a, f(-b/2a))。",
                "type": "math",
                "difficulty": "medium",
                "explanation": "抛物线的基本性质"
            },
            {
                "prompt": "如何计算等差数列的和？",
                "reference": "等差数列的和公式为 S_n = n/2 × (a₁ + a_n)，其中n是项数，a₁是首项，a_n是末项。或者使用 S_n = n/2 × [2a₁ + (n-1)d]，其中d是公差。",
                "type": "math",
                "difficulty": "medium",
                "explanation": "等差数列求和公式"
            },
            {
                "prompt": "解释一下概率的基本概念",
                "reference": "概率是衡量事件发生可能性的数值，范围在0到1之间。0表示不可能发生，1表示必然发生。基本概率公式：P(A) = 事件A发生的次数 / 所有可能结果的次数。",
                "type": "math",
                "difficulty": "medium",
                "explanation": "概率的定义和计算"
            },
            {
                "prompt": "什么是矩阵的秩？它有什么意义？",
                "reference": "矩阵的秩是其行向量或列向量的最大线性无关组中向量的个数。它反映了矩阵的线性独立性和方程组的解的情况。满秩矩阵可逆，秩小于列数时方程组有无穷多解。",
                "type": "math",
                "difficulty": "hard",
                "explanation": "矩阵秩的定义和应用"
            }
        ]
        
        eval_file.parent.mkdir(parents=True, exist_ok=True)
        with open(eval_file, 'w', encoding='utf-8') as f:
            for item in eval_data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        
        print(f"Created evaluation dataset: {eval_file}")
        return eval_data
    
    else:
        eval_data = []
        with open(eval_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    eval_data.append(json.loads(line))
        
        return eval_data

def call_model_api(prompt: str, model_endpoint: str = "http://127.0.0.1:8004/v1") -> str:
    """调用模型 API（模拟）"""
    # 在实际应用中，这里应该调用真实的 OpenAI 兼容 API
    # 示例：使用 requests 库调用 /v1/chat/completions
    
    print(f"  Calling model API for prompt: {prompt[:50]}...")
    
    # 模拟延迟
    time.sleep(0.1)
    
    # 生成模拟响应
    responses = [
        f"这是对'{prompt[:20]}...'的模拟回答。在实际评估中，这里应该是真实的模型输出。",
        f"根据我的知识，{prompt[:30]}...的答案是模拟数据。",
        f"这个问题可以这样回答：这是一个模拟的响应，用于测试评估流程。",
        f"好的，我来回答这个问题。不过请注意，这是评估模式下的模拟回答。"
    ]
    
    return random.choice(responses)

def calculate_char_f1(prediction: str, reference: str) -> float:
    """计算字符级 F1 分数（模拟）"""
    # 在实际应用中，这里应该实现真正的 F1 计算
    # 这里使用简单的重叠比例作为模拟
    
    pred_chars = set(prediction.lower())
    ref_chars = set(reference.lower())
    
    if not pred_chars or not ref_chars:
        return 0.0
    
    intersection = pred_chars.intersection(ref_chars)
    
    if not intersection:
        return 0.0
    
    precision = len(intersection) / len(pred_chars)
    recall = len(intersection) / len(ref_chars)
    
    if precision + recall == 0:
        return 0.0
    
    f1 = 2 * precision * recall / (precision + recall)
    return round(f1, 4)

def check_mcq_accuracy(prediction: str, gold: str) -> bool:
    """检查多选题准确率（模拟）"""
    # 在实际应用中，这里应该解析预测和标准答案
    # 这里使用简单的字符串包含检查
    
    if not gold or gold.lower() == "none":
        return False
    
    # 简单模拟：如果预测包含黄金答案的部分内容，认为正确
    gold_keywords = gold.lower().split()
    pred_lower = prediction.lower()
    
    matches = sum(1 for kw in gold_keywords if kw in pred_lower)
    accuracy = matches / len(gold_keywords) if gold_keywords else 0
    
    return accuracy > 0.5

def run_evaluation(args):
    """运行模型评估"""
    print(f"Running model evaluation for wzy module")
    
    # 加载评估数据集
    eval_data = load_eval_dataset()
    
    if args.limit > 0 and args.limit < len(eval_data):
        eval_data = eval_data[:args.limit]
        print(f"Limiting evaluation to {len(eval_data)} samples")
    
    print(f"Evaluation samples: {len(eval_data)}")
    
    results = []
    total_f1 = 0
    total_mcq_accuracy = 0
    mcq_count = 0
    latencies = []
    
    # 逐条评估
    for i, item in enumerate(eval_data, 1):
        print(f"\n[{i}/{len(eval_data)}] Evaluating: {item['prompt'][:60]}...")
        
        # 调用模型
        start_time = time.time()
        prediction = call_model_api(item["prompt"], args.endpoint)
        latency = time.time() - start_time
        latencies.append(latency)
        
        # 计算指标
        f1_score = 0.0
        mcq_correct = False
        
        if "reference" in item:
            f1_score = calculate_char_f1(prediction, item["reference"])
            total_f1 += f1_score
        
        if item.get("type") == "mcq" and "gold" in item:
            mcq_correct = check_mcq_accuracy(prediction, item["gold"])
            total_mcq_accuracy += 1 if mcq_correct else 0
            mcq_count += 1
        
        # 保存结果
        result = {
            "index": i,
            "prompt": item["prompt"],
            "prediction": prediction,
            "reference": item.get("reference", ""),
            "char_f1": f1_score,
            "mcq_correct": mcq_correct if item.get("type") == "mcq" else None,
            "latency_ms": round(latency * 1000, 2),
            "difficulty": item.get("difficulty", "unknown"),
            "type": item.get("type", "qa")
        }
        
        results.append(result)
        
        print(f"  Char-F1: {f1_score:.4f}, Latency: {latency*1000:.2f}ms")
    
    # 计算总体指标
    avg_f1 = total_f1 / len(eval_data) if eval_data else 0
    avg_mcq_accuracy = total_mcq_accuracy / mcq_count if mcq_count > 0 else 0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    
    # 按难度分组统计
    difficulty_stats = {}
    for result in results:
        difficulty = result["difficulty"]
        if difficulty not in difficulty_stats:
            difficulty_stats[difficulty] = {"count": 0, "total_f1": 0, "samples": []}
        
        stats = difficulty_stats[difficulty]
        stats["count"] += 1
        stats["total_f1"] += result["char_f1"]
        stats["samples"].append(result["char_f1"])
    
    for difficulty, stats in difficulty_stats.items():
        stats["avg_f1"] = stats["total_f1"] / stats["count"] if stats["count"] > 0 else 0
    
    # 创建评估报告
    report = {
        "module": "wzy",
        "eval_type": "model_quality",
        "endpoint": args.endpoint,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": {
            "char_f1": round(avg_f1, 4),
            "mcq_accuracy": round(avg_mcq_accuracy, 4),
            "samples_evaluated": len(eval_data),
            "mcq_samples": mcq_count,
            "latency_ms": {
                "avg": round(avg_latency * 1000, 2),
                "min": round(min_latency * 1000, 2),
                "max": round(max_latency * 1000, 2)
            }
        },
        "difficulty_stats": difficulty_stats,
        "sample_results": results[:10]  # 只保存前10个样本的详细结果
    }
    
    # 保存评估报告
    report_file = Path("data/training/wzy/eval/model_eval_report.json")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"EVALUATION REPORT")
    print(f"{'='*60}")
    print(f"Module: wzy")
    print(f"Samples evaluated: {len(eval_data)}")
    print(f"Average Char-F1: {avg_f1:.4f}")
    if mcq_count > 0:
        print(f"MCQ Accuracy: {avg_mcq_accuracy:.4f} ({mcq_count} samples)")
    print(f"Latency: {avg_latency*1000:.2f}ms (min: {min_latency*1000:.2f}ms, max: {max_latency*1000:.2f}ms)")
    
    print(f"\nDifficulty breakdown:")
    for difficulty, stats in difficulty_stats.items():
        print(f"  {difficulty}: {stats['count']} samples, avg F1: {stats['avg_f1']:.4f}")
    
    print(f"\n✓ Evaluation report saved to {report_file}")
    print(f"\nNote: This is a simulated evaluation. To perform real evaluation,")
    print(f"ensure the model server is running and implement actual API calls.")
    print(f"Model endpoint: {args.endpoint}")

def main():
    parser = argparse.ArgumentParser(description="Run model evaluation for wzy module")
    parser.add_argument("--module", required=True, help="Module name")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8004/v1",
                       help="Model API endpoint")
    parser.add_argument("--limit", type=int, default=0,
                       help="Limit number of evaluation samples")
    parser.add_argument("--output", default="data/training/wzy/eval/model_eval_report.json",
                       help="Output report file path")
    args = parser.parse_args()
    
    run_evaluation(args)

if __name__ == "__main__":
    main()
EOF

    chmod +x "${PROJECT_ROOT}/training/modules/wzy/eval/run_model_eval.py"
    
    log_ok "评估脚本创建完成"
}

# 8. 创建配置文件
create_config_files() {
    log_info "创建配置文件..."
    
    # 8.1 SFT 配置文件
    cat > "${PROJECT_ROOT}/training/modules/wzy/fine_tuning/configs/sft_qwen3_14b_lora.json" << 'EOF'
{
  "model_name_or_path": "OpenPipe/Qwen3-14B-Instruct",
  "output_dir": "data/training/wzy/checkpoints/sft_lora",
  "dataset_path": "data/training/wzy/datasets/sft",
  "lora_r": 32,
  "lora_alpha": 64,
  "lora_dropout": 0.1,
  "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj"],
  "bias": "none",
  "task_type": "CAUSAL_LM",
  "num_train_epochs": 3,
  "per_device_train_batch_size": 4,
  "per_device_eval_batch_size": 4,
  "gradient_accumulation_steps": 4,
  "warmup_steps": 100,
  "learning_rate": 2e-4,
  "fp16": true,
  "logging_steps": 10,
  "save_steps": 100,
  "eval_steps": 100,
  "save_total_limit": 3,
  "report_to": "none",
  "dataloader_num_workers": 4,
  "remove_unused_columns": false,
  "optim": "adamw_torch"
}
EOF

    # 8.2 DPO 配置文件
    cat > "${PROJECT_ROOT}/training/modules/wzy/fine_tuning/configs/dpo_qwen3_14b_lora.json" << 'EOF'
{
  "model_name_or_path": "OpenPipe/Qwen3-14B-Instruct",
  "sft_model_path": "data/training/wzy/checkpoints/sft_lora",
  "output_dir": "data/training/wzy/checkpoints/dpo_lora",
  "dataset_path": "data/training/wzy/datasets/preference/train.jsonl",
  "lora_r": 32,
  "lora_alpha": 64,
  "lora_dropout": 0.1,
  "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj"],
  "bias": "none",
  "task_type": "CAUSAL_LM",
  "num_train_epochs": 2,
  "per_device_train_batch_size": 2,
  "per_device_eval_batch_size": 2,
  "gradient_accumulation_steps": 4,
  "warmup_steps": 50,
  "learning_rate": 1e-5,
  "beta": 0.1,
  "fp16": true,
  "logging_steps": 10,
  "save_steps": 100,
  "eval_steps": 100,
  "save_total_limit": 3,
  "report_to": "none",
  "dataloader_num_workers": 4,
  "remove_unused_columns": false,
  "optim": "adamw_torch"
}
EOF

    # 8.3 Docker Compose 配置文件
    cat > "${PROJECT_ROOT}/training/modules/wzy/serving/docker-compose.vllm.yml" << 'EOF'
version: '3.8'

services:
  vllm-wzy:
    image: vllm/vllm-openai:latest
    container_name: vllm-wzy
    ports:
      - "8004:8000"
    environment:
      - MODEL=OpenPipe/Qwen3-14B-Instruct
      - HUGGING_FACE_HUB_TOKEN=${HUGGING_FACE_HUB_TOKEN:-}
      - HF_HOME=/root/.cache/huggingface
      - HF_HUB_CACHE=/root/.cache/huggingface/hub
    volumes:
      - /home/dataset-assist-0/data/work/.cache/huggingface:/root/.cache/huggingface
      - ./data/training/wzy/checkpoints:/checkpoints
    command: >
      --model ${MODEL}
      --served-model-name wzy-qwen3-14b
      --port 8000
      --max-model-len 8192
      --gpu-memory-utilization 0.9
      --enable-lora
      --lora-modules wzy-dpo=/checkpoints/dpo_lora,wzy-sft-math=/checkpoints/sft_lora/math
      --max-loras 4
      --max-lora-rank 64
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
    networks:
      - wzy-network

networks:
  wzy-network:
    name: wzy-network
EOF

    log_ok "配置文件创建完成"
}

# 9. 创建测试脚本
create_test_script() {
    log_info "创建测试脚本..."
    
    cat > "${PROJECT_ROOT}/test_wzy_module.sh" << 'EOF'
#!/bin/bash
# =============================================================================
# WZY 模块测试脚本
# 功能：测试 wzy 模块的所有流水线命令
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { printf "${BLUE}[INFO]${NC} %s\n" "$1"; }
log_ok() { printf "${GREEN}[OK]${NC} %s\n" "$1"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
log_err() { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 测试步骤
test_step() {
    local step_num=$1
    local step_name=$2
    local command=$3
    
    log_info "步骤 ${step_num}: ${step_name}"
    echo "命令: ${command}"
    echo ""
    
    if eval "$command"; then
        log_ok "步骤 ${step_num} 成功"
        echo ""
        return 0
    else
        log_err "步骤 ${step_num} 失败"
        return 1
    fi
}

main() {
    log_info "开始测试 WZY 模块"
    echo "=========================================="
    
    # 步骤 1: 构建知识库
    test_step 1 "构建 GraphRAG 知识库" \
        "./deploy/scripts/pipeline.sh kb --module wzy --build-index --embedding-backend hash --limit 10"
    
    # 步骤 2: 构建嵌入索引
    test_step 2 "构建嵌入索引" \
        "./deploy/scripts/pipeline.sh embed-index --module wzy --embedding-backend hash --limit 10"
    
    # 步骤 3: 准备数据集
    test_step 3 "准备数据集" \
        "./deploy/scripts/pipeline.sh datasets --module wzy --demo --demo-n 20"
    
    # 步骤 4: SFT 训练
    test_step 4 "SFT 训练（冒烟测试）" \
        "./deploy/scripts/pipeline.sh train-sft --module wzy --subject math"
    
    # 步骤 5: DPO 训练
    test_step 5 "DPO 训练（冒烟测试）" \
        "./deploy/scripts/pipeline.sh train-dpo --module wzy --max-steps 1"
    
    # 步骤 6: 启动模型服务
    test_step 6 "启动模型服务" \
        "./deploy/scripts/pipeline.sh serve-model --module wzy up"
    
    # 等待服务启动
    log_info "等待模型服务启动..."
    sleep 5
    
    # 步骤 7: 检查服务状态
    test_step 7 "检查服务状态" \
        "./deploy/scripts/pipeline.sh serve-model --module wzy status"
    
    # 步骤 8: 模型评估
    test_step 8 "模型评估" \
        "./deploy/scripts/pipeline.sh eval-model --module wzy"
    
    # 步骤 9: 停止模型服务
    test_step 9 "停止模型服务" \
        "./deploy/scripts/pipeline.sh serve-model --module wzy down"
    
    log_ok "所有测试步骤完成！"
    echo ""
    log_info "WZY 模块测试总结："
    echo "1. 知识库构建 ✓"
    echo "2. 嵌入索引构建 ✓"
    echo "3. 数据集准备 ✓"
    echo "4. SFT 训练 ✓"
    echo "5. DPO 训练 ✓"
    echo "6. 模型服务启动/停止 ✓"
    echo "7. 模型评估 ✓"
    echo ""
    log_info "下一步："
    echo "- 查看详细日志：./deploy/scripts/pipeline.sh serve-model --module wzy logs"
    echo "- 使用真实数据训练：修改 scripts 中的数据加载逻辑"
    echo "- 配置后端集成：设置 PERSONAL_MODEL_ENABLED_WZY 环境变量"
    echo "- 验证完整流程：启动后端服务并测试 API"
}

main "$@"
EOF

    chmod +x "${PROJECT_ROOT}/test_wzy_module.sh"
    
    log_ok "测试脚本创建完成"
}

# 10. 创建 README 文件
create_readme() {
    log_info "创建 README 文件..."
    
    cat > "${PROJECT_ROOT}/training/modules/wzy/README.md" << 'EOF'
# WZY 模块

## 概述
WZY 模块是教育 AI 助手系统的一个组件，专注于数学学科的教学和问答。本模块包含完整的训练和服务流水线。

## 目录结构