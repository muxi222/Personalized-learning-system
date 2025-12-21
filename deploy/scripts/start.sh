#!/bin/bash
# =============================================================================
# AI Learning Assistant - 启动脚本 (Linux/Mac)
#
# 用法:
#   ./start.sh              # 启动所有服务
#   ./start.sh api          # 仅启动 API 服务
#   ./start.sh agent        # 仅启动 Agent Worker
#   ./start.sh frontend     # 仅启动前端
#   ./start.sh docker       # 使用 Docker Compose 启动
#   ./start.sh stop         # 停止所有服务
# =============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PID_DIR="${PROJECT_ROOT}/pids"
API_PID_FILE="${PID_DIR}/.api.pid"
AGENT_PID_FILE="${PID_DIR}/.agent.pid"
FRONTEND_PID_FILE="${PID_DIR}/.frontend.pid"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

CHILD_PIDS=()
SERVICES_STARTED=false

register_child() {
    CHILD_PIDS+=("$1")
    SERVICES_STARTED=true
}

wait_for_children() {
    if [ ${#CHILD_PIDS[@]} -gt 0 ]; then
        wait "${CHILD_PIDS[@]}" 2>/dev/null || true
    fi
}

ensure_pid_dir() {
    mkdir -p "${PID_DIR}"
}

safe_kill_pid_file() {
    local pid_file="$1"
    if [ -f "${pid_file}" ]; then
        local pid
        pid=$(cat "${pid_file}")
        if [ -n "${pid}" ]; then
            kill "${pid}" 2>/dev/null || true
        fi
        rm -f "${pid_file}"
    fi
}

# 检查依赖
check_dependencies() {
    log_info "检查依赖..."

    # 检查 Conda
    if ! command -v conda &> /dev/null; then
        log_error "Conda 未安装，请先安装 Anaconda 或 Miniconda"
        exit 1
    fi

    # 检查 Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装"
        exit 1
    fi

    # 检查 Node.js (前端需要)
    if ! command -v node &> /dev/null; then
        log_warn "Node.js 未安装，前端服务将无法启动"
    fi

    # 检查 Redis
    if ! command -v redis-cli &> /dev/null; then
        log_warn "Redis CLI 未安装，请确保 Redis 服务已运行"
    fi

    log_success "依赖检查完成"
}

# 激活 Conda 环境
setup_conda() {
    log_info "激活 Conda 环境 312_edu..."

    # 初始化 conda for bash（确保 conda activate 可用）
    eval "$(conda shell.bash hook)"

    # 检查环境是否存在
    if ! conda env list | grep -q "^312_edu "; then
        log_error "Conda 环境 312_edu 不存在"
        log_info "请运行以下命令创建环境："
        log_info "  conda create -n 312_edu python=3.10 -y"
        log_info "  conda activate 312_edu"
        log_info "  pip install -r requirements.txt"
        exit 1
    fi

    # 激活环境
    conda activate 312_edu

    # 检查并安装依赖
    if [ -f "${PROJECT_ROOT}/requirements.txt" ]; then
        log_info "检查项目依赖..."
        pip install -q -r "${PROJECT_ROOT}/requirements.txt"
        log_success "依赖检查完成"
    elif [ -f "${PROJECT_ROOT}/pyproject.toml" ]; then
        log_info "检查项目依赖..."
        pip install -q -e "${PROJECT_ROOT}"
        log_success "依赖检查完成"
    fi
}

# 创建数据目录
setup_data_dirs() {
    log_info "创建数据目录..."
    mkdir -p "${PROJECT_ROOT}/data/sqlite"
    mkdir -p "${PROJECT_ROOT}/data/faiss"
    mkdir -p "${PROJECT_ROOT}/data/bm25"
    mkdir -p "${PROJECT_ROOT}/data/uploads"
    mkdir -p "${PROJECT_ROOT}/data/redis"
    mkdir -p "${PROJECT_ROOT}/logs"
    ensure_pid_dir
    log_success "数据目录创建完成"
}

# 加载环境变量
load_env() {
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        # 安全加载环境变量：过滤注释、空行，并移除行内注释
        while IFS= read -r line || [ -n "$line" ]; do
            # 跳过空行和注释行
            if [ -z "$line" ] || echo "$line" | grep -q "^[[:space:]]*#"; then
                continue
            fi
            # 移除行内注释
            clean_line=$(echo "$line" | sed 's/[[:space:]]*#.*$//')
            # 导出变量
            if [ -n "$clean_line" ]; then
                export "$clean_line"
            fi
        done < "${PROJECT_ROOT}/.env"
        log_success "环境变量加载完成"
    else
        log_warn ".env 文件不存在，使用默认配置"
        if [ -f "${PROJECT_ROOT}/env.example" ]; then
            cp "${PROJECT_ROOT}/env.example" "${PROJECT_ROOT}/.env"
            log_info "已从 env.example 创建 .env 文件，请编辑配置"
        fi
    fi
}

# 启动 Redis (如果本地运行)
start_redis() {
    if command -v redis-server &> /dev/null; then
        if ! pgrep -x "redis-server" > /dev/null; then
            log_info "启动 Redis..."
            redis-server --daemonize yes --dir "${PROJECT_ROOT}/data/redis"
            sleep 1
            log_success "Redis 启动成功"
        else
            log_info "Redis 已在运行"
        fi
    fi
}

# 启动 API 服务
start_api() {
    log_info "启动 API 服务..."

    setup_conda
    load_env
    setup_data_dirs

    cd "${PROJECT_ROOT}"

    # 初始化数据库
    log_info "初始化数据库..."
    if ! conda run -n 312_edu python - <<'PY'; then
from backend.app.db.session import init_db
import asyncio


async def _main():
    await init_db()
    print('数据库初始化完成')


asyncio.run(_main())
PY
        log_error "数据库初始化失败，请检查上方日志并确认依赖已安装"
        exit 1
    fi

    log_success "数据库初始化完成"

    # 启动 API
    export PYTHONPATH="${PROJECT_ROOT}/backend:${PROJECT_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
    conda run -n 312_edu --no-capture-output uvicorn backend.main:app \
        --host ${HOST:-0.0.0.0} \
        --port ${PORT:-6000} \
        --reload &

    API_PID=$!
    echo $API_PID > "${API_PID_FILE}"
    register_child "${API_PID}"

    log_success "API 服务启动成功 (PID: $API_PID)"
    log_info "访问地址: http://localhost:${PORT:-6000}"
    log_info "API 文档: http://localhost:${PORT:-6000}/docs"
}

# 启动 Agent Worker (Celery)
start_agent() {
    log_info "启动 Agent Worker..."

    setup_conda
    load_env
    start_redis
    ensure_pid_dir

    cd "${PROJECT_ROOT}"
    export PYTHONPATH="${PROJECT_ROOT}/backend:${PROJECT_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

    conda run -n 312_edu --no-capture-output celery -A backend.app.core.celery_app worker \
        --loglevel=info \
        --concurrency=2 &

    AGENT_PID=$!
    echo $AGENT_PID > "${AGENT_PID_FILE}"
    register_child "${AGENT_PID}"

    log_success "Agent Worker 启动成功 (PID: $AGENT_PID)"
}

# 启动前端
start_frontend() {
    log_info "启动前端服务..."

    if ! command -v node &> /dev/null; then
        log_error "Node.js 未安装"
        exit 1
    fi

    ensure_pid_dir

    cd "${PROJECT_ROOT}/frontend"

    if [ ! -d "node_modules" ]; then
        log_info "安装前端依赖..."
        npm install
    fi

    npm run dev &

    FRONTEND_PID=$!
    echo $FRONTEND_PID > "${FRONTEND_PID_FILE}"
    register_child "${FRONTEND_PID}"

    log_success "前端服务启动成功 (PID: $FRONTEND_PID)"
    log_info "访问地址: http://localhost:8000"
}

# Docker Compose 启动
start_docker() {
    log_info "使用 Docker Compose 启动..."

    if ! command -v docker-compose &> /dev/null && ! command -v docker &> /dev/null; then
        log_error "Docker 未安装"
        exit 1
    fi

    cd "${PROJECT_ROOT}"

    # 创建数据目录
    setup_data_dirs

    # 启动服务
    if command -v docker-compose &> /dev/null; then
        docker-compose up -d
    else
        docker compose up -d
    fi

    log_success "Docker 服务启动成功"
    log_info "API 地址: http://localhost:6000"
    log_info "前端地址: http://localhost:8000"
}

# 停止所有服务
stop_all() {
    log_info "停止所有服务..."

    # 停止 API
    safe_kill_pid_file "${API_PID_FILE}"
    safe_kill_pid_file "${PROJECT_ROOT}/.api.pid"  # 兼容旧版本

    # 停止 Agent
    safe_kill_pid_file "${AGENT_PID_FILE}"
    safe_kill_pid_file "${PROJECT_ROOT}/.agent.pid"  # 兼容旧版本

    # 停止前端
    safe_kill_pid_file "${FRONTEND_PID_FILE}"
    safe_kill_pid_file "${PROJECT_ROOT}/.frontend.pid"  # 兼容旧版本

    # 停止 Celery workers
    pkill -f "celery.*worker" 2>/dev/null || true

    # 停止 uvicorn
    pkill -f "uvicorn.*backend" 2>/dev/null || true

    log_success "所有服务已停止"
}

# 停止 Docker
stop_docker() {
    log_info "停止 Docker 服务..."
    cd "${PROJECT_ROOT}"

    if command -v docker-compose &> /dev/null; then
        docker-compose down
    else
        docker compose down
    fi

    log_success "Docker 服务已停止"
}

cleanup() {
    local signal="${1:-EXIT}"
    if [ "${signal}" != "EXIT" ]; then
        log_warn "检测到中断信号 (${signal})，正在停止所有服务..."
    fi
    if [ "${SERVICES_STARTED}" = true ]; then
        stop_all
    fi
    if [ "${signal}" != "EXIT" ]; then
        exit 0
    fi
}

trap 'cleanup SIGINT' SIGINT
trap 'cleanup SIGTERM' SIGTERM
trap 'cleanup SIGHUP' SIGHUP
trap 'cleanup EXIT' EXIT

# 显示状态
show_status() {
    echo ""
    echo "=========================================="
    echo "       AI Learning Assistant 状态"
    echo "=========================================="

    # API 状态
    if [ -f "${API_PID_FILE}" ] && kill -0 $(cat "${API_PID_FILE}") 2>/dev/null; then
        echo -e "API 服务:    ${GREEN}运行中${NC} (PID: $(cat ${API_PID_FILE}))"
    elif [ -f "${PROJECT_ROOT}/.api.pid" ] && kill -0 $(cat "${PROJECT_ROOT}/.api.pid") 2>/dev/null; then
        echo -e "API 服务:    ${GREEN}运行中${NC} (PID: $(cat ${PROJECT_ROOT}/.api.pid))"
    else
        echo -e "API 服务:    ${RED}未运行${NC}"
    fi

    # Agent 状态
    if [ -f "${AGENT_PID_FILE}" ] && kill -0 $(cat "${AGENT_PID_FILE}") 2>/dev/null; then
        echo -e "Agent Worker: ${GREEN}运行中${NC} (PID: $(cat ${AGENT_PID_FILE}))"
    elif [ -f "${PROJECT_ROOT}/.agent.pid" ] && kill -0 $(cat "${PROJECT_ROOT}/.agent.pid") 2>/dev/null; then
        echo -e "Agent Worker: ${GREEN}运行中${NC} (PID: $(cat ${PROJECT_ROOT}/.agent.pid))"
    else
        echo -e "Agent Worker: ${RED}未运行${NC}"
    fi

    # Redis 状态
    if command -v redis-cli &> /dev/null && redis-cli ping >/dev/null 2>&1; then
        echo -e "Redis:       ${GREEN}运行中${NC}"
    elif pgrep -f "redis-server" > /dev/null 2>&1; then
        echo -e "Redis:       ${GREEN}运行中${NC}"
    else
        echo -e "Redis:       ${RED}未运行${NC}"
    fi

    echo "=========================================="
}

# 显示帮助
show_help() {
    echo ""
    echo "AI Learning Assistant 启动脚本"
    echo ""
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  (无参数)    启动所有服务 (API + Agent + 前端)"
    echo "  api         仅启动 API 服务"
    echo "  agent       仅启动 Agent Worker"
    echo "  frontend    仅启动前端服务"
    echo "  docker      使用 Docker Compose 启动"
    echo "  stop        停止所有本地服务"
    echo "  stop-docker 停止 Docker 服务"
    echo "  status      显示服务状态"
    echo "  help        显示此帮助"
    echo ""
}

# 主函数
main() {
    case "${1:-all}" in
        api)
            check_dependencies
            start_redis
            start_api
            log_info "按 Ctrl+C 或 Ctrl+D 退出并清理所有服务"
            wait_for_children
            ;;
        agent)
            check_dependencies
            start_agent
            log_info "按 Ctrl+C 或 Ctrl+D 退出并清理所有服务"
            wait_for_children
            ;;
        frontend)
            start_frontend
            log_info "按 Ctrl+C 或 Ctrl+D 退出并清理所有服务"
            wait_for_children
            ;;
        docker)
            start_docker
            ;;
        stop)
            stop_all
            ;;
        stop-docker)
            stop_docker
            ;;
        status)
            show_status
            ;;
        help|--help|-h)
            show_help
            ;;
        all|"")
            check_dependencies
            start_redis
            start_api
            start_agent
            start_frontend
            echo ""
            show_status
            log_info "按 Ctrl+C 或 Ctrl+D 退出并清理所有服务"
            wait_for_children
            ;;
        *)
            log_error "未知命令: $1"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
