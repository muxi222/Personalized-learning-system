"""
Training Module
模型微调与Embedding训练

Layout (new):
- `training/core`: shared infra (GraphRAG KB, dataset prep, fine-tuning runners, serving)
- `training/modules/<module>`: module-specific entrypoints mirroring backend modules

Legacy scripts remain available under:
- `training/embedding/`
- `training/fine_tuning/`
"""

