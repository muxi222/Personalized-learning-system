#!/bin/bash
# =============================================================================
# 单模块启动脚本 - 用于启动独立的模块服务
#
# 用法:
#   ./start_module.sh api rpj       # 启动 RPJ 模块 API
#   ./start_module.sh agent tony    # 启动 TONY 模块 Agent
#
# 特点:
#   - 每个模块独立运行，互不影响
#   - Ctrl+C 只停止当前模块
#   - 支持多个模块同时运行
# =============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 根据模块名获取端口号
get_module_port() {
    case "$1" in
        default) echo "6100" ;;
        rpj)  echo "6001" ;;
        xmx)  echo "6002" ;;
        wzy)  echo "6003" ;;
        wzm)  echo "6004" ;;
        tony) echo "6005" ;;
        *)    echo "" ;;
    esac
}

# 根据模块名获取学科列表
get_module_subjects() {
    case "$1" in
        default) echo "所有学科（跨学科查询）" ;;
        rpj)  echo "语文、英语、政治" ;;
        xmx)  echo "经济学" ;;
        wzy)  echo "数学、物理" ;;
        wzm)  echo "化学" ;;
        tony) echo "历史、地理、其他" ;;
        *)    echo "" ;;
    esac
}

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PID_DIR="${PROJECT_ROOT}/pids"

log_info() {
    printf "${BLUE}[INFO]${NC} %s\n" "$1"
}

log_success() {
    printf "${GREEN}[SUCCESS]${NC} %s\n" "$1"
}

log_warn() {
    printf "${YELLOW}[WARN]${NC} %s\n" "$1"
}

log_error() {
    printf "${RED}[ERROR]${NC} %s\n" "$1"
}

log_module() {
    local module=$1
    shift
    printf "${CYAN}[%s]${NC} %s\n" "$(echo "$module" | tr '[:lower:]' '[:upper:]')" "$*"
}

# 检查端口是否被占用
check_port() {
    local port=$1
    if lsof -Pi :${port} -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # 端口被占用
    else
        return 1  # 端口可用
    fi
}

# 获取占用端口的进程信息
get_port_process() {
    local port=$1
    lsof -Pi :${port} -sTCP:LISTEN | tail -n +2 | awk '{print $2, $1}' | head -1
}

# 确保PID目录存在
mkdir -p "${PID_DIR}"

# 加载环境变量
if [ -f "${PROJECT_ROOT}/.env" ]; then
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
fi

# Default feature flags (can be overridden by .env / exported env)
if [ -z "${COMPANION_REQUIRE_SUBJECT_MODEL:-}" ]; then
    export COMPANION_REQUIRE_SUBJECT_MODEL=true
fi

# 激活 Conda 环境
eval "$(conda shell.bash hook)"
conda activate 312_edu 2>/dev/null || {
    log_error "Conda 环境 312_edu 不存在"
    exit 1
}

# 参数解析
SERVICE_TYPE=$1  # api 或 agent
MODULE=$2        # rpj, xmx, wzy, wzm, tony

if [ -z "$SERVICE_TYPE" ] || [ -z "$MODULE" ]; then
    echo "用法: $0 <service_type> <module>"
    echo "  service_type: api 或 agent"
    echo "  module: default, rpj, xmx, wzy, wzm, tony"
    exit 1
fi

PORT=$(get_module_port "$MODULE")
SUBJECTS=$(get_module_subjects "$MODULE")

if [ -z "$PORT" ]; then
    log_error "未知模块: $MODULE"
    exit 1
fi

cd "${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}/backend:${PYTHONPATH:+:$PYTHONPATH}"

PID_FILE="${PID_DIR}/${SERVICE_TYPE}_${MODULE}.pid"
LOG_FILE="${PROJECT_ROOT}/logs/${MODULE}_${SERVICE_TYPE}.log"

# 检查是否已经运行
if [ -f "${PID_FILE}" ]; then
    OLD_PID=$(cat "${PID_FILE}")
    if kill -0 "${OLD_PID}" 2>/dev/null; then
        log_error "${MODULE} ${SERVICE_TYPE} 已经在运行 (PID: ${OLD_PID})"
        log_info "如需重启，请先运行: ./start.sh stop_${MODULE}"
        exit 1
    else
        # 清理旧的PID文件
        log_warn "发现旧的PID文件，正在清理..."
        rm -f "${PID_FILE}"
    fi
fi

# 如果是 API 服务，检查端口是否被占用
if [ "$SERVICE_TYPE" = "api" ]; then
    if check_port "$PORT"; then
        PROCESS_INFO=$(get_port_process "$PORT")
        OCCUPYING_PID=$(echo "$PROCESS_INFO" | awk '{print $1}')
        OCCUPYING_NAME=$(echo "$PROCESS_INFO" | awk '{print $2}')

        log_error "端口 ${PORT} 已被占用！"
        log_error "占用进程: ${OCCUPYING_NAME} (PID: ${OCCUPYING_PID})"
        echo ""
        log_info "解决方案："
        log_info "  1. 停止占用端口的进程: kill ${OCCUPYING_PID}"
        log_info "  2. 或使用停止脚本: ./start.sh stop_${MODULE}"
        echo ""
        exit 1
    fi
fi

# 当前进程的PID列表（用于Ctrl+C清理）
CHILD_PID=""

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

# Kill a PID and all its descendants.
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

# 清理函数
cleanup() {
    local exit_code=$?
    if [ -n "${CHILD_PID}" ]; then
        log_info "正在停止 ${MODULE} ${SERVICE_TYPE} (PID: ${CHILD_PID})..."
        # Kill process tree first (conda run wrapper may not forward signals)
        kill_tree "${CHILD_PID}" "TERM"
        # Also try killing process group if applicable
        kill -TERM -- "-${CHILD_PID}" 2>/dev/null || true
        sleep 1
        kill_tree "${CHILD_PID}" "KILL"
        kill -KILL -- "-${CHILD_PID}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
    exit $exit_code
}

trap cleanup INT TERM EXIT

# 启动服务
if [ "$SERVICE_TYPE" = "api" ]; then
    log_module "$MODULE" "启动 API 服务 (端口: $PORT, 学科: $SUBJECTS)..."

    # NOTE: scope --reload to the code directory only. Watching PROJECT_ROOT
    # (the default) includes logs/ and data/, and since the service writes its
    # own log into logs/ this creates an infinite reload loop (the port never
    # opens). RELOAD=false in .env disables hot-reload entirely.
    # Exclude __pycache__ to prevent reload loops from Python bytecode updates.
    RELOAD_ARGS="--reload --reload-dir ${PROJECT_ROOT}/backend --reload-exclude '**/__pycache__/*' --reload-exclude '**/*.pyc'"
    if [ "${RELOAD:-true}" = "false" ]; then
        RELOAD_ARGS=""
    fi
    conda run -n 312_edu --no-capture-output uvicorn \
        "backend.modules.${MODULE}.main:app" \
        --host ${HOST:-0.0.0.0} \
        --port ${PORT} \
        ${RELOAD_ARGS} > "${LOG_FILE}" 2>&1 &

    CHILD_PID=$!
    echo $CHILD_PID > "${PID_FILE}"

    log_module "$MODULE" "API 服务已启动 (PID: $CHILD_PID)"

    # 等待服务启动
    log_info "等待服务启动..."
    sleep 3

    # 检查进程是否还在运行
    if ! kill -0 "${CHILD_PID}" 2>/dev/null; then
        log_error "API 服务启动失败！进程已退出"
        log_info "请查看日志文件: ${LOG_FILE}"
        echo ""
        log_info "最近的错误日志："
        tail -20 "${LOG_FILE}"
        rm -f "${PID_FILE}"
        exit 1
    fi

    # 检查端口是否监听
    if ! check_port "$PORT"; then
        log_warn "端口 ${PORT} 尚未监听，服务可能还在启动中..."
        log_info "请等待几秒后访问，或查看日志: ${LOG_FILE}"
    fi

    log_module "$MODULE" "访问地址: http://localhost:${PORT}"
    log_module "$MODULE" "API 文档: http://localhost:${PORT}/docs"
    log_module "$MODULE" "日志文件: ${LOG_FILE}"

elif [ "$SERVICE_TYPE" = "agent" ]; then
    QUEUE="queue_${MODULE}"
    log_module "$MODULE" "启动 Agent Worker (队列: $QUEUE, 学科: $SUBJECTS)..."

    conda run -n 312_edu --no-capture-output celery \
        -A "backend.modules.${MODULE}.celery_app" worker \
        --loglevel=info \
        --queues=${QUEUE} \
        --concurrency=2 > "${LOG_FILE}" 2>&1 &

    CHILD_PID=$!
    echo $CHILD_PID > "${PID_FILE}"

    # 等待 worker 启动
    log_info "等待 Agent Worker 启动..."
    sleep 2

    # 检查进程是否还在运行
    if ! kill -0 "${CHILD_PID}" 2>/dev/null; then
        log_error "Agent Worker 启动失败！进程已退出"
        log_info "请查看日志文件: ${LOG_FILE}"
        echo ""
        log_info "最近的错误日志："
        tail -20 "${LOG_FILE}"
        rm -f "${PID_FILE}"
        exit 1
    fi

    log_module "$MODULE" "Agent Worker 启动成功 (PID: $CHILD_PID, 队列: $QUEUE)"
    log_module "$MODULE" "日志文件: ${LOG_FILE}"
else
    log_error "未知的服务类型: $SERVICE_TYPE (应为 api 或 agent)"
    exit 1
fi

echo ""
log_success "$(echo "$MODULE" | tr '[:lower:]' '[:upper:]') ${SERVICE_TYPE} 已启动"
log_info "按 Ctrl+C 停止此服务"
echo ""

# 等待进程
wait "${CHILD_PID}"
