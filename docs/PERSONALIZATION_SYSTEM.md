## 个性化系统实现细节（Tony-first）

本文件聚焦“个性化（小书童）”的**工程实现**：个人微调模型（vLLM + LoRA）、检索（向量库/Hybrid/GraphRAG/MCP）、以及业务端到端闭环与日志可观测性。

### 1) 个人模型（用户自己训练/微调后的模型）

- **服务化**：`./deploy/scripts/pipeline.sh serve-model --module tony up`
  - base model：从 HuggingFace Hub cache 加载（见 `pipeline.sh` 的 HF_HUB_CACHE）
  - LoRA 产物：自动从 `data/training/<module>/checkpoints/` 下发现并以模型 id 暴露
    - `data/training/tony/checkpoints/dpo_lora/` → `tony-dpo`
    - `data/training/tony/checkpoints/sft_lora/<subject>/` → `tony-sft-<subject>`

验证（注意绕过代理）：

```bash
export NO_PROXY=127.0.0.1,localhost
curl --noproxy '*' http://127.0.0.1:8001/v1/models
```

### 2) 后端如何调用个人模型（OpenAI-compatible）

封装位置：`backend/core/services/personal_model_service.py`

- **按模块读取配置**（支持 `PERSONAL_MODEL_*_<MODULE>` 覆盖）：`backend/core/base_config.py`
- **调用接口**：`PersonalModelService.chat(...)`
  - `base_url`：`PERSONAL_MODEL_API_BASE_<MODULE>`（例如 `http://127.0.0.1:8001/v1`）
  - `model`：`PERSONAL_MODEL_MODEL_<MODULE>`（例如 `tony-dpo`）

### 3) 业务闭环（Tony）

#### 3.1 小书童对话（前端 /companion）

- 前端：`frontend/src/pages/Companion.jsx` → `frontend/src/lib/api.js` 的 `companionApi`
- default 模块代理：`backend/modules/default/api/endpoints/companion.py`
- tony 实现：`backend/modules/tony/api/endpoints/companion/chat.py`
  - 构建学生画像（弱项/知识点）
  - 检索：Hybrid（FAISS+BM25）+ embedding + 可选 GraphRAG 扩展
  - 调用个人模型：`PersonalModelService.chat(...)`
  - 存储会话：`CompanionConversation` / `CompanionMessage`

#### 3.2 学习计划（learning-plan）

- 入口：`backend/modules/tony/api/endpoints/learning/guidance.py` 的 `GET /learning-plan`
- 数据：DB 的复习候选 + 可选 GraphRAG 扩展
- 生成：个人模型优先（enabled 时），否则 fallback 到共享 LLM

#### 3.3 举一反三（similar-questions）

- 入口：`POST /api/v1/learning/similar-questions`（同上文件）
- 检索：`backend/modules/tony/agents/learning/similar_question_agent.py`
  - 优先 MCP retrieval（`MCP_RETRIEVAL_ENABLED=true`）
  - 否则本地向量库 fallback
  - GraphRAG 可选（`GRAPHRAG_ENABLED=true`）
- 生成：个人模型优先（enabled 时）

### 4) Trace 落盘日志（默认开启，可关闭）

需求：每次后端调用个人模型时，把 **prompt / retrieval / output** 全量落盘到 `./logs/trace_*.jsonl`，便于审计与调试。

实现位置：`backend/core/services/personal_model_service.py`

- 默认写入：`./logs/trace_personal_model_<module>.jsonl`
- 开关（默认开启）：

```bash
export PERSONAL_MODEL_TRACE_ENABLED=false   # 关闭落盘
```

- 指定路径：

```bash
export PERSONAL_MODEL_TRACE_PATH=./logs/trace_personal_model.jsonl
```

- 采样（降低日志量）：

```bash
export PERSONAL_MODEL_TRACE_SAMPLE_RATE=0.1
```

- 同时打印更详细的 stdout 日志（截断预览）：

```bash
export PERSONAL_MODEL_LOG_VERBOSE=true
```

### 5) 隐私与日志爆炸注意事项

- Trace 默认会包含**用户输入、检索内容、模型输出**，请仅用于教学/调试环境。
- 若用于生产，建议：
  - 关闭 trace 或改为抽样
  - 对敏感字段做脱敏/加密
  - 配合日志轮转与保留策略

