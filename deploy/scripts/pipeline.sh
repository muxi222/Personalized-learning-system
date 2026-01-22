#!/bin/bash
# =============================================================================
# Offline/Training Pipeline Runner (per-module)
#
# This script is intentionally separate from service startup scripts:
# - Service startup: deploy/scripts/start.sh, start_module.sh, start-docker.sh
# - Offline pipelines: this file (GraphRAG KB build, dataset prep, fine-tuning, model serving)
#
# Usage examples:
#   ./deploy/scripts/pipeline.sh help
#
#   # Build Tony GraphRAG graph + (optionally) retriever index
#   ./deploy/scripts/pipeline.sh kb --module tony --build-index --embedding-backend hash
#
#   # Prepare Tony datasets
#   ./deploy/scripts/pipeline.sh datasets --module tony
#
#   # Train Tony SFT (uses module config)
#   ./deploy/scripts/pipeline.sh train-sft --module tony
#
#   # Train Tony DPO (requires feedback pairs)
#   ./deploy/scripts/pipeline.sh train-dpo --module tony
#
#   # Start/stop Tony vLLM serving (docker compose)
#   ./deploy/scripts/pipeline.sh serve-model --module tony up
#   ./deploy/scripts/pipeline.sh serve-model --module tony down
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

log_info() { printf "${BLUE}[INFO]${NC} %s\n" "$1"; }
log_ok() { printf "${GREEN}[OK]${NC} %s\n" "$1"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
log_err() { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

warn_proxy_for_localhost() {
  # Many classroom environments set SOCKS/HTTP proxies globally. `curl http://127.0.0.1:PORT`
  # will fail if curl tries to go through a SOCKS5 proxy (common error: "Failed to receive SOCKS5 connect request ack.").
  # Detect and print actionable hints.
  local port="$1"
  local proxy_vars=()
  for v in ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy; do
    if [ -n "${!v:-}" ]; then
      proxy_vars+=("${v}")
    fi
  done
  if [ ${#proxy_vars[@]} -eq 0 ]; then
    return 0
  fi

  local no_proxy="${NO_PROXY:-${no_proxy:-}}"
  if echo ",${no_proxy}," | grep -qiE ",(127\\.0\\.0\\.1|localhost|\\*),"; then
    return 0
  fi

  log_warn "Detected proxy env vars (${proxy_vars[*]}). Local curl to 127.0.0.1 may fail via SOCKS5 proxy."
  log_info "Fix (recommended):"
  log_info "  export NO_PROXY=127.0.0.1,localhost"
  log_info "Or run curl bypassing proxies for localhost:"
  log_info "  env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \\"
  log_info "    curl --noproxy '*' http://127.0.0.1:${port}/v1/models"
}

probe_http_models_no_proxy() {
  # Best-effort startup probe that does NOT use env proxies.
  # This avoids confusing "SOCKS5 connect request ack" errors when students verify the server.
  # It should be fast and never block startup.
  local port="$1"
  python - <<'PY' "${port}" >/dev/null 2>&1 || true
import json, socket, sys, time
port = int(sys.argv[1])

# TCP check first
s = socket.socket()
s.settimeout(0.2)
try:
  s.connect(("127.0.0.1", port))
except Exception:
  raise SystemExit(0)
finally:
  try: s.close()
  except Exception: pass

# Minimal HTTP GET /v1/models (stdlib, no proxy)
try:
  import http.client
  c = http.client.HTTPConnection("127.0.0.1", port, timeout=0.4)
  c.request("GET", "/v1/models")
  r = c.getresponse()
  body = r.read(256)  # preview only
  # Emit a tiny marker line for logs/stdout (caller prints the message).
  if 200 <= r.status < 300:
    print("OK", r.status, body.decode("utf-8", errors="ignore").replace("\n", " ")[:120])
  else:
    print("ERR", r.status, body.decode("utf-8", errors="ignore").replace("\n", " ")[:120])
except Exception:
  pass
PY
}

usage() {
  cat <<'EOF'
Offline/Training Pipeline Runner

Commands:
  kb            Build GraphRAG KB (graph.json) and optionally retriever index (FAISS+BM25)
  embed-index    Build retriever index only (FAISS+BM25) using module embedding settings
  datasets      Prepare datasets (SFT + preference)
  datasets-web  Fetch free/open web datasets (HF) and convert to module SFT JSONL (Tony)
  train-sft     Run module SFT fine-tuning wrapper
  train-dpo     Run module DPO preference optimization wrapper
  serve-model   Start/stop model server (vLLM local by default; supports --module <m>|all)
  fetch-model   Prefetch base model snapshot into HF cache (for vLLM)
  fetch-quantized-model  Prefetch a quantized base model (AWQ/GPTQ) into HF cache (for vLLM)
  eval-model    Evaluate served model (OpenAI-compatible; supports --module <m>|all)
  help          Show this help

Common flags:
  --module <tony|rpj|xmx|wzy|wzm|all>       Which module pipeline to run (offline steps are Tony-first)

serve-model flags:
  up|down|restart|logs|status
  --runtime <vllm|docker>
  --quantization <awq|gptq|bitsandbytes|...>     Enable vLLM quantization (single module only)
  --quantized-model <ORG/REPO|/abs/path>         Quantized base model repo or local dir (used with --quantization)
  --dtype <auto|bfloat16|float16|...>            vLLM compute dtype (works with or without quantization)
  --load-format <auto|safetensors|gguf|...>      vLLM load format hint (works with or without quantization)

kb flags (passed through to training script where supported):
  --build-index
  --embedding-backend <hash|sentence-transformers>
  --embedding-model <hf-or-local-name>
  --limit <N>

Examples:
  ./deploy/scripts/pipeline.sh kb --module tony --build-index --embedding-backend hash --limit 200
  ./deploy/scripts/pipeline.sh embed-index --module tony --embedding-backend hash --limit 200
  ./deploy/scripts/pipeline.sh datasets-web --module tony --min-total 10000 --max-total 50000
  ./deploy/scripts/pipeline.sh datasets --module tony
  ./deploy/scripts/pipeline.sh train-sft --module tony --subject history
  ./deploy/scripts/pipeline.sh serve-model --module tony up
  ./deploy/scripts/pipeline.sh serve-model --module tony up --dtype bfloat16 --load-format auto
  ./deploy/scripts/pipeline.sh serve-model --module tony up --quantization awq --quantized-model <ORG/REPO>
  ./deploy/scripts/pipeline.sh serve-model --module all up
  ./deploy/scripts/pipeline.sh fetch-model --module tony
  ./deploy/scripts/pipeline.sh fetch-quantized-model --module tony --quantization awq --model <ORG/REPO>
  ./deploy/scripts/pipeline.sh eval-model --module tony
  ./deploy/scripts/pipeline.sh eval-model --module all

Notes:
- Only tony has a full implementation today; other modules are TODO/student modules.
- All data/artifacts are stored under ./data/ by convention.
EOF
}

if [ $# -lt 1 ]; then
  usage
  exit 1
fi

CMD="$1"; shift

MODULE=""
PASSTHRU=()

while [ $# -gt 0 ]; do
  case "$1" in
    --module)
      MODULE="$2"; shift 2 ;;
    *)
      PASSTHRU+=("$1"); shift ;;
  esac
done

if [ "$CMD" = "help" ]; then
  usage
  exit 0
fi

if [ -z "$MODULE" ]; then
  log_err "Missing --module"
  usage
  exit 1
fi

# If the script is invoked from an unexpected path (e.g. copied into /deploy/),
# fall back to current working directory to locate the repo root.
if [ ! -d "${PROJECT_ROOT}/backend" ] || [ ! -d "${PROJECT_ROOT}/training" ]; then
  log_warn "PROJECT_ROOT (${PROJECT_ROOT}) doesn't look like repo root; falling back to pwd"
  PROJECT_ROOT="$(pwd)"
fi

cd "${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}/backend:${PYTHONPATH:+:$PYTHONPATH}"

# -----------------------------------------------------------------------------
# HuggingFace cache location (models/datasets) - classroom unified cache.
#
# Requirement: training (train-*) + fetch-model + serve-model MUST share the same
# HF hub cache folder to support resumable downloads and avoid re-downloading.
#
# Target path:
#   /home/dataset-assist-0/data/work/.cache/huggingface/hub/
# -----------------------------------------------------------------------------
export HF_HOME="/home/dataset-assist-0/data/work/.cache/huggingface"
export HF_HUB_CACHE="/home/dataset-assist-0/data/work/.cache/huggingface/hub"
# transformers>=5 will remove TRANSFORMERS_CACHE; prefer HF_HOME/HF_HUB_CACHE.
# Also unset it to avoid warnings if user has it set in their shell.
unset TRANSFORMERS_CACHE

# HuggingFace Hub tuning for flaky networks:
# - Increase etag timeout (default 10s) so metadata fetch is less likely to fail.
# - Use xet cache dir (already under HF_HOME). If hf_xet is installed, hub can use it.
export HF_HUB_ETAG_TIMEOUT="${HF_HUB_ETAG_TIMEOUT:-60}"
export HF_XET_CACHE="${HF_XET_CACHE:-${HF_HOME}/xet}"
export HF_HUB_ENABLE_HF_XET="${HF_HUB_ENABLE_HF_XET:-1}"
mkdir -p "${HF_HOME}"

# Ensure cache subdirs exist (and fix up any stale symlinks from previous runs).
if [ -L "${HF_HUB_CACHE}" ] && [ ! -d "${HF_HUB_CACHE}" ]; then
  rm -f "${HF_HUB_CACHE}"
fi
mkdir -p "${HF_HUB_CACHE}"

if [ -L "${HF_HOME}/datasets" ] && [ ! -d "${HF_HOME}/datasets" ]; then
  rm -f "${HF_HOME}/datasets"
fi
mkdir -p "${HF_HOME}/datasets"

# IMPORTANT (classroom): do NOT maintain a second "local_dir" copy of base models.
# All base model downloads must live under the shared HF hub cache:
#   /home/dataset-assist-0/data/work/.cache/huggingface/hub/
# Training and serving will load from the hub snapshots directly (cache-first),
# so we intentionally DISABLE `HF_MODEL_LOCAL_DIR`.
unset HF_MODEL_LOCAL_DIR

resolve_python() {
  # 1) explicit override
  if [ -n "${PYTHON:-}" ]; then
    echo "${PYTHON}"
    return 0
  fi

  # 2) active env (preferred): if the user already activated conda/venv, respect it.
  # This is the most reliable way to pick the python that actually has deps installed.
  if [ -n "${CONDA_PREFIX:-}" ] && [ -x "${CONDA_PREFIX}/bin/python" ]; then
    echo "${CONDA_PREFIX}/bin/python"
    return 0
  fi
  if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
    echo "${VIRTUAL_ENV}/bin/python"
    return 0
  fi

  # 3) known deployment path (best-effort; some teaching environments pre-create it)
  if [ -x "/home/dataset-assist-0/data/conda/envs/312_edu/bin/python" ]; then
    echo "/home/dataset-assist-0/data/conda/envs/312_edu/bin/python"
    return 0
  fi

  # 4) prefer conda env if available (matches start.sh convention)
  if command -v conda >/dev/null 2>&1; then
    if conda env list 2>/dev/null | awk '{print $1}' | grep -qx "312_edu"; then
      echo "conda-run"
      return 0
    fi
  fi

  # 5) fallback
  echo "python3"
}

PY_MODE="$(resolve_python)"

run_py() {
  if [ "$PY_MODE" = "conda-run" ]; then
    conda run -n 312_edu --no-capture-output python "$@"
  else
    "$PY_MODE" "$@"
  fi
}

filter_args_for_prepare_sft() {
  # prepare_sft.py should not receive preference-demo flags.
  local -a in_args=("$@")
  local -a out_args=()
  local i=0
  while [ $i -lt ${#in_args[@]} ]; do
    local a="${in_args[$i]}"
    case "$a" in
      --demo)
        i=$((i+1))
        continue
        ;;
      --demo-n|--demo-seed)
        i=$((i+2))
        continue
        ;;
      --demo-n=*|--demo-seed=*)
        i=$((i+1))
        continue
        ;;
    esac
    out_args+=("$a")
    i=$((i+1))
  done

  if [ ${#out_args[@]} -gt 0 ]; then
    printf '%s\n' "${out_args[@]}"
  fi
}

filter_args_for_prepare_preferences() {
  # prepare_preferences.py accepts: --sqlite, --output, --subjects, --limit, --demo, --demo-n, --demo-seed
  # Users often pass SFT-only flags (e.g. --extra-sft-dir) to `pipeline.sh datasets`,
  # which should not break the preference step.
  local -a in_args=("$@")
  local -a out_args=()
  local i=0
  while [ $i -lt ${#in_args[@]} ]; do
    local a="${in_args[$i]}"

    # Drop SFT-only flags (support both `--flag value` and `--flag=value` forms)
    case "$a" in
      --extra-sft-dir|--output-dir|--legacy-output)
        i=$((i+2))
        continue
        ;;
      --extra-sft-dir=*|--output-dir=*|--legacy-output=*)
        i=$((i+1))
        continue
        ;;
      --write-split-artifacts)
        i=$((i+1))
        continue
        ;;
    esac

    out_args+=("$a")
    i=$((i+1))
  done

  # Return array via stdout, one arg per line (caller must read carefully).
  # NOTE: if out_args is empty, emit nothing (no blank line).
  if [ ${#out_args[@]} -gt 0 ]; then
    printf '%s\n' "${out_args[@]}"
  fi
}

VALID_MODULES=("rpj" "xmx" "wzy" "wzm" "tony")

is_valid_module() {
  local m="$1"
  for x in "${VALID_MODULES[@]}"; do
    if [ "$x" = "$m" ]; then
      return 0
    fi
  done
  return 1
}

ensure_training_module_supported() {
  # Training/offline pipeline is Tony-first by design.
  if [ "$MODULE" != "tony" ]; then
    log_err "Module '$MODULE' offline pipeline is TODO/student-only. Only 'tony' is fully implemented."
    log_info "You can use the Tony scripts as reference: training/modules/tony/..."
    exit 1
  fi
}

resolve_docker_compose() {
  # Prefer Docker Compose v2 plugin: `docker compose`
  if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
      DOCKER_COMPOSE_CMD=("docker" "compose")
      return 0
    fi
  fi

  # Fallback: legacy docker-compose binary
  if command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD=("docker-compose")
    return 0
  fi

  log_err "Docker / Docker Compose 未安装或不可用，无法执行 serve-model（当前实现使用 docker compose）。"
  log_info "解决方案（二选一）："
  log_info "  A) 安装 Docker（推荐）:"
  log_info "     - 确保系统有 docker 命令，并且 docker compose 可用（或安装 docker-compose）"
  log_info "     - 安装后重试: ./deploy/scripts/pipeline.sh serve-model --module tony up"
  log_info "  B) 不使用 Docker：请在本机 Python 环境直接启动 vLLM（需要你手动安装 vllm 并准备模型路径）。"
  log_info "     - 参考说明: training/modules/tony/serving/README.md"
  return 127
}

PID_DIR="${PROJECT_ROOT}/pids"
LOG_DIR="${PROJECT_ROOT}/logs"
VLLM_PY=""
VLLM_HF_HOME=""
VLLM_HF_HUB_CACHE=""

ensure_dirs() {
  mkdir -p "${PID_DIR}" "${LOG_DIR}"
}

select_vllm_hf_cache() {
  # vLLM may run under a different Python env; we force a single, classroom-unified cache.
  # This MUST match HF_HOME/HF_HUB_CACHE used by training + fetch-model.
  VLLM_HF_HOME="${HF_HOME}"
  VLLM_HF_HUB_CACHE="${HF_HUB_CACHE}"
  mkdir -p "${VLLM_HF_HOME}" "${VLLM_HF_HUB_CACHE}"
}

pid_file_for_model() {
  local module="$1"
  echo "${PID_DIR}/model_${module}.pid"
}

log_file_for_model() {
  local module="$1"
  echo "${LOG_DIR}/model_${module}.log"
}

# Best-effort: port check (requires lsof). If lsof is missing, skip.
check_port_free() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    if lsof -Pi :"${port}" -sTCP:LISTEN -t >/dev/null 2>&1; then
      return 1
    fi
  fi
  return 0
}

# Recursively collect descendants of a PID (best-effort; works on Linux/macOS with pgrep).
get_descendants() {
  local root_pid="$1"
  local out=()

  if [ -z "${root_pid}" ]; then
    return 0
  fi
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi

  local children
  children=$(pgrep -P "${root_pid}" 2>/dev/null || true)
  if [ -z "${children}" ]; then
    return 0
  fi

  for c in ${children}; do
    out+=("${c}")
    local g
    g=$(get_descendants "${c}" || true)
    if [ -n "${g}" ]; then
      out+=(${g})
    fi
  done

  echo "${out[@]}"
}

kill_tree() {
  local pid="$1"
  local sig="${2:-TERM}"
  if [ -z "${pid}" ]; then
    return 0
  fi
  local desc
  desc=$(get_descendants "${pid}" || true)
  if [ -n "${desc}" ]; then
    for d in ${desc}; do
      kill "-${sig}" "${d}" 2>/dev/null || true
    done
  fi
  kill "-${sig}" "${pid}" 2>/dev/null || true
}

safe_kill_pid_file() {
  local pid_file="$1"
  if [ -f "${pid_file}" ]; then
    local pid
    pid=$(cat "${pid_file}" 2>/dev/null || true)
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
      # Kill process tree first (conda run wrapper may not forward signals)
      kill_tree "${pid}" "TERM"
      # Also try killing process group if applicable
      kill -TERM -- "-${pid}" 2>/dev/null || true
      sleep 1
      kill_tree "${pid}" "KILL"
      kill -KILL -- "-${pid}" 2>/dev/null || true
    fi
    rm -f "${pid_file}"
  fi
}

check_vllm_available_or_exit() {
  # vLLM may be installed in a different Python than the repo's training env (312_edu).
  # For model serving, we allow a dedicated python just for vLLM:
  # - env override: VLLM_PYTHON=/path/to/python
  # - otherwise try current shell `python`, then some known locations
  #
  # Important: `import vllm` may fail even when installed due to CUDA/torch/triton mismatch.
  # We distinguish:
  # - NOT installed: find_spec('vllm') is None
  # - installed but broken: find_spec exists but import fails

  if [ -n "${VLLM_PY}" ]; then
    return 0
  fi

  local -a candidates=()
  if [ -n "${VLLM_PYTHON:-}" ]; then
    candidates+=("${VLLM_PYTHON}")
  fi
  # If user explicitly sets PYTHON, prefer it too (common in teaching envs).
  if [ -n "${PYTHON:-}" ]; then
    candidates+=("${PYTHON}")
  fi
  # Current PATH python (may be miniforge)
  if command -v python >/dev/null 2>&1; then
    candidates+=("python")
  fi
  # Repo training env python (might or might not have vLLM)
  candidates+=("/home/dataset-assist-0/data/conda/envs/312_edu/bin/python")
  # A common miniforge location used in this environment (observed in practice)
  candidates+=("/home/dataset-assist-0/data/opt/miniforge3/bin/python")
  # Fallbacks
  if command -v python3 >/dev/null 2>&1; then
    candidates+=("python3")
  fi

  local chosen=""
  for c in "${candidates[@]}"; do
    # Skip non-existent absolute paths
    if [[ "${c}" == /* ]] && [ ! -x "${c}" ]; then
      continue
    fi
    # 1) Check module presence without importing heavy deps.
    if ${c} -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('vllm') else 1)" >/dev/null 2>&1; then
      chosen="${c}"
      break
    fi
  done

  if [ -z "${chosen}" ]; then
    log_err "vLLM 未安装（在可探测的 Python 环境中都找不到 vllm 包），无法用本机方式启动模型服务。"
    log_info "已尝试的 Python 候选："
    for c in "${candidates[@]}"; do
      echo "  - ${c}"
    done
    log_info "解决方案："
    log_info "  1) 在你实际用于 vLLM 的 python 环境里安装：pip install -U vllm"
    log_info "  2) 或显式指定：VLLM_PYTHON=/path/to/python ./deploy/scripts/pipeline.sh serve-model --module tony up"
    exit 1
  fi

  # 2) It is installed; now ensure it can be imported (surface real error if not).
  if ${chosen} -c "import vllm; print(getattr(vllm, '__version__', 'unknown'))" >/dev/null 2>&1; then
    VLLM_PY="${chosen}"
    log_info "vLLM Python selected: ${VLLM_PY}"
    ${VLLM_PY} -c "import sys; print('  sys.executable=', sys.executable); print('  sys.prefix=', sys.prefix)" 2>/dev/null || true
    return 0
  fi

  log_err "检测到 vLLM 已安装（${chosen}），但 import vllm 失败（通常是 CUDA / PyTorch / Triton 不匹配）。"
  log_info "请直接运行下面命令查看真实报错："
  log_info "  ${chosen} -c \"import vllm; print(vllm.__version__)\""
  log_info "常见修复思路："
  log_info "  - 确认 torch 与 CUDA/驱动匹配（vLLM 强依赖 GPU 环境）"
  log_info "  - 重新安装与当前 CUDA 版本匹配的 vllm wheel"
  exit 1
}

vllm_port_for() {
  # Default ports (avoid 8000 frontend):
  # - tony: 8001 (keeps backward compatibility with earlier docs)
  # - others: 8002..8005
  local module="$1"
  local env_key="VLLM_PORT_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  case "${module}" in
    tony) echo "8001" ;;
    rpj) echo "8002" ;;
    xmx) echo "8003" ;;
    wzy) echo "8004" ;;
    wzm) echo "8005" ;;
    *) echo "" ;;
  esac
}

vllm_max_model_len_for() {
  local module="$1"
  local env_key="VLLM_MAX_MODEL_LEN_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  # Course default: 8192, but this can be very memory-heavy (KV cache) on 40GB-class GPUs.
  # Best-practice heuristic: if total VRAM is ~<=48GB, default to 4096 for stability.
  local vram_gb=""
  vram_gb=$("${VLLM_PY:-python}" - <<'PY' 2>/dev/null || true
import math
try:
  import torch
  if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print(int(math.floor(p.total_memory / (1024**3))))
except Exception:
  pass
PY
)
  if [ -n "${vram_gb}" ] && [[ "${vram_gb}" =~ ^[0-9]+$ ]] && [ "${vram_gb}" -le 48 ]; then
    echo "4096"
  else
    echo "8192"
  fi
}

vllm_gpu_memory_utilization_for() {
  local module="$1"
  local env_key="VLLM_GPU_MEMORY_UTILIZATION_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  # Course default: 0.90, but leaving too little headroom often causes instability when:
  # - other CUDA processes (e.g. training) are running
  # - CUDA allocator fragmentation occurs over time
  # Best-practice heuristic: on ~<=48GB GPUs, default to 0.85.
  local vram_gb=""
  vram_gb=$("${VLLM_PY:-python}" - <<'PY' 2>/dev/null || true
import math
try:
  import torch
  if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print(int(math.floor(p.total_memory / (1024**3))))
except Exception:
  pass
PY
)
  if [ -n "${vram_gb}" ] && [[ "${vram_gb}" =~ ^[0-9]+$ ]] && [ "${vram_gb}" -le 48 ]; then
    echo "0.85"
  else
    echo "0.90"
  fi
}

vllm_max_num_seqs_for() {
  # Concurrency control (scheduler). Smaller => lower KV cache pressure under load.
  # Override:
  #   export VLLM_MAX_NUM_SEQS_TONY=8
  local module="$1"
  local env_key="VLLM_MAX_NUM_SEQS_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  # Default: keep vLLM defaults unless user explicitly wants memory-tuned serving.
  echo ""
}

vllm_max_num_batched_tokens_for() {
  # Prefill batching limit. Smaller => less aggressive batching (often less memory spikes).
  # Override:
  #   export VLLM_MAX_NUM_BATCHED_TOKENS_TONY=8192
  local module="$1"
  local env_key="VLLM_MAX_NUM_BATCHED_TOKENS_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  echo ""
}

vllm_kv_cache_dtype_for() {
  # KV cache dtype (vLLM 0.13 supports: auto, fp8, fp8_e4m3, fp8_e5m2, ...).
  # WARNING: fp8 KV cache requires CUDA 11.8+ and may have quality/perf trade-offs.
  # Override:
  #   export VLLM_KV_CACHE_DTYPE_TONY=auto|fp16|fp8_e4m3
  local module="$1"
  local env_key="VLLM_KV_CACHE_DTYPE_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  echo ""
}

vllm_dtype_for() {
  # Model dtype (weights/compute). Often auto/bfloat16/float16.
  # Override:
  #   export VLLM_DTYPE_TONY=bfloat16
  local module="$1"
  local env_key="VLLM_DTYPE_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  echo ""
}

vllm_quantization_for() {
  # Weight quantization mode (depends on vLLM build + model format), e.g. awq/gptq/bitsandbytes/fp8.
  # Override:
  #   export VLLM_QUANTIZATION_TONY=awq
  local module="$1"
  local env_key="VLLM_QUANTIZATION_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  echo ""
}

vllm_load_format_for() {
  # Load format hint for vLLM (e.g. auto, safetensors, gguf, bitsandbytes).
  # Override:
  #   export VLLM_LOAD_FORMAT_TONY=auto
  local module="$1"
  local env_key="VLLM_LOAD_FORMAT_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  echo ""
}

vllm_swap_space_for() {
  # KV cache swap-space (GiB) to host memory. Helps avoid OOM under bursty load at the cost of latency.
  # Override:
  #   export VLLM_SWAP_SPACE_TONY=4
  local module="$1"
  local env_key="VLLM_SWAP_SPACE_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  echo ""
}

vllm_cpu_offload_gb_for() {
  # CPU offload capacity (GiB). Can reduce GPU memory pressure.
  # Override:
  #   export VLLM_CPU_OFFLOAD_GB_TONY=4
  local module="$1"
  local env_key="VLLM_CPU_OFFLOAD_GB_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  echo ""
}

vllm_max_loras_for() {
  # Limit number of LoRA adapters resident at once.
  # Override:
  #   export VLLM_MAX_LORAS_TONY=4
  local module="$1"
  local env_key="VLLM_MAX_LORAS_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  echo ""
}

vllm_enforce_eager_for() {
  local module="$1"
  local env_key="VLLM_ENFORCE_EAGER_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  # Stability-first default: enforce eager to avoid torch.compile + CUDA graph capture.
  # This reduces startup complexity and often avoids "mysterious early exits" in constrained environments.
  echo "true"
}

vllm_base_model_for() {
  local module="$1"
  local env_key="VLLM_BASE_MODEL_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
  else
    echo "OpenPipe/Qwen3-14B-Instruct"
  fi
}

quant_map_file() {
  # Persistent mapping for quantized base models (so serve-model --quantization can be one-click).
  echo "${PROJECT_ROOT}/data/vllm/quantized_base_models.json"
}

get_quantized_model_from_map() {
  local module="$1"
  local quant="$2"
  local f
  f="$(quant_map_file)"
  "${VLLM_PY:-python}" - <<'PY' "${f}" "${module}" "${quant}" 2>/dev/null || true
import json, os, sys
f, module, quant = sys.argv[1], sys.argv[2].lower(), sys.argv[3].lower()
if not os.path.isfile(f):
    raise SystemExit(0)
try:
    obj = json.load(open(f, "r", encoding="utf-8"))
except Exception:
    raise SystemExit(0)
print(((obj.get(module) or {}).get(quant) or "").strip())
PY
}

set_quantized_model_in_map() {
  local module="$1"
  local quant="$2"
  local model_id="$3"
  local f
  f="$(quant_map_file)"
  mkdir -p "$(dirname "${f}")"
  "${VLLM_PY:-python}" - <<'PY' "${f}" "${module}" "${quant}" "${model_id}"
import json, os, sys
f, module, quant, model_id = sys.argv[1], sys.argv[2].lower(), sys.argv[3].lower(), sys.argv[4]
obj = {}
if os.path.isfile(f):
    try:
        obj = json.load(open(f, "r", encoding="utf-8"))
    except Exception:
        obj = {}
obj.setdefault(module, {})[quant] = model_id
with open(f, "w", encoding="utf-8") as w:
    json.dump(obj, w, ensure_ascii=False, indent=2)
print(f)
PY
}

resolve_quantized_base_model_for() {
  local module="$1"
  local quant="$2"
  if [ -z "${module}" ] || [ -z "${quant}" ]; then
    echo ""
    return 0
  fi
  local env_key="VLLM_BASE_MODEL_$(echo "${module}" | tr '[:lower:]' '[:upper:]')_$(echo "${quant}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  get_quantized_model_from_map "${module}" "${quant}"
}

vllm_chat_template_for() {
  # transformers>=4.44 disallows "default chat template" when tokenizer has no chat_template.
  # vLLM will then return 400 for /v1/chat/completions unless --chat-template is provided.
  local module="$1"
  local env_key="VLLM_CHAT_TEMPLATE_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi
  # Course default: ChatML template for Qwen-style instruct models.
  echo "${PROJECT_ROOT}/deploy/vllm/chat_templates/template_chatml.jinja"
}

resolve_hf_snapshot_dir_if_present() {
  # If the base model is already cached in HF_HUB_CACHE, prefer a local snapshot path
  # to avoid any network calls (common in restricted classrooms).
  # Input: model id like "OpenPipe/Qwen3-14B-Instruct"
  # Output: absolute snapshot dir or empty.
  local model_id="$1"
  if [ -z "${model_id}" ]; then
    echo ""
    return 0
  fi
  # Only handle hub-style ids ORG/REPO
  if [[ "${model_id}" != */* ]]; then
    echo ""
    return 0
  fi
  local org="${model_id%%/*}"
  local repo="${model_id##*/}"
  local hub_cache="${VLLM_HF_HUB_CACHE:-${HF_HUB_CACHE}}"
  local cache_dir="${hub_cache}/models--${org}--${repo}"
  if [ ! -d "${cache_dir}/snapshots" ]; then
    echo ""
    return 0
  fi

  is_hf_snapshot_complete() {
    local dir="$1"
    # Must have config + tokenizer + weights (any common format)
    if [ ! -f "${dir}/config.json" ]; then
      return 1
    fi
    if ! compgen -G "${dir}/tokenizer.*" >/dev/null 2>&1; then
      # some repos use vocab/merges; still need tokenizer_config at least for AutoTokenizer
      if [ ! -f "${dir}/tokenizer_config.json" ]; then
        return 1
      fi
    fi
    if compgen -G "${dir}/*.safetensors" >/dev/null 2>&1; then
      return 0
    fi
    if compgen -G "${dir}/pytorch_model*.bin" >/dev/null 2>&1; then
      return 0
    fi
    if [ -f "${dir}/model.safetensors.index.json" ]; then
      # Validate all shard files referenced by index exist.
      if "${VLLM_PY:-python}" - <<'PY' "${dir}" >/dev/null 2>&1
import json, os, sys
snap=sys.argv[1]
idx=os.path.join(snap,"model.safetensors.index.json")
obj=json.load(open(idx,"r",encoding="utf-8"))
files=set((obj.get("weight_map") or {}).values())
missing=[f for f in files if not os.path.isfile(os.path.join(snap,f))]
raise SystemExit(0 if not missing else 1)
PY
      then
        return 0
      fi
      return 1
    fi
    if [ -f "${dir}/pytorch_model.bin.index.json" ]; then
      if "${VLLM_PY:-python}" - <<'PY' "${dir}" >/dev/null 2>&1
import json, os, sys
snap=sys.argv[1]
idx=os.path.join(snap,"pytorch_model.bin.index.json")
obj=json.load(open(idx,"r",encoding="utf-8"))
files=set((obj.get("weight_map") or {}).values())
missing=[f for f in files if not os.path.isfile(os.path.join(snap,f))]
raise SystemExit(0 if not missing else 1)
PY
      then
        return 0
      fi
      return 1
    fi
    return 1
  }

  # Prefer the snapshot pinned by local refs/<revision> (no network needed).
  local revision="${HF_REVISION:-main}"
  local ref_file="${cache_dir}/refs/${revision}"
  if [ -f "${ref_file}" ]; then
    local sha
    sha="$(cat "${ref_file}" 2>/dev/null | tr -d ' \n\r\t' || true)"
    if [ -n "${sha}" ] && [ -d "${cache_dir}/snapshots/${sha}" ] && is_hf_snapshot_complete "${cache_dir}/snapshots/${sha}"; then
      echo "${cache_dir}/snapshots/${sha}"
      return 0
    fi
  fi

  # Fallback: newest snapshot (best-effort).
  local latest
  latest=$(ls -1dt "${cache_dir}/snapshots/"* 2>/dev/null | head -1 || true)
  if [ -n "${latest}" ] && is_hf_snapshot_complete "${latest}"; then
    echo "${latest}"
    return 0
  fi
  echo ""
  return 0
}

vllm_served_name_for() {
  local module="$1"
  local env_key="VLLM_SERVED_MODEL_NAME_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
  else
    echo "${module}-qwen3-14b"
  fi
}

collect_lora_modules_for() {
  # Output one `name=path` per line (caller reads lines).
  local module="$1"

  local dpo="${PROJECT_ROOT}/data/training/${module}/checkpoints/dpo_lora"
  if [ -d "${dpo}" ]; then
    echo "${module}-dpo=${dpo}"
  fi

  local sft="${PROJECT_ROOT}/data/training/${module}/checkpoints/sft_lora"
  if [ -d "${sft}" ]; then
    # If there are subdirs (e.g. history), expose each as a separate LoRA model.
    local found=false
    for sub in "${sft}"/*; do
      if [ -d "${sub}" ]; then
        found=true
        echo "${module}-sft-$(basename "${sub}")=${sub}"
      fi
    done
    if [ "${found}" = "false" ]; then
      echo "${module}-sft=${sft}"
    fi
  fi

  # Optional extra modules via env (comma-separated):
  #   export VLLM_LORA_MODULES_TONY="custom=/abs/path/to/adapter,foo=/abs/path2"
  local env_key="VLLM_LORA_MODULES_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local extra="${!env_key:-}"
  if [ -n "${extra}" ]; then
    # Split by comma
    local IFS=","
    for pair in ${extra}; do
      pair="$(echo "${pair}" | xargs)"
      if [ -n "${pair}" ]; then
        echo "${pair}"
      fi
    done
  fi
}

vllm_max_lora_rank_for_module() {
  # Determine required max_lora_rank for the module based on adapter configs.
  # Users can override explicitly:
  #   export VLLM_MAX_LORA_RANK_TONY=64
  local module="$1"
  local env_key="VLLM_MAX_LORA_RANK_$(echo "${module}" | tr '[:lower:]' '[:upper:]')"
  local override="${!env_key:-}"
  if [ -n "${override}" ]; then
    echo "${override}"
    return 0
  fi

  # Default vLLM max_lora_rank is 16; keep that as floor.
  local floor_rank=16

  # Collect adapter directories (paths only).
  local -a adapter_dirs=()
  while IFS= read -r line; do
    if [ -z "${line}" ]; then
      continue
    fi
    # line form: name=/abs/path
    local p="${line#*=}"
    if [ -n "${p}" ] && [ -d "${p}" ]; then
      adapter_dirs+=("${p}")
    fi
  done < <(collect_lora_modules_for "${module}")

  if [ ${#adapter_dirs[@]} -eq 0 ]; then
    echo "${floor_rank}"
    return 0
  fi

  # Parse adapter_config.json in each adapter dir to extract r (rank).
  # Common keys:
  # - "r" (peft)
  # - "lora_r" (some custom configs)
  local max_rank
  max_rank=$("${VLLM_PY}" - <<'PY' "${adapter_dirs[@]}" 2>/dev/null || true
import json, os, sys
paths = sys.argv[1:]
best = 0
for d in paths:
  cfg = os.path.join(d, "adapter_config.json")
  if not os.path.isfile(cfg):
    continue
  try:
    obj = json.load(open(cfg, "r", encoding="utf-8"))
  except Exception:
    continue
  for k in ("r", "lora_r"):
    v = obj.get(k)
    try:
      best = max(best, int(v))
    except Exception:
      pass
print(best)
PY
)

  # Fallback if we couldn't parse any adapter configs.
  if [ -z "${max_rank}" ] || ! [[ "${max_rank}" =~ ^[0-9]+$ ]]; then
    echo "${floor_rank}"
    return 0
  fi

  if [ "${max_rank}" -lt "${floor_rank}" ]; then
    echo "${floor_rank}"
  else
    echo "${max_rank}"
  fi
}

start_vllm_module() {
  ensure_dirs

  local module="$1"
  local port
  port="$(vllm_port_for "${module}")"
  if [ -z "${port}" ]; then
    log_err "Unknown model serving port for module='${module}'"
    exit 1
  fi

  local pid_file
  pid_file="$(pid_file_for_model "${module}")"
  local log_file
  log_file="$(log_file_for_model "${module}")"

  # Already running?
  if [ -f "${pid_file}" ]; then
    local old_pid
    old_pid=$(cat "${pid_file}" 2>/dev/null || true)
    if [ -n "${old_pid}" ] && kill -0 "${old_pid}" 2>/dev/null; then
      log_warn "Model server already running (module=${module}, PID: ${old_pid})"
      log_info "Models: http://127.0.0.1:${port}/v1/models"
      log_info "Logs:   ${log_file}"
      return 0
    fi
    rm -f "${pid_file}"
  fi

  if ! check_port_free "${port}"; then
    log_err "端口 ${port} 已被占用，无法启动 vLLM"
    if command -v lsof >/dev/null 2>&1; then
      log_info "占用信息: $(lsof -Pi :${port} -sTCP:LISTEN | tail -n +2 | head -1)"
    fi
    exit 1
  fi

  check_vllm_available_or_exit

  # Ensure vLLM uses a HF cache that actually contains weights/tokenizer (avoid network).
  select_vllm_hf_cache

  local base_model
  base_model="$(vllm_base_model_for "${module}")"
  # If quantization is enabled for this module, prefer a quantized base model mapping:
  # - env: VLLM_BASE_MODEL_<MODULE>_<QUANT>=...
  # - or persisted mapping written by `fetch-quantized-model`
  local _quant_for_base
  _quant_for_base="$(vllm_quantization_for "${module}")"
  if [ -n "${_quant_for_base}" ]; then
    local _qbase
    _qbase="$(resolve_quantized_base_model_for "${module}" "${_quant_for_base}")"
    if [ -n "${_qbase}" ]; then
      log_info "Quantization enabled: quant=${_quant_for_base}; using quantized base model:"
      log_info "  ${_qbase}"
      base_model="${_qbase}"
    else
      log_warn "Quantization enabled (${_quant_for_base}) but no quantized base model mapping found."
      log_warn "Set VLLM_BASE_MODEL_${module^^}_${_quant_for_base^^}=<ORG/REPO> (or local dir), or run:"
      log_warn "  ./deploy/scripts/pipeline.sh fetch-quantized-model --module ${module} --quantization ${_quant_for_base} --model <ORG/REPO>"
    fi
  fi
  # If cached, switch to local snapshot dir to avoid HF network.
  local cached_dir
  cached_dir="$(resolve_hf_snapshot_dir_if_present "${base_model}")"
  if [ -n "${cached_dir}" ]; then
    log_info "Using local HF snapshot dir for base model:"
    log_info "  ${cached_dir}"
    base_model="${cached_dir}"
    # Preflight: ensure snapshot shards are complete (avoid vLLM crash).
    if [ -f "${base_model}/model.safetensors.index.json" ]; then
      missing=$("${VLLM_PY}" - <<'PY' "${base_model}" || true
import json, os, sys
snap=sys.argv[1]
idx=os.path.join(snap,"model.safetensors.index.json")
obj=json.load(open(idx,"r",encoding="utf-8"))
files=sorted(set((obj.get("weight_map") or {}).values()))
missing=[f for f in files if not os.path.isfile(os.path.join(snap,f))]
print("\n".join(missing))
raise SystemExit(0 if not missing else 2)
PY
)
      if [ -n "${missing}" ]; then
        log_err "Detected incomplete HF snapshot (missing shard files). vLLM cannot start."
        echo "${missing}" | sed 's/^/  - /'
        log_info "Fix options:"
        log_info "  - Resume model download into this cache (recommended). If you have a mirror:"
        log_info "      export HF_ENDPOINT=https://hf-mirror.com"
        log_info "  - Or delete the incomplete snapshot dir and re-download."
        log_info "Snapshot: ${base_model}"
        exit 1
      fi
    fi
  else
    # No complete snapshot found. If we have an incomplete snapshot in the selected cache,
    # fail fast with an actionable message instead of letting vLLM crash later.
    if [[ "${base_model}" == */* ]]; then
      local org="${base_model%%/*}"
      local repo="${base_model##*/}"
      local hub_cache="${VLLM_HF_HUB_CACHE:-${HF_HUB_CACHE}}"
      local model_dir="${hub_cache}/models--${org}--${repo}"
      if [ -d "${model_dir}/snapshots" ]; then
        local latest
        latest=$(ls -1dt "${model_dir}/snapshots/"* 2>/dev/null | head -1 || true)
        if [ -n "${latest}" ] && [ -f "${latest}/model.safetensors.index.json" ]; then
          missing=$("${VLLM_PY}" - <<'PY' "${latest}" || true
import json, os, sys
snap=sys.argv[1]
idx=os.path.join(snap,"model.safetensors.index.json")
obj=json.load(open(idx,"r",encoding="utf-8"))
files=sorted(set((obj.get("weight_map") or {}).values()))
missing=[f for f in files if not os.path.isfile(os.path.join(snap,f))]
print("\n".join(missing))
raise SystemExit(0 if not missing else 2)
PY
)
          if [ -n "${missing}" ]; then
            log_err "HF snapshot exists but is incomplete (missing shard files)."
            echo "${missing}" | sed 's/^/  - /'
            log_info "Please prefetch/resume model download, then retry:"
            log_info "  ./deploy/scripts/pipeline.sh fetch-model --module ${module}"
            log_info "If huggingface.co is blocked, set mirror endpoint first:"
            log_info "  export HF_ENDPOINT=https://hf-mirror.com"
            exit 1
          fi
        fi
      fi
    fi
    # If we have a cache folder but snapshot looks incomplete, warn early with actionable hints.
    if [[ "${base_model}" == */* ]]; then
      local org="${base_model%%/*}"
      local repo="${base_model##*/}"
      local hub_cache="${VLLM_HF_HUB_CACHE:-${HF_HUB_CACHE}}"
      local cache_dir="${hub_cache}/models--${org}--${repo}"
      if [ -d "${cache_dir}" ]; then
        log_warn "Detected HF cache dir but snapshot seems incomplete (missing tokenizer/weights)."
        log_warn "Model serving may attempt to download from HuggingFace and fail in restricted networks."
        log_info "Cache dir: ${cache_dir}"
        log_info "Suggestions:"
        log_info "  - If you have a mirror, set: export HF_ENDPOINT=https://hf-mirror.com"
        log_info "  - Then rerun serve-model to allow download/resume."
        log_info "  - Or set VLLM_BASE_MODEL_${module^^} to a local full model directory."
      fi
    fi
    # Best-effort: if user is in restricted network, suggest using HF mirror/offline.
    if [ -n "${HF_ENDPOINT:-}" ]; then
      log_info "HF_ENDPOINT=${HF_ENDPOINT}"
    fi
  fi
  local served_name
  served_name="$(vllm_served_name_for "${module}")"

  local max_len
  max_len="$(vllm_max_model_len_for "${module}")"
  local mem_util
  mem_util="$(vllm_gpu_memory_utilization_for "${module}")"
  local eager
  eager="$(vllm_enforce_eager_for "${module}")"

  # Additional industrial knobs (optional)
  local max_num_seqs
  max_num_seqs="$(vllm_max_num_seqs_for "${module}")"
  local max_num_batched_tokens
  max_num_batched_tokens="$(vllm_max_num_batched_tokens_for "${module}")"
  local kv_cache_dtype
  kv_cache_dtype="$(vllm_kv_cache_dtype_for "${module}")"
  local vllm_dtype
  vllm_dtype="$(vllm_dtype_for "${module}")"
  local vllm_quant
  vllm_quant="$(vllm_quantization_for "${module}")"
  local vllm_load_format
  vllm_load_format="$(vllm_load_format_for "${module}")"
  local vllm_swap_space
  vllm_swap_space="$(vllm_swap_space_for "${module}")"
  local vllm_cpu_offload
  vllm_cpu_offload="$(vllm_cpu_offload_gb_for "${module}")"

  log_info "Starting vLLM model server (local python) for module=${module} ..."
  log_info "Endpoint: http://127.0.0.1:${port}/v1/models"
  log_info "Log:      ${log_file}"
  if [ -n "${VLLM_HF_HUB_CACHE}" ]; then
    log_info "HF_HUB_CACHE (vLLM): ${VLLM_HF_HUB_CACHE}"
  fi
  log_info "vLLM config: max_model_len=${max_len}, gpu_memory_utilization=${mem_util}, enforce_eager=${eager}"
  if [ -n "${max_num_seqs}" ] || [ -n "${max_num_batched_tokens}" ] || [ -n "${kv_cache_dtype}" ] || [ -n "${vllm_quant}" ] || [ -n "${vllm_load_format}" ] || [ -n "${vllm_swap_space}" ] || [ -n "${vllm_cpu_offload}" ]; then
    log_info "vLLM extra: max_num_seqs=${max_num_seqs:-<default>}, max_num_batched_tokens=${max_num_batched_tokens:-<default>}, kv_cache_dtype=${kv_cache_dtype:-<default>}, quantization=${vllm_quant:-<default>}, load_format=${vllm_load_format:-<default>}, swap_space=${vllm_swap_space:-<default>}, cpu_offload_gb=${vllm_cpu_offload:-<default>}"
  fi
  warn_proxy_for_localhost "${port}"

  # Start with a clean log for this run to avoid confusing mixed traces.
  : > "${log_file}"

  # Keep the command aligned with course instructions (OpenAI-compatible server + optional LoRA modules).
  # NOTE: This starts a background process and writes PID to ./pids/.
  local -a lora_pairs=()
  while IFS= read -r line; do
    if [ -n "$line" ]; then
      lora_pairs+=("$line")
    fi
  done < <(collect_lora_modules_for "${module}")

  local -a lora_args=()
  if [ ${#lora_pairs[@]} -gt 0 ]; then
    # vLLM defaults max_lora_rank=16; but our trained adapters may have r=32/64.
    # Auto-detect required rank from adapter_config.json to avoid:
    #   "LoRA rank 32 is greater than max_lora_rank 16"
    local max_rank
    max_rank="$(vllm_max_lora_rank_for_module "${module}")"
    if [ -n "${max_rank}" ]; then
      log_info "LoRA detected; setting vLLM --max-lora-rank=${max_rank} (override via VLLM_MAX_LORA_RANK_${module^^})"
      lora_args+=(--max-lora-rank "${max_rank}")
    fi
    local max_loras
    max_loras="$(vllm_max_loras_for "${module}")"
    if [ -n "${max_loras}" ]; then
      lora_args+=(--max-loras "${max_loras}")
    fi
    lora_args+=(--enable-lora --lora-modules)
    for p in "${lora_pairs[@]}"; do
      lora_args+=("$p")
    done
  fi

  local -a eager_args=()
  case "$(echo "${eager}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|y|on) eager_args+=(--enforce-eager) ;;
    0|false|no|n|off) eager_args+=(--no-enforce-eager) ;;
    *) eager_args+=(--enforce-eager) ;; # safe default
  esac

  local -a chat_template_args=()
  local chat_template
  chat_template="$(vllm_chat_template_for "${module}")"
  if [ -n "${chat_template}" ]; then
    if [ -f "${chat_template}" ]; then
      chat_template_args+=(--chat-template "${chat_template}")
      log_info "vLLM chat template: ${chat_template} (override via VLLM_CHAT_TEMPLATE_${module^^})"
    else
      log_warn "Configured vLLM chat template not found: ${chat_template} (skip)"
    fi
  fi

  # Optional: engine/scheduler/cache knobs for memory/throughput tuning
  local -a extra_args=()
  if [ -n "${max_num_seqs}" ]; then
    extra_args+=(--max-num-seqs "${max_num_seqs}")
  fi
  if [ -n "${max_num_batched_tokens}" ]; then
    extra_args+=(--max-num-batched-tokens "${max_num_batched_tokens}")
  fi
  if [ -n "${kv_cache_dtype}" ]; then
    extra_args+=(--kv-cache-dtype "${kv_cache_dtype}")
  fi
  if [ -n "${vllm_dtype}" ]; then
    extra_args+=(--dtype "${vllm_dtype}")
  fi
  if [ -n "${vllm_quant}" ]; then
    extra_args+=(--quantization "${vllm_quant}")
  fi
  if [ -n "${vllm_load_format}" ]; then
    extra_args+=(--load-format "${vllm_load_format}")
  fi
  if [ -n "${vllm_swap_space}" ]; then
    extra_args+=(--swap-space "${vllm_swap_space}")
  fi
  if [ -n "${vllm_cpu_offload}" ]; then
    extra_args+=(--cpu-offload-gb "${vllm_cpu_offload}")
  fi

  # Use dedicated vLLM python (may differ from training python).
  HF_HOME="${VLLM_HF_HOME:-${HF_HOME}}" HF_HUB_CACHE="${VLLM_HF_HUB_CACHE:-${HF_HUB_CACHE}}" \
  "${VLLM_PY}" -m vllm.entrypoints.openai.api_server \
      --model "${base_model}" \
      --served-model-name "${served_name}" \
      --host 0.0.0.0 \
      --port "${port}" \
      --max-model-len "${max_len}" \
      --gpu-memory-utilization "${mem_util}" \
      "${eager_args[@]}" \
      "${chat_template_args[@]}" \
      "${extra_args[@]}" \
      "${lora_args[@]}" \
      > "${log_file}" 2>&1 &

  local pid=$!
  echo "${pid}" > "${pid_file}"
  log_ok "Model server started (module=${module}, PID: ${pid})"
  # Always print a proxy-safe verify command (students often have ALL_PROXY set).
  log_info "Verify (proxy-safe):"
  log_info "  curl --noproxy '*' http://127.0.0.1:${port}/v1/models"
  # Best-effort probe (non-blocking; may be empty while model is still loading).
  local probe
  probe="$(probe_http_models_no_proxy "${port}" || true)"
  if [ -n "${probe}" ]; then
    log_ok "Startup probe (/v1/models): ${probe}"
  else
    log_info "Startup probe: model may still be loading; check logs if needed:"
    log_info "  ./deploy/scripts/pipeline.sh serve-model --module ${module} logs"
  fi
}

down_vllm_module() {
  ensure_dirs
  local module="$1"
  local pid_file
  pid_file="$(pid_file_for_model "${module}")"
  safe_kill_pid_file "${pid_file}"
  log_ok "Model server stopped (module=${module})"
}

logs_vllm_module() {
  ensure_dirs
  local module="$1"
  local log_file
  log_file="$(log_file_for_model "${module}")"
  if [ ! -f "${log_file}" ]; then
    log_warn "Log file not found yet: ${log_file}"
    exit 1
  fi
  exec tail -f "${log_file}"
}

case "$CMD" in
  kb)
    ensure_training_module_supported
    log_info "Building GraphRAG KB for module=$MODULE ..."
    run_py "training/modules/${MODULE}/graphrag/scripts/build_kb.py" "${PASSTHRU[@]}"
    ;;

  embed-index)
    ensure_training_module_supported
    log_info "Building retriever index (FAISS+BM25) for module=$MODULE ..."
    run_py "training/modules/${MODULE}/embedding/scripts/build_index.py" "${PASSTHRU[@]}"
    ;;

  datasets)
    ensure_training_module_supported
    log_info "Preparing datasets for module=$MODULE ..."
    SFT_ARGS=()
    while IFS= read -r line; do
      if [ -n "$line" ]; then
        SFT_ARGS+=("$line")
      fi
    done < <(filter_args_for_prepare_sft "${PASSTHRU[@]}")
    run_py "training/modules/${MODULE}/datasets/scripts/prepare_sft.py" "${SFT_ARGS[@]}"
    PREF_ARGS=()
    while IFS= read -r line; do
      # Guard: skip any empty line to avoid passing "" to argparse
      if [ -n "$line" ]; then
        PREF_ARGS+=("$line")
      fi
    done < <(filter_args_for_prepare_preferences "${PASSTHRU[@]}")
    run_py "training/modules/${MODULE}/datasets/scripts/prepare_preferences.py" "${PREF_ARGS[@]}"
    log_ok "Datasets prepared."
    ;;

  datasets-web)
    ensure_training_module_supported
    log_info "Fetching web (HF) datasets for module=$MODULE ..."
    run_py "training/modules/${MODULE}/datasets/scripts/fetch_web_sft_hf.py" "${PASSTHRU[@]}"
    log_ok "Web datasets fetched."
    ;;

  train-sft)
    ensure_training_module_supported
    log_info "Running SFT training wrapper for module=$MODULE ..."
    run_py "training/modules/${MODULE}/fine_tuning/scripts/train_sft.py" "${PASSTHRU[@]}"
    ;;

  train-dpo)
    ensure_training_module_supported
    log_info "Running DPO training wrapper for module=$MODULE ..."
    run_py "training/modules/${MODULE}/fine_tuning/scripts/train_dpo.py" "${PASSTHRU[@]}"
    ;;

  serve-model)
    if [ ${#PASSTHRU[@]} -lt 1 ]; then
      log_err "serve-model requires one arg: up|down|restart|logs|status"
      exit 1
    fi
    ACTION="${PASSTHRU[0]}"
    # Optional flags (parsed from PASSTHRU):
    #   --runtime vllm|docker
    #   --quantization awq|gptq|...        (enables vLLM --quantization)
    #   --quantized-model ORG/REPO|/path   (base model for this quantization)
    #   --load-format auto|...             (vLLM --load-format)
    #   --dtype bfloat16|float16|auto      (vLLM --dtype)
    RUNTIME="${SERVE_MODEL_RUNTIME:-vllm}"
    SERVE_QUANTIZATION=""
    SERVE_QUANTIZED_MODEL=""
    SERVE_LOAD_FORMAT=""
    SERVE_DTYPE=""
    i=1
    while [ $i -lt ${#PASSTHRU[@]} ]; do
      arg="${PASSTHRU[$i]}"
      case "${arg}" in
        --runtime)
          RUNTIME="${PASSTHRU[$((i+1))]:-}"; i=$((i+2));;
        --runtime=*)
          RUNTIME="${arg#--runtime=}"; i=$((i+1));;
        --quantization)
          SERVE_QUANTIZATION="${PASSTHRU[$((i+1))]:-}"; i=$((i+2));;
        --quantization=*)
          SERVE_QUANTIZATION="${arg#--quantization=}"; i=$((i+1));;
        --quantized-model)
          SERVE_QUANTIZED_MODEL="${PASSTHRU[$((i+1))]:-}"; i=$((i+2));;
        --quantized-model=*)
          SERVE_QUANTIZED_MODEL="${arg#--quantized-model=}"; i=$((i+1));;
        --load-format)
          SERVE_LOAD_FORMAT="${PASSTHRU[$((i+1))]:-}"; i=$((i+2));;
        --load-format=*)
          SERVE_LOAD_FORMAT="${arg#--load-format=}"; i=$((i+1));;
        --dtype)
          SERVE_DTYPE="${PASSTHRU[$((i+1))]:-}"; i=$((i+2));;
        --dtype=*)
          SERVE_DTYPE="${arg#--dtype=}"; i=$((i+1));;
        *)
          i=$((i+1));;
      esac
    done

    # `serve-model` supports all modules (including student modules), and also `--module all`.
    if [ "$MODULE" != "all" ] && ! is_valid_module "$MODULE"; then
      log_err "Unknown --module '${MODULE}' for serve-model. Supported: all, ${VALID_MODULES[*]}"
      exit 1
    fi

    # Apply one-shot env overrides for vLLM flags (per module).
    # Note: --dtype / --load-format are "top-level" knobs and work with or without quantization.
    apply_one_shot_serving_knobs() {
      local module="$1"
      if [ -n "${SERVE_LOAD_FORMAT}" ]; then
        export "VLLM_LOAD_FORMAT_${module^^}=${SERVE_LOAD_FORMAT}"
      fi
      if [ -n "${SERVE_DTYPE}" ]; then
        export "VLLM_DTYPE_${module^^}=${SERVE_DTYPE}"
      fi
    }
    if [ "$MODULE" = "all" ]; then
      for m in "${VALID_MODULES[@]}"; do
        apply_one_shot_serving_knobs "${m}"
      done
    else
      apply_one_shot_serving_knobs "${MODULE}"
    fi

    if [ -n "${SERVE_QUANTIZATION}" ]; then
      # Only enforce the presence of a quantized base-model mapping when we are actually
      # going to start/restart the server. For status/logs/down, allow inspection even if
      # the mapping is missing (avoid "just checking status is blocked").
      quant_requires_mapping="false"
      case "${ACTION}" in
        up|restart) quant_requires_mapping="true" ;;
        *) quant_requires_mapping="false" ;;
      esac

      if [ "$MODULE" = "all" ]; then
        if [ "${quant_requires_mapping}" = "true" ]; then
          log_err "--quantization is only supported with a single --module (not 'all')"
          exit 1
        fi
        log_warn "Ignoring --quantization with --module all for action=${ACTION} (status/logs/down only)."
      else
        export "VLLM_QUANTIZATION_${MODULE^^}=${SERVE_QUANTIZATION}"
        if [ -n "${SERVE_QUANTIZED_MODEL}" ]; then
          export "VLLM_BASE_MODEL_${MODULE^^}_${SERVE_QUANTIZATION^^}=${SERVE_QUANTIZED_MODEL}"
          # Persist so future runs can simply use `--quantization ...`.
          set_quantized_model_in_map "${MODULE}" "${SERVE_QUANTIZATION}" "${SERVE_QUANTIZED_MODEL}" >/dev/null 2>&1 || true
        else
          if [ "${quant_requires_mapping}" = "true" ]; then
            # Ensure we have a mapping; otherwise "one-click" won't know which base model to serve.
            qbase="$(resolve_quantized_base_model_for "${MODULE}" "${SERVE_QUANTIZATION}")"
            if [ -z "${qbase}" ]; then
              log_err "Missing quantized base model mapping for module=${MODULE} quantization=${SERVE_QUANTIZATION}."
              log_info "Fix options:"
              log_info "  1) Download + register once:"
              log_info "     ./deploy/scripts/pipeline.sh fetch-quantized-model --module ${MODULE} --quantization ${SERVE_QUANTIZATION} --model <ORG/REPO>"
              log_info "  2) Or pass it directly for this run:"
              log_info "     ./deploy/scripts/pipeline.sh serve-model --module ${MODULE} up --quantization ${SERVE_QUANTIZATION} --quantized-model <ORG/REPO|/path>"
              exit 1
            fi
          fi
        fi
      fi
    fi

    COMPOSE_FILE="training/modules/${MODULE}/serving/docker-compose.vllm.yml"
    status_vllm_module() {
      local module="$1"
      local port
      port="$(vllm_port_for "${module}")"
      local pid_file
      pid_file="$(pid_file_for_model "${module}")"
      local log_file
      log_file="$(log_file_for_model "${module}")"

      local pid=""
      if [ -f "${pid_file}" ]; then
        pid=$(cat "${pid_file}" 2>/dev/null || true)
      fi

      if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
        # Check TCP
        if python - <<PY >/dev/null 2>&1
import socket
s=socket.socket(); s.settimeout(0.3)
try:
  s.connect(("127.0.0.1", int(${port})))
  raise SystemExit(0)
except Exception:
  raise SystemExit(1)
finally:
  s.close()
PY
        then
          log_ok "model ${module}: RUNNING (pid=${pid}, port=${port})"
        else
          log_warn "model ${module}: STARTING (pid=${pid}, port=${port} not listening yet)"
          log_info "  Large models may take minutes to load; tail logs:"
          log_info "    ./deploy/scripts/pipeline.sh serve-model --module ${module} logs"
        fi
      else
        log_warn "model ${module}: STOPPED"
      fi

      if [ -f "${log_file}" ]; then
        log_info "  log: ${log_file}"
      fi
    }

    case "$ACTION" in
      up)
        case "${RUNTIME}" in
          vllm)
            if [ "$MODULE" = "all" ]; then
              for m in "${VALID_MODULES[@]}"; do
                start_vllm_module "${m}"
              done
            else
              start_vllm_module "${MODULE}"
            fi
            log_info "Note: model server starts in background and may take time to load weights."
            log_info "If curl shows empty reply / connection refused, wait and check logs:"
            log_info "  ./deploy/scripts/pipeline.sh serve-model --module ${MODULE} logs"
            ;;
          docker)
            if [ ! -f "$COMPOSE_FILE" ]; then
              log_err "Compose file not found: $COMPOSE_FILE"
              exit 1
            fi
            resolve_docker_compose || exit $?
            log_info "Starting vLLM model server (docker compose) for module=$MODULE ..."
            exec "${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" up -d
            ;;
          auto|*)
            if resolve_docker_compose >/dev/null 2>&1; then
              if [ ! -f "$COMPOSE_FILE" ]; then
                log_err "Compose file not found: $COMPOSE_FILE"
                exit 1
              fi
              log_info "Starting vLLM model server (docker compose) for module=$MODULE ..."
              exec "${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" up -d
            fi
            if [ "$MODULE" = "all" ]; then
              for m in "${VALID_MODULES[@]}"; do
                start_vllm_module "${m}"
              done
            else
              start_vllm_module "${MODULE}"
            fi
            ;;
        esac
        ;;
      down)
        case "${RUNTIME}" in
          docker)
            if [ ! -f "$COMPOSE_FILE" ]; then
              log_err "Compose file not found: $COMPOSE_FILE"
              exit 1
            fi
            resolve_docker_compose || exit $?
            log_info "Stopping vLLM model server (docker compose) for module=$MODULE ..."
            exec "${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" down
            ;;
          vllm|auto|*)
            if [ "$MODULE" = "all" ]; then
              for m in "${VALID_MODULES[@]}"; do
                down_vllm_module "${m}"
              done
            else
              down_vllm_module "${MODULE}"
            fi
            ;;
        esac
        ;;
      restart)
        case "${RUNTIME}" in
          docker)
            if [ ! -f "$COMPOSE_FILE" ]; then
              log_err "Compose file not found: $COMPOSE_FILE"
              exit 1
            fi
            resolve_docker_compose || exit $?
            log_info "Restarting vLLM model server (docker compose) for module=$MODULE ..."
            "${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" down
            exec "${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" up -d
            ;;
          vllm|auto|*)
            if [ "$MODULE" = "all" ]; then
              for m in "${VALID_MODULES[@]}"; do
                down_vllm_module "${m}"
              done
              for m in "${VALID_MODULES[@]}"; do
                start_vllm_module "${m}"
              done
            else
              down_vllm_module "${MODULE}"
              start_vllm_module "${MODULE}"
            fi
            ;;
        esac
        ;;
      logs)
        case "${RUNTIME}" in
          docker)
            if [ ! -f "$COMPOSE_FILE" ]; then
              log_err "Compose file not found: $COMPOSE_FILE"
              exit 1
            fi
            resolve_docker_compose || exit $?
            log_info "Tailing vLLM logs for module=$MODULE (docker compose) ..."
            exec "${DOCKER_COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" logs -f
            ;;
          vllm|auto|*)
            if [ "$MODULE" = "all" ]; then
              log_info "Logs are per-module under ./logs/. Tail one module at a time:"
              for m in "${VALID_MODULES[@]}"; do
                log_info "  ./deploy/scripts/pipeline.sh serve-model --module ${m} logs"
              done
              exit 0
            fi
            log_info "Tailing vLLM logs for module=$MODULE (local python) ..."
            logs_vllm_module "${MODULE}"
            ;;
        esac
        ;;
      status)
        if [ "$MODULE" = "all" ]; then
          for m in "${VALID_MODULES[@]}"; do
            status_vllm_module "${m}"
          done
        else
          status_vllm_module "${MODULE}"
        fi
        ;;
      *)
        log_err "Unknown serve-model action: $ACTION"
        exit 1
        ;;
    esac
    ;;

  eval-model)
    # Evaluate OpenAI-compatible model server.
    # Tony has a complete implementation; other modules provide a small curated eval set.
    if [ "$MODULE" != "all" ] && ! is_valid_module "$MODULE"; then
      log_err "Unknown --module '${MODULE}' for eval-model. Supported: all, ${VALID_MODULES[*]}"
      exit 1
    fi
    if [ "$MODULE" = "all" ]; then
      for m in "${VALID_MODULES[@]}"; do
        log_info "Evaluating model for module=${m} ..."
        run_py "training/modules/${m}/eval/run_model_eval.py" --module "${m}" "${PASSTHRU[@]}"
      done
    else
      run_py "training/modules/${MODULE}/eval/run_model_eval.py" --module "${MODULE}" "${PASSTHRU[@]}"
    fi
    ;;

  fetch-model)
    # Prefetch the base model into HF cache for vLLM (resumable).
    if [ "$MODULE" != "all" ] && ! is_valid_module "$MODULE"; then
      log_err "Unknown --module '${MODULE}' for fetch-model. Supported: all, ${VALID_MODULES[*]}"
      exit 1
    fi
    check_vllm_available_or_exit
    select_vllm_hf_cache
    log_info "Unified HF cache (classroom):"
    log_info "  HF_HOME=${HF_HOME}"
    log_info "  HF_HUB_CACHE=${HF_HUB_CACHE}"
    do_fetch_one() {
      local module="$1"
      local model_id
      model_id="$(vllm_base_model_for "${module}")"
      if [[ "${model_id}" != */* ]]; then
        log_warn "fetch-model only supports HF repo ids (ORG/REPO). Got: ${model_id}"
        return 0
      fi
      log_info "Prefetching base model for module=${module}: ${model_id}"
      log_info "HF_HUB_CACHE (vLLM): ${VLLM_HF_HUB_CACHE}"
      HF_HOME="${VLLM_HF_HOME:-${HF_HOME}}" HF_HUB_CACHE="${VLLM_HF_HUB_CACHE:-${HF_HUB_CACHE}}" \
        "${VLLM_PY}" - <<'PY' "${model_id}"
import os, sys
from huggingface_hub import HfApi, snapshot_download

def snapshot_complete(path: str) -> bool:
  if not os.path.isdir(path):
    return False
  if not os.path.isfile(os.path.join(path, "config.json")):
    return False
  # tokenizer can be tokenizer.json or vocab/merges; require tokenizer_config at minimum
  if not any(name.startswith("tokenizer.") for name in os.listdir(path)) and not os.path.isfile(os.path.join(path, "tokenizer_config.json")):
    return False
  # single-file weights
  names = set(os.listdir(path))
  if any(n.endswith(".safetensors") for n in names) or any(n.startswith("pytorch_model") and n.endswith(".bin") for n in names):
    return True
  # sharded weights
  import json
  for idx_name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
    idx = os.path.join(path, idx_name)
    if os.path.isfile(idx):
      obj = json.load(open(idx, "r", encoding="utf-8"))
      files = set((obj.get("weight_map") or {}).values())
      return all(os.path.isfile(os.path.join(path, f)) for f in files)
  return False

model_id = sys.argv[1]
revision = os.environ.get("HF_REVISION") or "main"
hub_cache = os.environ.get("HF_HUB_CACHE")  # used by huggingface_hub
print("revision:", revision)
print("HF_HUB_CACHE:", hub_cache)

# Determine remote commit SHA for this revision (version check).
sha = None
try:
  info = HfApi().model_info(model_id, revision=revision)
  sha = getattr(info, "sha", None)
  if sha:
    print("remote sha:", sha)
except Exception as e:
  print("warn: cannot fetch remote sha (offline or blocked):", repr(e))

def cache_paths(repo_id: str):
  org, repo = repo_id.split("/", 1)
  base = os.path.join(hub_cache, f"models--{org}--{repo}")
  return base, os.path.join(base, "snapshots"), os.path.join(base, "refs")

if hub_cache:
  base, snaps, refs = cache_paths(model_id)
  # If remote sha known, and local snapshot exists+complete => skip download.
  if sha:
    snap = os.path.join(snaps, sha)
    if snapshot_complete(snap):
      os.makedirs(refs, exist_ok=True)
      with open(os.path.join(refs, revision), "w", encoding="utf-8") as f:
        f.write(sha)
      print("already complete; skip download:", snap)
      raise SystemExit(0)
  # If refs pin exists and points to a complete snapshot => skip download.
  try:
    ref_path = os.path.join(refs, revision)
    if os.path.isfile(ref_path):
      pinned = open(ref_path, "r", encoding="utf-8").read().strip()
      snap = os.path.join(snaps, pinned)
      if snapshot_complete(snap):
        print("already complete (pinned); skip download:", snap)
        raise SystemExit(0)
  except Exception:
    pass

print("snapshot_download:", model_id, "revision=", revision, "(resume)")
path = snapshot_download(repo_id=model_id, revision=revision, resume_download=True)
print("done:", path)
if snapshot_complete(path):
  print("snapshot complete: yes")
else:
  print("snapshot complete: unknown/no (may still be downloading)")
PY
    }
    if [ "$MODULE" = "all" ]; then
      for m in "${VALID_MODULES[@]}"; do
        do_fetch_one "${m}"
      done
    else
      do_fetch_one "${MODULE}"
    fi
    log_ok "Prefetch finished."
    ;;

  fetch-quantized-model)
    # Prefetch a quantized base model (AWQ/GPTQ/...) into HF cache for vLLM and persist mapping.
    # Usage:
    #   ./deploy/scripts/pipeline.sh fetch-quantized-model --module tony --quantization awq --model <ORG/REPO>
    if [ "$MODULE" = "all" ]; then
      log_err "fetch-quantized-model requires a single --module (not 'all')"
      exit 1
    fi
    if ! is_valid_module "$MODULE"; then
      log_err "Unknown --module '${MODULE}' for fetch-quantized-model. Supported: ${VALID_MODULES[*]}"
      exit 1
    fi

    # Parse passthru flags.
    Q_QUANT=""
    Q_MODEL=""
    Q_REV=""
    i=0
    while [ $i -lt ${#PASSTHRU[@]} ]; do
      arg="${PASSTHRU[$i]}"
      case "${arg}" in
        --quantization)
          Q_QUANT="${PASSTHRU[$((i+1))]:-}"; i=$((i+2));;
        --quantization=*)
          Q_QUANT="${arg#--quantization=}"; i=$((i+1));;
        --model)
          Q_MODEL="${PASSTHRU[$((i+1))]:-}"; i=$((i+2));;
        --model=*)
          Q_MODEL="${arg#--model=}"; i=$((i+1));;
        --revision)
          Q_REV="${PASSTHRU[$((i+1))]:-}"; i=$((i+2));;
        --revision=*)
          Q_REV="${arg#--revision=}"; i=$((i+1));;
        *)
          i=$((i+1));;
      esac
    done
    if [ -z "${Q_QUANT}" ]; then
      log_err "fetch-quantized-model requires --quantization <awq|gptq|...>"
      exit 1
    fi
    if [ -z "${Q_MODEL}" ]; then
      # Allow using previously registered mapping as default.
      Q_MODEL="$(resolve_quantized_base_model_for "${MODULE}" "${Q_QUANT}")"
    fi
    if [ -z "${Q_MODEL}" ]; then
      log_err "fetch-quantized-model requires --model <ORG/REPO> (quantized base model repo id) or an existing mapping."
      log_info "Example:"
      log_info "  ./deploy/scripts/pipeline.sh fetch-quantized-model --module ${MODULE} --quantization ${Q_QUANT} --model <ORG/REPO>"
      exit 1
    fi

    check_vllm_available_or_exit
    select_vllm_hf_cache
    log_info "Unified HF cache (classroom):"
    log_info "  HF_HOME=${HF_HOME}"
    log_info "  HF_HUB_CACHE=${HF_HUB_CACHE}"
    log_info "Prefetching quantized model for module=${MODULE} quantization=${Q_QUANT}: ${Q_MODEL}"
    if [ -n "${Q_REV}" ]; then
      log_info "revision=${Q_REV}"
    fi

    # If local dir, just record mapping.
    if [ -d "${Q_MODEL}" ]; then
      set_quantized_model_in_map "${MODULE}" "${Q_QUANT}" "${Q_MODEL}" >/dev/null 2>&1 || true
      log_ok "Registered local quantized model dir."
      log_info "Mapping file: $(quant_map_file)"
      exit 0
    fi

    if [[ "${Q_MODEL}" != */* ]]; then
      log_err "Quantized model must be a local dir or HF repo id ORG/REPO. Got: ${Q_MODEL}"
      exit 1
    fi

    # Reuse the same resumable snapshot logic as fetch-model.
    if [ -n "${Q_REV}" ]; then
      export HF_REVISION="${Q_REV}"
    fi
    HF_HOME="${VLLM_HF_HOME:-${HF_HOME}}" HF_HUB_CACHE="${VLLM_HF_HUB_CACHE:-${HF_HUB_CACHE}}" \
      "${VLLM_PY}" - <<'PY' "${Q_MODEL}"
import os, sys
from huggingface_hub import HfApi, snapshot_download

def snapshot_complete(path: str) -> bool:
  if not os.path.isdir(path):
    return False
  if not os.path.isfile(os.path.join(path, "config.json")):
    return False
  if not any(name.startswith("tokenizer.") for name in os.listdir(path)) and not os.path.isfile(os.path.join(path, "tokenizer_config.json")):
    return False
  names = set(os.listdir(path))
  if any(n.endswith(".safetensors") for n in names) or any(n.startswith("pytorch_model") and n.endswith(".bin") for n in names):
    return True
  import json
  for idx_name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
    idx = os.path.join(path, idx_name)
    if os.path.isfile(idx):
      obj = json.load(open(idx, "r", encoding="utf-8"))
      files = set((obj.get("weight_map") or {}).values())
      return all(os.path.isfile(os.path.join(path, f)) for f in files)
  return False

model_id = sys.argv[1]
revision = os.environ.get("HF_REVISION") or "main"
hub_cache = os.environ.get("HF_HUB_CACHE")
print("revision:", revision)
print("HF_HUB_CACHE:", hub_cache)

sha = None
try:
  info = HfApi().model_info(model_id, revision=revision)
  sha = getattr(info, "sha", None)
  if sha:
    print("remote sha:", sha)
except Exception as e:
  print("warn: cannot fetch remote sha (offline or blocked):", repr(e))

def cache_paths(repo_id: str):
  org, repo = repo_id.split("/", 1)
  base = os.path.join(hub_cache, f"models--{org}--{repo}")
  return base, os.path.join(base, "snapshots"), os.path.join(base, "refs")

if hub_cache:
  base, snaps, refs = cache_paths(model_id)
  if sha:
    snap = os.path.join(snaps, sha)
    if snapshot_complete(snap):
      os.makedirs(refs, exist_ok=True)
      with open(os.path.join(refs, revision), "w", encoding="utf-8") as f:
        f.write(sha)
      print("already complete; skip download:", snap)
      raise SystemExit(0)
  try:
    ref_path = os.path.join(refs, revision)
    if os.path.isfile(ref_path):
      pinned = open(ref_path, "r", encoding="utf-8").read().strip()
      snap = os.path.join(snaps, pinned)
      if snapshot_complete(snap):
        print("already complete (pinned); skip download:", snap)
        raise SystemExit(0)
  except Exception:
    pass

print("snapshot_download:", model_id, "revision=", revision, "(resume)")
path = snapshot_download(repo_id=model_id, revision=revision, resume_download=True)
print("done:", path)
print("snapshot complete:", "yes" if snapshot_complete(path) else "unknown/no")
PY

    set_quantized_model_in_map "${MODULE}" "${Q_QUANT}" "${Q_MODEL}" >/dev/null 2>&1 || true
    log_ok "Quantized model prefetched and mapping registered."
    log_info "Mapping file: $(quant_map_file)"
    log_info "One-click serve:"
    log_info "  ./deploy/scripts/pipeline.sh serve-model --module ${MODULE} up --quantization ${Q_QUANT}"
    ;;

  *)
    log_err "Unknown command: $CMD"
    usage
    exit 1
    ;;
esac

