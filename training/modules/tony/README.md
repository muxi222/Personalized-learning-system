## Tony 学科（历史/地理/其他）训练与 GraphRAG（完整实现）

本目录把 `training/` 按模块拆分为：`tony / rpj / wzy / wzm / xmx`，并 **优先完成 tony 的全链路**：

- **GraphRAG 知识库**（结构化图 + 混合检索 FAISS+BM25）
- **数据集构建**（SFT + 人工偏好/AI偏好入口）
- **微调**（LoRA/QLoRA SFT + DPO 入口）
- **部署**（vLLM OpenAI-compatible + K8s 清单）

### 1) GraphRAG 知识库（构建）

构建图谱 +（可选）构建检索索引：

```bash
python training/modules/tony/graphrag/scripts/build_kb.py --build-index
```

产物：
- `data/training/tony/graphrag/graph.json`
- `data/faiss/tony/*` + `data/bm25/tony/*`

### 2) 训练数据（整理）

SFT（从 DB 结构化字段生成 instruction/input/output）：

```bash
python training/modules/tony/datasets/scripts/prepare_sft.py
```

偏好数据（从 `feedbacks` 表生成 chosen/rejected，用于 DPO/ORPO）：

```bash
python training/modules/tony/datasets/scripts/prepare_preferences.py
```

### 3) 微调（LoRA/QLoRA）

SFT：

```bash
python training/modules/tony/fine_tuning/scripts/train_sft.py
```

DPO（偏好优化）：

```bash
python training/modules/tony/fine_tuning/scripts/train_dpo.py
```

> 说明：Qwen3-70B 需要大显存/多卡；本仓库提供的脚本/配置是“工业可迁移”的。
> 在本机/小资源环境请先把 `model_name` 改成 7B/14B 做烟测。

### 4) 部署（推理服务）

见 `training/modules/tony/serving/README.md`。

### 5) 与后端功能对接（learning/review）

下一步会在后端增加一个 **feature-gated** 的 GraphRAG 检索服务（默认不影响现有功能），让 tony 的：
- `learning`（举一反三 / 学习建议）
- `review`（复习题单 / 复习计划）

可以在原有 RAG 基础上进一步使用：图谱扩展、知识点聚合、用户画像偏好加权。

后端启用建议（示例环境变量）：

```bash
# 启用 GraphRAG（读取 data/training/tony/graphrag/graph.json）
export GRAPHRAG_ENABLED=true

# 如果你用 vLLM 部署了微调模型，并希望后端的学习计划/点评走该模型：
export DEFAULT_LLM_PROVIDER=openai
export OPENAI_API_KEY=EMPTY
export OPENAI_API_BASE=http://localhost:8001/v1
export OPENAI_MODEL=tony-qwen3-14b
```

