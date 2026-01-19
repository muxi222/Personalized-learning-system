## Tony Evaluation (MCP + Retrieval + UX Metrics)

This folder provides **quantifiable** evaluation for the improvements introduced by MCP and related telemetry.

### Data sources
- **Online telemetry**: SQLite table `metric_events` in `data/sqlite/app.db`
- **Optional manual labels**: JSONL file for retrieval hit-rate evaluation (see below)

### What we measure (mapping to requested metrics)
- **Retrieval hit rate**:
  - `retrieval_hit_rate.py` supports:
    - manual labels (preferred)
    - weak supervision (fallback): treat same knowledge-points as "relevant"
- **Recommended question acceptance rate**:
  - from `metric_events`:
    - `reco.similar_questions.shown`
    - `reco.similar_questions.accept`
- **Explanation consistency**:
  - TODO: add a dedicated evaluator once explanation tool output is standardized
- **Tool call success rate / latency**:
  - from `metric_events`:
    - `tool.retrieval.search_questions`
    - `tool.retrieval.get_questions`
- **SSE/task failure rate / retry success**:
  - from `metric_events`:
    - `task.task.status_update`
    - `task.task.failed`
  - TODO: add explicit retry-success events (next iteration)
- **User journey duration** (exam upload → analysis → practice):
  - from `metric_events`:
    - `journey.ocr.analyze.start`
    - `journey.ocr.analyze.done`
    - `journey.ocr.analyze.failed`
  - practice step is tracked via `reco.similar_questions.accept` (when front-end calls it)
- **Retention (D1/D7)**:
  - computed via **key event sequence** (strict), not DAU proxy:
    - cohort Day0: `journey.ocr.analyze.done`
    - retained on D+1 / D+7 if any of:
      - `journey.ocr.analyze.done`
      - `reco.similar_questions.accept`
      - `feedback.learning.feedback`
- **Feedback rate & positive ratio**:
  - from `metric_events`: `feedback.learning.feedback`

### Run
From repo root:

```bash
python training/modules/tony/eval/metrics_from_db.py --db ./data/sqlite/app.db
python training/modules/tony/eval/retrieval_hit_rate.py --db ./data/sqlite/app.db --k 5 --max-questions 200
```

### Model serving eval (OpenAI-compatible, e.g. vLLM)

This repo also provides a lightweight **model endpoint** evaluation that many teams use in practice:
- send a curated prompt set to `/v1/chat/completions`
- compute basic automatic metrics (MCQ accuracy / char-F1)
- optionally use a rubric judge model (LLM-as-a-judge) to score tutoring quality

Run (requires `./deploy/scripts/pipeline.sh serve-model --module tony up` already running):

```bash
./deploy/scripts/pipeline.sh eval-model --module tony
```

The report is written to:
- `data/training/tony/eval/model_eval_report.json`

### Manual labels format (optional)
Create a file like `data/training/tony/eval/retrieval_labels.jsonl`:

Each line:
```json
{"query_question_id": 123, "relevant_question_ids": [45, 67, 89]}
```

