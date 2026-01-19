## RPJ Evaluation (stub)

This module is a student/TODO module in this repo.

This folder provides a **minimal runnable model eval** for OpenAI-compatible endpoints (vLLM):
- Eval set template: `training/modules/rpj/eval/assets/model_eval_min.jsonl`
- Runner: `training/modules/rpj/eval/run_model_eval.py`
- Core evaluator (shared): `training/core/eval/model_eval_openai_compatible.py`

Planned metrics:
- retrieval hit rate
- tool success/latency
- task failure/retry
- recommendation acceptance
- feedback rate/positive ratio
- journey duration + retention proxy

Run (requires the model server already running on port 8002 by default):

```bash
./deploy/scripts/pipeline.sh eval-model --module rpj
```

