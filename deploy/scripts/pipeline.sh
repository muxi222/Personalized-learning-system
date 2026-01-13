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
  serve-model   Start/stop model server (module-specific; currently vLLM docker compose for tony)
  help          Show this help

Common flags:
  --module <default|rpj|xmx|wzy|wzm|tony>   Which module pipeline to run

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
# HuggingFace cache location (models/datasets) - make it stable and repo-local.
#
# Desired example path:
#   <repo>/data/.cache/huggingface/hub/models--ORG--REPO/snapshots/<sha>
#
# This avoids writing to ~/.cache/ in shared environments and makes downloads reusable
# across repeated pipeline runs (resumable HuggingFace Hub cache).
# -----------------------------------------------------------------------------
export HF_HOME="${PROJECT_ROOT}/data/.cache/huggingface"
export HF_HUB_CACHE="${HF_HOME}/hub"
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

# Optional: a stable, human-visible model directory.
# Training scripts can prefer loading from here (fully local) once downloaded.
export HF_MODEL_LOCAL_DIR="${HF_MODEL_LOCAL_DIR:-${PROJECT_ROOT}/data/models/hf}"
mkdir -p "${HF_MODEL_LOCAL_DIR}"

resolve_python() {
  # 1) explicit override
  if [ -n "${PYTHON:-}" ]; then
    echo "${PYTHON}"
    return 0
  fi

  # 2) common training env path in this repo's deployments (more robust than relying on `conda` on PATH)
  if [ -x "/home/dataset-assist-0/data/conda/envs/312_edu/bin/python" ]; then
    echo "/home/dataset-assist-0/data/conda/envs/312_edu/bin/python"
    return 0
  fi

  # 2) prefer conda env if available (matches start.sh convention)
  if command -v conda >/dev/null 2>&1; then
    if conda env list 2>/dev/null | awk '{print $1}' | grep -qx "312_edu"; then
      echo "conda-run"
      return 0
    fi
  fi

  # 3) fallback
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

ensure_module_supported() {
  if [ "$MODULE" != "tony" ]; then
    log_err "Module '$MODULE' pipeline is TODO/student-only. Only 'tony' is fully implemented."
    log_info "You can use the Tony scripts as reference: training/modules/tony/..."
    exit 1
  fi
}

case "$CMD" in
  kb)
    ensure_module_supported
    log_info "Building GraphRAG KB for module=$MODULE ..."
    run_py "training/modules/${MODULE}/graphrag/scripts/build_kb.py" "${PASSTHRU[@]}"
    ;;

  embed-index)
    ensure_module_supported
    log_info "Building retriever index (FAISS+BM25) for module=$MODULE ..."
    run_py "training/modules/${MODULE}/embedding/scripts/build_index.py" "${PASSTHRU[@]}"
    ;;

  datasets)
    ensure_module_supported
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
    ensure_module_supported
    log_info "Fetching web (HF) datasets for module=$MODULE ..."
    run_py "training/modules/${MODULE}/datasets/scripts/fetch_web_sft_hf.py" "${PASSTHRU[@]}"
    log_ok "Web datasets fetched."
    ;;

  train-sft)
    ensure_module_supported
    log_info "Running SFT training wrapper for module=$MODULE ..."
    run_py "training/modules/${MODULE}/fine_tuning/scripts/train_sft.py" "${PASSTHRU[@]}"
    ;;

  train-dpo)
    ensure_module_supported
    log_info "Running DPO training wrapper for module=$MODULE ..."
    run_py "training/modules/${MODULE}/fine_tuning/scripts/train_dpo.py" "${PASSTHRU[@]}"
    ;;

  serve-model)
    ensure_module_supported
    if [ ${#PASSTHRU[@]} -lt 1 ]; then
      log_err "serve-model requires one arg: up|down|restart|logs"
      exit 1
    fi
    ACTION="${PASSTHRU[0]}"
    COMPOSE_FILE="training/modules/${MODULE}/serving/docker-compose.vllm.yml"
    if [ ! -f "$COMPOSE_FILE" ]; then
      log_err "Compose file not found: $COMPOSE_FILE"
      exit 1
    fi
    case "$ACTION" in
      up)
        log_info "Starting vLLM model server (docker compose) for module=$MODULE ..."
        exec docker compose -f "$COMPOSE_FILE" up -d
        ;;
      down)
        log_info "Stopping vLLM model server (docker compose) for module=$MODULE ..."
        exec docker compose -f "$COMPOSE_FILE" down
        ;;
      restart)
        log_info "Restarting vLLM model server (docker compose) for module=$MODULE ..."
        docker compose -f "$COMPOSE_FILE" down
        exec docker compose -f "$COMPOSE_FILE" up -d
        ;;
      logs)
        log_info "Tailing vLLM logs for module=$MODULE ..."
        exec docker compose -f "$COMPOSE_FILE" logs -f
        ;;
      *)
        log_err "Unknown serve-model action: $ACTION"
        exit 1
        ;;
    esac
    ;;

  *)
    log_err "Unknown command: $CMD"
    usage
    exit 1
    ;;
esac

