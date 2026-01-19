## XMX Evaluation (stub)

This module is a student/TODO module in this repo.

This folder provides a **minimal runnable model eval** for OpenAI-compatible endpoints (vLLM):
- Eval set template: `training/modules/xmx/eval/assets/model_eval_min.jsonl`
- Runner: `training/modules/xmx/eval/run_model_eval.py`
- Core evaluator (shared): `training/core/eval/model_eval_openai_compatible.py`

Run (requires the model server already running on port 8003 by default):

```bash
./deploy/scripts/pipeline.sh eval-model --module xmx
```

