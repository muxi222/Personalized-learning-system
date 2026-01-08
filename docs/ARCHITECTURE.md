## Architecture

### High-level components

This project uses a **module-based backend** (one FastAPI app per module) and a shared frontend.

Modules:
- `default` (6100): cross-subject aggregation + shared endpoints
- `rpj` (6001): 语文/英语/政治 (student TODO module)
- `xmx` (6002): 经济学 (student TODO module)
- `wzy` (6003): 数学/物理 (student TODO module)
- `wzm` (6004): 化学 (student TODO module)
- `tony` (6005): 历史/地理/其他 (**full implementation first**)

Shared infrastructure:
- SQLite DB (shared): `data/sqlite/app.db`
- Hybrid retrieval per module (FAISS + BM25): `data/faiss/<module>` + `data/bm25/<module>`
- Upload storage: `data/uploads/<user>/...`
- Redis: Celery broker/results + caching

### Runtime architecture diagram (services)

```mermaid
flowchart LR
  subgraph FE[Frontend]
    UI[React + Vite]
  end

  subgraph API[Backend Modules (FastAPI)]
    D[default :6100]
    R[rpj :6001]
    X[xmx :6002]
    W1[wzy :6003]
    W2[wzm :6004]
    T[tony :6005]
  end

  subgraph Infra[Shared Infra]
    DB[(SQLite/Postgres)]
    Redis[(Redis)]
    Uploads[(data/uploads)]
    Vec[(FAISS + BM25 per module)]
  end

  UI -->|/api/<module>/v1/*| D
  UI --> R
  UI --> X
  UI --> W1
  UI --> W2
  UI --> T

  D --> DB
  R --> DB
  X --> DB
  W1 --> DB
  W2 --> DB
  T --> DB

  D --> Vec
  R --> Vec
  X --> Vec
  W1 --> Vec
  W2 --> Vec
  T --> Vec

  D --> Uploads
  R --> Uploads
  X --> Uploads
  W1 --> Uploads
  W2 --> Uploads
  T --> Uploads

  D --> Redis
  R --> Redis
  X --> Redis
  W1 --> Redis
  W2 --> Redis
  T --> Redis
```

### Offline pipeline (GraphRAG + fine-tuning) diagram

```mermaid
flowchart TB
  DB[(data/sqlite/app.db)] -->|ETL| DS[SFT dataset / preference dataset]
  DB -->|Graph build| G[GraphRAG graph.json]
  Uploads[(data/uploads)] --> DS

  DS -->|SFT (LoRA/QLoRA)| SFT[Adapter checkpoints]
  DS -->|DPO (optional)| DPO[Preference checkpoints]

  SFT --> Serve[vLLM / serving]
  DPO --> Serve

  G --> Runtime[Backend GraphRAG Service]
  Runtime --> Agents[tony learning/review agents]
  Serve --> Agents
```

### Source layout (important folders)

- `backend/core/`: shared schemas/services/crud/db
- `backend/modules/<module>/`: per-module FastAPI + agents + endpoints
- `training/`: offline pipelines
  - `training/core/`: shared pipeline code (GraphRAG, datasets, preference optimization)
  - `training/modules/tony/`: Tony full pipeline entrypoints
- `deploy/scripts/`: scripts
  - Online services startup: `start.sh`, `start_module.sh`, `start-docker.sh`
  - Offline/training pipeline: `pipeline.sh`
- `data/`: runtime + training artifacts
  - `data/training/<module>/graphrag/graph.json`
  - `data/training/<module>/datasets/...`
  - `data/training/<module>/checkpoints/...`

