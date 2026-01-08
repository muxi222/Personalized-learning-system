## Training / GraphRAG / Model Serving (Tony first)

This repo supports **offline pipelines** that produce:
- a **GraphRAG knowledge base** (graph + retriever index)
- **fine-tuned checkpoints** (SFT LoRA/QLoRA + optional DPO)
- a **servable model endpoint** (vLLM OpenAI-compatible)

All artifacts MUST live under `data/`.

### Scripts entrypoint (recommended)

All offline pipelines are wrapped by:

```bash
./deploy/scripts/pipeline.sh help
```

### 1) Build Tony GraphRAG KB

Build graph only:

```bash
./deploy/scripts/pipeline.sh kb --module tony
```

Build graph + retriever index:

```bash
./deploy/scripts/pipeline.sh kb --module tony --build-index --embedding-backend hash
```

Outputs:
- Graph: `data/training/tony/graphrag/graph.json`
- Retriever (if enabled):
  - `data/faiss/tony/`
  - `data/bm25/tony/`

Notes:
- `--embedding-backend hash` works offline (no HuggingFace downloads) and is suitable for pipeline validation.
- For real semantic retrieval, use `sentence-transformers` with a locally available model cache.

### 2) Prepare Tony datasets

```bash
./deploy/scripts/pipeline.sh datasets --module tony
```

Outputs (default locations):
- `data/training/tony/datasets/sft/<subject>/train.jsonl` (per-subject)
- (legacy, optional) `data/training/tony/datasets/sft/train.jsonl`
- `data/training/tony/datasets/preference/train.jsonl` (if feedback pairs exist)

#### (Optional) Enrich SFT with free web data (10k~50k)

Step 1: fetch web dataset (HF) into a separate folder:

```bash
./deploy/scripts/pipeline.sh datasets-web --module tony --provider hf-gaokao-bench --min-total 10000 --max-total 50000
```

Or fetch a single-subject Gaokao Chinese MCQ dataset (schema: query+choices+gold):

```bash
./deploy/scripts/pipeline.sh datasets-web --module tony --provider hf-agieval-gaokao-chinese --max-total 50000
```

Notes:
- If your environment uses a SOCKS proxy (e.g. `ALL_PROXY=socks5h://...`), make sure you have SOCKS deps installed:
  - `pip install PySocks` (recommended)
  - or `pip install 'requests[socks]'`

If `pip install PySocks` fails with “Missing dependencies for SOCKS support”, that usually means **pip itself**
is trying to use the SOCKS proxy before PySocks is installed. Install with proxies temporarily disabled:

```bash
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy pip install PySocks
```
- Or run with `--no-proxy` to ignore proxy env vars:

```bash
./deploy/scripts/pipeline.sh datasets-web --module tony --provider hf-gaokao-bench --no-proxy --max-total 1000
```

Or set the proxy for this run:

```bash
./deploy/scripts/pipeline.sh datasets-web --module tony --provider hf-gaokao-bench \
  --all-proxy socks5h://127.0.0.1:10800 --max-total 1000
```

Step 2: merge web rows into per-subject `train.jsonl`:

```bash
./deploy/scripts/pipeline.sh datasets --module tony \
  --extra-sft-dir data/training/tony/datasets/sft_web
```

### 3) Fine-tune (SFT)

```bash
./deploy/scripts/pipeline.sh train-sft --module tony --subject history
```

Config lives at:
- `training/modules/tony/fine_tuning/configs/sft_qwen3_14b_lora.json`

### 4) Preference optimization (DPO, optional)

Requires preference pairs (from `feedbacks.preferred_response`):

```bash
./deploy/scripts/pipeline.sh train-dpo --module tony
```

Config:
- `training/modules/tony/fine_tuning/configs/dpo_qwen3_14b_lora.json`

### 5) Model serving (vLLM)

Start:

```bash
./deploy/scripts/pipeline.sh serve-model --module tony up
```

Stop:

```bash
./deploy/scripts/pipeline.sh serve-model --module tony down
```

The compose file is:
- `training/modules/tony/serving/docker-compose.vllm.yml`

### 6) Backend integration (GraphRAG feature flag)

Enable GraphRAG in backend processes:

```bash
export GRAPHRAG_ENABLED=true
```

Backend will read:
- `./data/training/<MODULE_NAME>/graphrag/graph.json`

Tony’s `learning` endpoints / agents will opportunistically expand retrieval via the graph.

### Module note

Only **Tony** has full pipeline implementations today.
Student modules (`rpj/xmx/wzy/wzm`) are intentionally TODO-only to be implemented by students.

