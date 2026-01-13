#!/bin/bash
# =============================================================================
# MCP services startup (local/conda)
#
# Purpose:
# - Start/stop MCP servers used by backend agents (Phase 1: retrieval-mcp).
# - Keep the MCP process lifecycle independent from API/Agent/Frontend processes.
#
# Usage:
#   ./deploy/scripts/start_mcp.sh help
#
#   # Phase 1: Tony retrieval MCP (FAISS+BM25 + GraphRAG expansion + DB fetch)
#   ./deploy/scripts/start_mcp.sh tony_retrieval up
#   ./deploy/scripts/start_mcp.sh tony_retrieval status
#   ./deploy/scripts/start_mcp.sh tony_retrieval down
#
# Notes:
# - Default endpoint: http://127.0.0.1:7010/mcp
# - Enable in backend processes:
#     export MCP_RETRIEVAL_ENABLED=true
#     export MCP_RETRIEVAL_URL=http://127.0.0.1:7010/mcp
# - GraphRAG expansion is controlled by:
#     export GRAPHRAG_ENABLED=true
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { printf "${BLUE}[INFO]${NC} %s\n" "$1"; }
log_success() { printf "${GREEN}[SUCCESS]${NC} %s\n" "$1"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
log_error() { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PID_DIR="${PROJECT_ROOT}/pids"
LOG_DIR="${PROJECT_ROOT}/logs"

ensure_dirs() {
  mkdir -p "${PID_DIR}" "${LOG_DIR}"
}

check_port_free() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    if lsof -Pi :"${port}" -sTCP:LISTEN -t >/dev/null 2>&1; then
      return 1
    fi
  fi
  return 0
}

pid_file_for() {
  local name="$1"
  echo "${PID_DIR}/mcp_${name}.pid"
}

safe_kill_pid_file() {
  local pid_file="$1"
  if [ -f "${pid_file}" ]; then
    local pid
    pid=$(cat "${pid_file}" 2>/dev/null || true)
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      sleep 1
      if kill -0 "${pid}" 2>/dev/null; then
        kill -9 "${pid}" 2>/dev/null || true
      fi
    fi
    rm -f "${pid_file}"
  fi
}

setup_conda() {
  if ! command -v conda >/dev/null 2>&1; then
    log_error "Conda 未安装"
    exit 1
  fi
  eval "$(conda shell.bash hook)"
  conda activate 312_edu 2>/dev/null || {
    log_error "Conda 环境 312_edu 不存在"
    exit 1
  }
  # Best-effort deps sync (keeps script self-contained)
  if [ -f "${PROJECT_ROOT}/requirements.txt" ]; then
    pip install -q -r "${PROJECT_ROOT}/requirements.txt" 2>/dev/null || true
  fi
}

start_tony_retrieval() {
  ensure_dirs
  setup_conda

  local port="7010"
  local pid_file
  pid_file="$(pid_file_for "tony_retrieval")"
  local log_file="${LOG_DIR}/mcp_tony_retrieval.log"

  # Clean stale pid file
  if [ -f "${pid_file}" ]; then
    local old_pid
    old_pid=$(cat "${pid_file}" 2>/dev/null || true)
    if [ -n "${old_pid}" ] && kill -0 "${old_pid}" 2>/dev/null; then
      log_warn "tony_retrieval 已在运行 (PID: ${old_pid})"
      log_info "URL: http://127.0.0.1:${port}/mcp"
      return 0
    fi
    rm -f "${pid_file}"
  fi

  if ! check_port_free "${port}"; then
    log_error "端口 ${port} 已被占用，无法启动 tony_retrieval MCP"
    exit 1
  fi

  cd "${PROJECT_ROOT}"
  export PYTHONPATH="${PROJECT_ROOT}/backend:${PYTHONPATH:+:$PYTHONPATH}"

  # Load .env (optional)
  if [ -f "${PROJECT_ROOT}/.env" ]; then
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
  fi

  log_info "启动 tony_retrieval MCP (port=${port})..."
  # We do NOT use uvicorn directly; FastMCP runs uvicorn internally for streamable-http.
  conda run -n 312_edu --no-capture-output python -m backend.mcp_servers.tony.retrieval_server \
    > "${log_file}" 2>&1 &
  local pid=$!
  echo "${pid}" > "${pid_file}"
  log_success "tony_retrieval MCP 已启动 (PID: ${pid})"
  log_info "URL: http://127.0.0.1:${port}/mcp"
  log_info "Log: ${log_file}"
}

status_tony_retrieval() {
  local pid_file
  pid_file="$(pid_file_for "tony_retrieval")"
  if [ -f "${pid_file}" ]; then
    local pid
    pid=$(cat "${pid_file}" 2>/dev/null || true)
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
      log_success "tony_retrieval MCP 运行中 (PID: ${pid})"
      log_info "URL: http://127.0.0.1:7010/mcp"
      return 0
    fi
    log_warn "PID 文件存在但进程未运行，清理: ${pid_file}"
    rm -f "${pid_file}"
  fi
  log_warn "tony_retrieval MCP 未运行"
}

down_tony_retrieval() {
  ensure_dirs
  local pid_file
  pid_file="$(pid_file_for "tony_retrieval")"
  safe_kill_pid_file "${pid_file}"
  log_success "tony_retrieval MCP 已停止"
}

show_help() {
  cat <<'EOF'
MCP startup script

Usage:
  ./deploy/scripts/start_mcp.sh <service> <up|down|status>

Services:
  tony_retrieval   Phase 1 retrieval-mcp (port 7010)

Examples:
  ./deploy/scripts/start_mcp.sh tony_retrieval up
  ./deploy/scripts/start_mcp.sh tony_retrieval status
  ./deploy/scripts/start_mcp.sh tony_retrieval down
EOF
}

main() {
  local svc="${1:-help}"
  local action="${2:-help}"

  case "${svc}" in
    help|--help|-h)
      show_help
      ;;
    tony_retrieval)
      case "${action}" in
        up) start_tony_retrieval ;;
        down) down_tony_retrieval ;;
        status) status_tony_retrieval ;;
        *) show_help; exit 1 ;;
      esac
      ;;
    *)
      show_help
      exit 1
      ;;
  esac
}

main "$@"

