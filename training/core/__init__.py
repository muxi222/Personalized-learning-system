"""
training.core

Shared training utilities used by all subject modules (tony/rpj/wzy/wzm/xmx).

Design goals:
- Keep data/artifacts under `data/` (not under `training/`)
- Keep module-specific glue (prompts, subject taxonomies, sampling rules) in
  `training/modules/<module_name>/...`
- Keep reusable infra (GraphRAG KB builder/query, dataset preparation helpers,
  fine-tuning runners, serving manifests) here.
"""

