## 错题识别系统（Intake / 录入错题）— 实现细节参考（Tony-first）

> 本文档描述“录入错题（intake）”链路：它与 `docs/AI_CORRECTION_SYSTEM.md` 的 **AI 批改/试卷批注**链路不同。
>
> - **ai_correction**：试卷上传 → AI 批改 → 批改历史（ExamCorrection）→ 自动把错题入库
> - **intake**：用户在前端“录入错题”页面直接提交（文字/图片）→ 识别/结构化 → 入库为 Question

---

### 0. 逐节严审（Repo Reality Audit）

本节用于把本文的 **每一条 API、路径、表字段、文件命名规则** 与代码逐条对照，并标注状态：

- **已验证**：与代码实现一致（附代码位置）
- **待补充**：文档缺失关键约束/字段/行为（需要补文档）
- **待修正**：文档与代码不一致（要么改文档，要么改代码；本文先以“真实代码”为准）

**严审结论摘要（高优先级）**：
- **已验证**：入口 `POST /api/v1/questions/ocr` 同时支持 `input_type=image|text`，两者都异步走 `QuestionIntakeOCRAgent.process(...)`。实现：`backend/modules/tony/api/endpoints/intake/questions.py`
- **已验证**：图片落盘目录：`data/uploads/<username_email>/questions/<subject>/...`。实现：`backend/core/utils/file_utils.py`（`get_user_upload_dir`）
- **已验证**：录入错题图片“每次上传都生成新的 ImageFile 记录”（不去重），通过对 hash 做 task_id 级别盐化规避唯一约束。实现：`backend/modules/tony/api/endpoints/intake/questions.py`
- **待补充（重要）**：`ImageFile.file_path` 在 intake 链路中目前写入的是**绝对路径**；而 ai_correction 链路会标准化为 `data/uploads/...` 的相对路径。两者虽都能被 default 的图片服务解析，但建议后续统一存储策略以降低运维复杂度。
- **待修正（重要）**：intake 链路目前会把 `Question.image_urls` 写成 `image_path`（本地文件路径），这不适合作为前端可直接访问的 URL。当前应优先使用 `Question.source_image_id` 并通过 `GET /api/v1/image-files/{image_id}/content` 访问图片（default 模块已提供）。

**逐条核对清单（本文涉及的“规则项”）**：

| 规则项 | 状态 | Repo Reality（代码位置） |
|---|---|---|
| `POST /api/v1/questions/` | 已验证 | `backend/modules/tony/api/endpoints/intake/questions.py` |
| `POST /api/v1/questions/ocr` | 已验证 | 同上 |
| `GET /api/v1/tasks/{task_id}` | 已验证（Tony） | `backend/modules/tony/api/endpoints/shared/tasks.py`（路由：`backend/modules/tony/api/router.py`） |
| 落盘目录：`data/uploads/<user>/questions/<subject>/...` | 已验证 | `backend/core/utils/file_utils.py`（`get_user_upload_dir`） |
| 文件命名：`{task_id_no_dash[:16]}_{file_hash_raw[:16]}.{ext}` | 已验证 | `backend/modules/tony/api/endpoints/intake/questions.py` |
| 图片访问：`GET /api/v1/image-files/{image_id}/content` | 已验证 | `backend/modules/default/api/endpoints/image_files.py` |

### 1. 入口与 API（Tony）

路由聚合：`backend/modules/tony/api/router.py`（关键前缀）
- `include_router(questions.router, prefix="/questions")`

因此错题录入相关 API（Tony 模块）为：

#### 1.1 文本录入（异步任务）

- `POST /api/v1/questions/`
  - 说明：提交文字错题，返回 `task_id`（202），后台异步处理并创建 Question
  - 实现：`backend/modules/tony/api/endpoints/intake/questions.py`

#### 1.2 图片录入（OCR/结构化，异步任务）

- `POST /api/v1/questions/ocr`
  - `input_type=image`：上传图片 + OCR/结构化 → 入库
  - `input_type=text`：提交文本（要求为 JSON 字符串）→ 大模型结构化 → 入库
  - 实现：同上文件（`questions.py`）

任务状态查询（通用）：
- `GET /api/v1/tasks/{task_id}`

---

### 2. 核心流程（概览）

#### 2.1 图片录入（input_type=image）

```
前端上传错题图片
  → 保存到 data/uploads/<user>/questions/<subject>/
  → 写入 ImageFile（用于权限校验/统一访问；本链路按产品要求“不去重”，每次上传都会生成新的记录）
  → 创建 task（AgentTask）
  → QuestionIntakeOCRAgent.process(type=image)
    → OCR/理解（多模态/LLM）
    → 抽取结构化字段：题干/答案/错因/知识点/章节/标签
    → 写入 Question（source=manual；当前 `QuestionSourceEnum` 仅有 manual/ai_correction）
    → （待补充）索引更新：当前实现未在 intake 完成后自动触发 FAISS/BM25 更新；需要通过离线 pipeline 构建/更新索引
  → task 标记完成并返回 question_id
```

#### 2.2 文本录入（input_type=text 或 POST /questions）

```
前端提交文本（可含学生答案/提示）
  → 创建 task
  → QuestionIntakeOCRAgent.process(type=text)
    → LLM 结构化
    → 写入 Question
    → （待补充）索引更新：当前实现未在 intake 完成后自动触发 FAISS/BM25 更新；需要通过离线 pipeline 构建/更新索引
```

**状态**：已验证。实现：`backend/modules/tony/api/endpoints/intake/questions.py`（`/questions/ocr` 内部根据 `input_type` 分支，统一调用 `QuestionIntakeOCRAgent.process(...)`）

---

### 3. 落盘路径与文件管理（与 AI 批改区分）

录入错题的图片落盘在 **questions** 目录（与试卷批改的 corrections 目录区分）：

- `data/uploads/<username_email>/questions/<subject>/...`

实现参考：
- `backend/modules/tony/api/endpoints/intake/questions.py`
  - 使用 `get_user_upload_dir(UPLOAD_DIR, user, "questions", subject_en)` 生成用户隔离目录

**状态**：已验证。实现：`backend/core/utils/file_utils.py`（`get_user_upload_dir`）

**文件命名规则（当前实现）**：
- 图片文件名：`{task_id_no_dash[:16]}_{file_hash_raw[:16]}.{ext}`
  - 目的：同一张图片重复上传也会生成不同文件名，避免物理文件共享导致删除互相影响
  - 实现：`backend/modules/tony/api/endpoints/intake/questions.py`

统一图片访问：
- default 模块提供 `ImageFile` 访问接口（见 `docs/AI_CORRECTION_SYSTEM.md` 的图片访问规范与 `backend/modules/default/api/endpoints/image_files.py`）

**状态**：已验证。实现：`backend/modules/default/api/endpoints/image_files.py`（`GET /api/v1/image-files/{image_id}/content`）

---

### 4. 关键数据表与字段（概念级）

录入错题最终落到：
- `Question`：错题实体（题干/答案/错因/知识点/标签/图片引用等）
- `ImageFile`：图片元数据（file_path、user_id、hash、引用关系）
- `AgentTask`：异步任务状态（用于前端轮询）

特别说明：
- **AI 批改入库** 的错题会带 `exam_correction_id` 且 `source=ai_correction`
- **录入错题（intake）** 的错题一般不带 `exam_correction_id`，当前实现写入 `source=manual`，并用 `source_description="录入错题功能"` 区分语义（具体以代码字段为准）

**状态**：已验证（字段存在且可写入）。实现：`backend/core/db/models.py`（`Question.exam_correction_id`、`Question.source`、`QuestionSourceEnum`、`AgentTask`）

---

### 5. 与检索/向量库/GraphRAG/MCP 的关系

Intake 的目标不仅是入库，还要让它“可被后续个性化能力使用”：
- 被 Hybrid 检索（FAISS+BM25）召回，用于“举一反三/小书童”
- 作为 GraphRAG 图谱构建的语料来源之一（离线 pipeline）

因此在 intake 处理结束后，理想情况下应触发 embedding/索引更新（best-effort），以便后续检索可用。

**状态**：待补充。当前实现未在 intake 完成后自动触发 FAISS/BM25 更新；需要通过离线 pipeline 构建/更新索引（例如 `./deploy/scripts/pipeline.sh kb ...` / `embed-index ...`）。

---

### 6. 推荐日志与排查

后端会输出带 task_id 的链路日志（示例关键前缀）：
- `[questions/ocr] task_id=...`：表示 intake OCR 链路

常见排查：
- 图片未落盘 / 权限问题：检查 `ImageFile.file_path` 与 default 模块图片访问
- 结构化失败：查看 `QuestionIntakeOCRAgent` 的 JSON 解析/容错逻辑
- 索引未更新：检查 embedding/向量库初始化路径（`data/faiss/<module>`、`data/bm25/<module>`）

