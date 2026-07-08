#!/bin/bash
# =============================================================================
# AI Learning Assistant - 多模块启动脚本 (Linux/Mac)
#
# 入口脚本:
# - 本脚本负责“一键启动/批量启动/停止/状态查看/前端启动”
# - 单模块独立启动（互不影响、Ctrl+C 只停当前模块）由 `start_module.sh` 执行：
#     ./deploy/scripts/start.sh api_<module> / agent_<module> 会自动 `exec` 到 start_module.sh
#
# 常用用法（完整说明见：./deploy/scripts/start.sh help）:
#   ./deploy/scripts/start.sh                    # 启动全部服务（API + Agent + 前端）
#   ./deploy/scripts/start.sh api_default        # 独立启动某个模块的 API（示例：default）
#   ./deploy/scripts/start.sh agent_rpj          # 独立启动某个模块的 Agent（示例：rpj）
#   ./deploy/scripts/start.sh api_all            # 批量启动所有模块 API（在本脚本内等待，Ctrl+C 一起停）
#   ./deploy/scripts/start.sh agent_all          # 批量启动所有模块 Agent（在本脚本内等待，Ctrl+C 一起停）
#   ./deploy/scripts/start.sh frontend           # 仅启动前端
#   ./deploy/scripts/start.sh status             # 查看所有模块/共享服务状态
#   ./deploy/scripts/start.sh stop_<module>      # 停止某个模块的 API + Agent（示例：stop_tony）
#   ./deploy/scripts/start.sh stop_all           # 停止全部服务（含前端）
# =============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 模块定义 (兼容 Bash 3.2)
MODULES=("default" "rpj" "xmx" "wzy" "wzm" "tony")
AGENT_MODULES=("default" "rpj" "xmx" "wzy" "wzm" "tony")

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
        default) echo "跨学科（全量数据、图片转发）" ;;
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
FRONTEND_PID_FILE="${PID_DIR}/frontend.pid"

# 日志函数
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

CHILD_PIDS=()
CHILD_PID_FILES=()
SERVICES_STARTED=false

register_child() {
    CHILD_PIDS+=("$1")
    SERVICES_STARTED=true
}

register_pid_file() {
    CHILD_PID_FILES+=("$1")
}

wait_for_children() {
    if [ ${#CHILD_PIDS[@]} -gt 0 ]; then
        wait "${CHILD_PIDS[@]}" 2>/dev/null || true
    fi
}

ensure_pid_dir() {
    mkdir -p "${PID_DIR}"
}

get_pid_file() {
    local service=$1  # api or agent
    local module=$2
    echo "${PID_DIR}/${service}_${module}.pid"
}

safe_kill_pid_file() {
    local pid_file="$1"
    if [ -f "${pid_file}" ]; then
        local pid
        pid=$(cat "${pid_file}")
        if [ -n "${pid}" ]; then
            # Best-effort kill the whole process tree (conda run wrapper may not forward signals)
            kill_child_pid "${pid}"
        fi
        rm -f "${pid_file}"
    fi
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
        # recurse
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

    # Descendants first (so wrappers don't orphan workers)
    local desc
    desc=$(get_descendants "${pid}" || true)
    if [ -n "${desc}" ]; then
        for d in ${desc}; do
            kill "-${sig}" "${d}" 2>/dev/null || true
        done
    fi

    kill "-${sig}" "${pid}" 2>/dev/null || true
}

# 仅停止“当前 terminal/当前脚本实例”启动的子进程（不影响其他 terminal）
kill_child_pid() {
    local pid="$1"
    if [ -z "${pid}" ]; then
        return 0
    fi

    # 先杀进程树（conda run 包装层不一定会把信号传给 celery/uvicorn）
    kill_tree "${pid}" "TERM"

    # 再尝试杀进程组（某些场景 PGID==PID，可一并结束 uvicorn --reload 的子进程）
    kill -TERM -- "-${pid}" 2>/dev/null || true
    sleep 1

    # 强杀剩余进程（包括被重新父进程收养的 worker 子进程）
    kill_tree "${pid}" "KILL"
    kill -KILL -- "-${pid}" 2>/dev/null || true
}

cleanup_children_only() {
    local signal="${1:-EXIT}"
    if [ "${signal}" != "EXIT" ]; then
        log_warn "检测到中断信号 (${signal})，仅停止当前终端启动的服务..."
    fi

    # 停止子进程
    if [ ${#CHILD_PIDS[@]} -gt 0 ]; then
        for pid in "${CHILD_PIDS[@]}"; do
            kill_child_pid "${pid}"
        done
    fi

    # 清理本次启动产生的 PID 文件（不触碰其他终端产生的 PID 文件）
    if [ ${#CHILD_PID_FILES[@]} -gt 0 ]; then
        for f in "${CHILD_PID_FILES[@]}"; do
            rm -f "${f}" 2>/dev/null || true
        done
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
    # 初始化 conda for bash（确保 conda activate 可用）
    eval "$(conda shell.bash hook)"

    # 检查环境是否存在
    if ! conda env list | grep -q "^312_edu "; then
        log_error "Conda 环境 312_edu 不存在"
        log_info "请运行以下命令创建环境："
        log_info "  conda create -n 312_edu python=3.11 -y"
        log_info "  conda activate 312_edu"
        log_info "  pip install -r requirements.txt"
        exit 1
    fi

    # 激活环境
    conda activate 312_edu

    # 检查并安装依赖
    # if [ -f "${PROJECT_ROOT}/requirements.txt" ]; then
    #     pip install -q -r "${PROJECT_ROOT}/requirements.txt" 2>/dev/null || true
    # fi
}

# 创建数据目录
setup_data_dirs() {
    log_info "创建数据目录..."
    mkdir -p "${PROJECT_ROOT}/data/sqlite"
    mkdir -p "${PROJECT_ROOT}/data/uploads"
    mkdir -p "${PROJECT_ROOT}/logs"

    # 为每个模块创建FAISS和BM25目录
    for module in "${MODULES[@]}"; do
        mkdir -p "${PROJECT_ROOT}/data/faiss/${module}"
        mkdir -p "${PROJECT_ROOT}/data/bm25/${module}"
    done

    ensure_pid_dir
    log_success "数据目录创建完成"
}

# 加载环境变量
load_env() {
    if [ -f "${PROJECT_ROOT}/.env" ]; then
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
    fi
}

# Default feature flags (can be overridden by .env / exported env)
ensure_default_env() {
    # By default, companion chat will require a subject-specific LoRA:
    # - subject=history   -> tony-sft-history
    # - subject=chemistry -> wzm-sft-chemistry
    # If missing, backend will block and prompt user to train that subject LoRA.
    #
    # Users can disable (allow fallback to PERSONAL_MODEL_MODEL_<MODULE>):
    #   export COMPANION_REQUIRE_SUBJECT_MODEL=false
    if [ -z "${COMPANION_REQUIRE_SUBJECT_MODEL:-}" ]; then
        export COMPANION_REQUIRE_SUBJECT_MODEL=true
    fi
}

# 启动 Redis (如果本地运行)
start_redis() {
    if command -v redis-server &> /dev/null; then
        if ! pgrep -x "redis-server" > /dev/null; then
            log_info "启动 Redis..."
            redis-server --daemonize yes
            sleep 1
            log_success "Redis 启动成功"
        else
            log_info "Redis 已在运行"
        fi
    fi
}

# 初始化数据库 (只需要初始化一次，所有模块共享)
init_database() {
    log_info "初始化共享数据库..."

    cd "${PROJECT_ROOT}"
    export PYTHONPATH="${PROJECT_ROOT}/backend:${PYTHONPATH:+:$PYTHONPATH}"

    if conda run -n 312_edu python - <<'PY'; then
import asyncio
from backend.core.db.session import init_db

async def _main():
    await init_db()
    print('数据库初始化完成')

asyncio.run(_main())
PY
        log_success "数据库初始化完成"
    else
        log_error "数据库初始化失败"
        exit 1
    fi
}

# 启动模块 API 服务
start_module_api() {
    local module=$1
    local port=$(get_module_port "$module")
    local subjects=$(get_module_subjects "$module")

    log_module "$module" "启动 API 服务 (端口: $port, 学科: $subjects)..."

    local pid_file=$(get_pid_file "api" "$module")

    # 清理旧的 PID 文件（如果进程已死）
    if [ -f "${pid_file}" ]; then
        local old_pid=$(cat "${pid_file}")
        if ! kill -0 "${old_pid}" 2>/dev/null; then
            log_warn "清理 ${module} API 的旧 PID 文件"
            rm -f "${pid_file}"
        fi
    fi

    # 检查端口是否被占用
    if check_port "$port"; then
        PROCESS_INFO=$(get_port_process "$port")
        OCCUPYING_PID=$(echo "$PROCESS_INFO" | awk '{print $1}')
        OCCUPYING_NAME=$(echo "$PROCESS_INFO" | awk '{print $2}')

        log_error "${module} API 端口 ${port} 已被占用！"
        log_error "占用进程: ${OCCUPYING_NAME} (PID: ${OCCUPYING_PID})"
        log_info "请先停止占用端口的进程: ./deploy/scripts/start.sh stop_${module}"
        return 1
    fi

    cd "${PROJECT_ROOT}"
    export PYTHONPATH="${PROJECT_ROOT}/backend:${PYTHONPATH:+:$PYTHONPATH}"

    # 启动 API (使用模块的main.py)
    # 根据 RELOAD 环境变量决定是否启用热重载
    local reload_args=""
    if [ "${RELOAD:-true}" = "true" ]; then
        reload_args="--reload --reload-dir ${PROJECT_ROOT}/backend --reload-exclude '**/__pycache__/*' --reload-exclude '**/*.pyc'"
    fi

    conda run -n 312_edu --no-capture-output uvicorn \
        "backend.modules.${module}.main:app" \
        --host ${HOST:-0.0.0.0} \
        --port ${port} \
        ${reload_args} > "${PROJECT_ROOT}/logs/${module}_api.log" 2>&1 &

    local pid=$!
    echo $pid > "${pid_file}"
    register_child "${pid}"
    register_pid_file "${pid_file}"

    log_module "$module" "API 服务启动成功 (PID: $pid)"
    log_module "$module" "访问地址: http://localhost:${port}"
    log_module "$module" "API 文档: http://localhost:${port}/docs"
}

# 启动模块 Agent Worker
start_module_agent() {
    local module=$1
    local queue="queue_${module}"
    local subjects=$(get_module_subjects "$module")

    log_module "$module" "启动 Agent Worker (队列: $queue, 学科: $subjects)..."

    local pid_file=$(get_pid_file "agent" "$module")

    # 清理旧的 PID 文件（如果进程已死）
    if [ -f "${pid_file}" ]; then
        local old_pid=$(cat "${pid_file}")
        if ! kill -0 "${old_pid}" 2>/dev/null; then
            log_warn "清理 ${module} Agent 的旧 PID 文件"
            rm -f "${pid_file}"
        fi
    fi

    cd "${PROJECT_ROOT}"
    export PYTHONPATH="${PROJECT_ROOT}/backend:${PYTHONPATH:+:$PYTHONPATH}"

    # 启动 Celery Worker (使用模块的celery_app)
    conda run -n 312_edu --no-capture-output celery \
        -A "backend.modules.${module}.celery_app" worker \
        --loglevel=info \
        --queues=${queue} \
        --concurrency=2 > "${PROJECT_ROOT}/logs/${module}_agent.log" 2>&1 &

    local pid=$!
    echo $pid > "${pid_file}"
    register_child "${pid}"
    register_pid_file "${pid_file}"

    log_module "$module" "Agent Worker 启动成功 (PID: $pid, 队列: $queue)"
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

    npm run dev > "${PROJECT_ROOT}/logs/frontend.log" 2>&1 &

    local pid=$!
    echo $pid > "${FRONTEND_PID_FILE}"
    register_child "${pid}"
    register_pid_file "${FRONTEND_PID_FILE}"

    log_success "前端服务启动成功 (PID: $pid)"
    log_info "访问地址: http://localhost:8000"
}

# 启动所有模块的API
start_all_api() {
    log_info "启动所有模块 API..."
    for module in "${MODULES[@]}"; do
        start_module_api "$module"
        sleep 2  # 给每个服务一些启动时间
    done
    log_success "所有模块 API 启动完成"
}

# 启动所有模块的Agent
start_all_agent() {
    log_info "启动所有模块 Agent Worker..."
    for module in "${AGENT_MODULES[@]}"; do
        start_module_agent "$module"
        sleep 2
    done
    log_success "所有模块 Agent Worker 启动完成"
}

# 停止指定模块
stop_module() {
    local module=$1
    log_module "$module" "停止服务..."

    safe_kill_pid_file "$(get_pid_file "api" "$module")"
    safe_kill_pid_file "$(get_pid_file "agent" "$module")"

    log_module "$module" "服务已停止"
}

# 停止所有服务
stop_all() {
    log_info "停止所有服务..."

    # 停止所有模块
    for module in "${MODULES[@]}"; do
        stop_module "$module"
    done

    # 停止前端
    safe_kill_pid_file "${FRONTEND_PID_FILE}"

    # 清理残留进程
    pkill -f "celery.*worker" 2>/dev/null || true
    pkill -f "uvicorn.*backend.modules" 2>/dev/null || true

    log_success "所有服务已停止"
}

cleanup() {
    local signal="${1:-EXIT}"
    # 重要：Ctrl+C 只停止“当前终端/当前脚本实例”启动的服务，避免影响其他终端中的服务
    cleanup_children_only "${signal}"
    if [ "${signal}" != "EXIT" ]; then exit 0; fi
}

trap 'cleanup SIGINT' SIGINT
trap 'cleanup SIGTERM' SIGTERM
trap 'cleanup SIGHUP' SIGHUP
trap 'cleanup EXIT' EXIT

# 显示服务状态
show_status() {
    echo ""
    echo "============================================================"
    echo "       AI Learning Assistant - 多模块状态"
    echo "============================================================"
    echo ""

    # 显示每个模块的状态
    for module in "${MODULES[@]}"; do
        local port=$(get_module_port "$module")
        local subjects=$(get_module_subjects "$module")

        printf "${CYAN}模块: %s${NC} (端口: %s, 学科: %s)\n" "$(echo "$module" | tr '[:lower:]' '[:upper:]')" "$port" "$subjects"

        # API 状态
        local api_pid_file=$(get_pid_file "api" "$module")
        if [ -f "${api_pid_file}" ] && kill -0 $(cat "${api_pid_file}") 2>/dev/null; then
            printf "  API:    ${GREEN}●${NC} 运行中 (PID: %s)\n" "$(cat ${api_pid_file})"
        else
            printf "  API:    ${RED}○${NC} 未运行\n"
        fi

        # Agent 状态
        local agent_pid_file=$(get_pid_file "agent" "$module")
        if [ -f "${agent_pid_file}" ] && kill -0 $(cat "${agent_pid_file}") 2>/dev/null; then
            printf "  Agent:  ${GREEN}●${NC} 运行中 (PID: %s)\n" "$(cat ${agent_pid_file})"
        else
            printf "  Agent:  ${RED}○${NC} 未运行\n"
        fi

        echo ""
    done

    # Redis 状态
    printf "${CYAN}共享服务${NC}\n"
    if command -v redis-cli &> /dev/null && redis-cli ping >/dev/null 2>&1; then
        printf "  Redis:  ${GREEN}●${NC} 运行中\n"
    else
        printf "  Redis:  ${RED}○${NC} 未运行\n"
    fi

    # 前端状态
    if [ -f "${FRONTEND_PID_FILE}" ] && kill -0 $(cat "${FRONTEND_PID_FILE}") 2>/dev/null; then
        printf "  前端:   ${GREEN}●${NC} 运行中 (PID: %s)\n" "$(cat ${FRONTEND_PID_FILE})"
    else
        printf "  前端:   ${RED}○${NC} 未运行\n"
    fi

    echo ""
    echo "============================================================"
}

# 显示帮助
show_help() {
    cat <<'EOF'

AI Learning Assistant - 多模块启动脚本

用法:
  ./deploy/scripts/start.sh [命令]
  ./deploy/scripts/start.sh help

快速开始（推荐学生按这个顺序）:
  1) 一键启动全部（最省心）:
     ./deploy/scripts/start.sh
     - 前端: http://localhost:8000
     - API 文档: http://localhost:<端口>/docs（端口见下表）

  2) 只启动某一个模块（互不影响，适合并行开发/调试）:
     ./deploy/scripts/start.sh api_rpj
     ./deploy/scripts/start.sh agent_rpj

启动命令（Start）:
  all / (空)         启动全部服务：所有模块 API + 所有模块 Agent + 前端
  api_<module>       独立启动某模块 API（会 exec 到 start_module.sh，Ctrl+C 只停该模块）
  agent_<module>     独立启动某模块 Agent（会 exec 到 start_module.sh，Ctrl+C 只停该模块）
  api_all            批量启动所有模块 API（本脚本内等待模式，Ctrl+C 一起停）
  agent_all          批量启动所有模块 Agent（本脚本内等待模式，Ctrl+C 一起停）
  frontend           仅启动前端（本脚本内等待模式，Ctrl+C 停前端）

停止命令（Stop）:
  stop_<module>      停止某模块：API + Agent（示例：stop_tony）
  stop_all           停止全部服务（含前端；并 best-effort 清理 uvicorn/celery 残留进程）

查看状态（Status）:
  status             显示所有模块 API/Agent、Redis、前端的运行状态

帮助（Help）:
  help | --help | -h 显示本帮助

重要行为说明（非常适合学生理解）:
  - “独立启动模式”（api_<module>/agent_<module>）:
    - 会交给 ./deploy/scripts/start_module.sh 启动并等待
    - Ctrl+C 只会停止当前这个模块的服务，不影响其他终端里启动的服务
  - “批量等待模式”（all/api_all/agent_all/frontend）:
    - 本脚本会启动多个进程并等待
    - Ctrl+C 会停止“本次启动的子进程”，避免误杀其他终端的服务
  - stop_<module>/stop_all:
    - 通过 pids/*.pid 定位并停止进程；stop_all 还会尝试清理残留 celery/uvicorn

日志与 PID（排错必看）:
  - 日志目录: ./logs/
    - API:   logs/<module>_api.log
    - Agent: logs/<module>_agent.log
    - 前端:  logs/frontend.log
  - PID 目录: ./pids/

常见环境变量（可写入 .env 或在启动前 export）:
  - HOST: API 绑定地址（默认 0.0.0.0）
  - DATABASE_URL / Redis 等：按项目 .env 约定（如存在会自动加载）

提示:
  - 依赖要求: Conda 环境名必须为 312_edu；前端需要 Node.js；Agent 需要 Redis 可用
  - default 模块不提供 Agent Worker（无 celery_app）

EOF

    echo "可用模块（API 端口 / 学科）:"
    for module in "${MODULES[@]}"; do
        local port
        port=$(get_module_port "$module")
        local subjects
        subjects=$(get_module_subjects "$module")
        printf "  - %-8s  port=%-5s  %s\n" "${module}" "${port}" "${subjects}"
    done
    echo ""
    echo "支持 Agent Worker 的模块（default 除外）:"
    echo "  - ${AGENT_MODULES[*]}"
    echo ""
    echo "相关脚本（可选）:"
    echo "  - MCP 服务（Tony retrieval-mcp）: ./deploy/scripts/start_mcp.sh help"
    echo "  - 训练/构建/Serving 管线:          ./deploy/scripts/pipeline.sh help"
    echo ""
}

# 主函数
main() {
    local cmd="${1:-all}"

    # 解析命令
    if [[ "$cmd" == api_* ]]; then
        # api_<module> 命令
        local module="${cmd#api_}"
        if [ "$module" == "all" ]; then
            # 批量启动所有API - 使用等待模式
            check_dependencies
            setup_conda
            load_env
            ensure_default_env
            setup_data_dirs
            start_redis
            init_database
            start_all_api
            log_info "按 Ctrl+C 退出并停止所有 API 服务"
            wait_for_children
        elif [[ " ${MODULES[@]} " =~ " ${module} " ]]; then
            # 单模块启动 - 使用独立脚本，不阻塞
            log_info "使用独立模式启动 ${module} API..."
            exec "${SCRIPT_DIR}/start_module.sh" api "$module"
        else
            log_error "未知模块: $module"
            show_help
            exit 1
        fi

    elif [[ "$cmd" == agent_* ]]; then
        # agent_<module> 命令
        local module="${cmd#agent_}"
        if [ "$module" == "all" ]; then
            # 批量启动所有Agent - 使用等待模式
            check_dependencies
            setup_conda
            load_env
            ensure_default_env
            start_redis
            start_all_agent
            log_info "按 Ctrl+C 退出并停止所有 Agent Worker"
            wait_for_children
        elif [[ " ${MODULES[@]} " =~ " ${module} " ]]; then
            # 单模块启动 - 使用独立脚本，不阻塞
            log_info "使用独立模式启动 ${module} Agent..."
            exec "${SCRIPT_DIR}/start_module.sh" agent "$module"
        else
            log_error "未知模块: $module"
            show_help
            exit 1
        fi

    elif [[ "$cmd" == stop_* ]]; then
        # stop_<module> 命令
        local module="${cmd#stop_}"
        if [ "$module" == "all" ]; then
            stop_all
        elif [[ " ${MODULES[@]} " =~ " ${module} " ]]; then
            stop_module "$module"
        else
            log_error "未知模块: $module"
            exit 1
        fi

    else
        # 其他命令
        case "$cmd" in
            frontend)
                # 前端启动 - 独立模式(不影响其他服务)
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

                # 启动前端
                npm run dev > "${PROJECT_ROOT}/logs/frontend.log" 2>&1 &
                FRONTEND_PID=$!
                echo $FRONTEND_PID > "${FRONTEND_PID_FILE}"

                log_success "前端服务启动成功 (PID: $FRONTEND_PID)"
                log_info "访问地址: http://localhost:8000"
                log_info "按 Ctrl+C 退出并停止前端服务"

                # 独立的cleanup，只停止frontend
                cleanup_frontend() {
                    log_info "正在停止前端服务..."
                    if [ -n "${FRONTEND_PID}" ] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
                        kill "${FRONTEND_PID}" 2>/dev/null || true
                        sleep 1
                        if kill -0 "${FRONTEND_PID}" 2>/dev/null; then
                            kill -9 "${FRONTEND_PID}" 2>/dev/null || true
                        fi
                    fi
                    rm -f "${FRONTEND_PID_FILE}"
                    log_success "前端服务已停止"
                }

                # 设置独立的trap（覆盖全局trap）
                trap 'cleanup_frontend; exit 0' INT TERM

                # 等待前端进程
                wait "${FRONTEND_PID}"
                ;;
            status)
                show_status
                ;;
            help|--help|-h)
                show_help
                ;;
            all|"")
                # 启动所有服务 - 使用等待模式
                check_dependencies
                setup_conda
                load_env
            ensure_default_env
                setup_data_dirs
                start_redis
                init_database
                start_all_api
                start_all_agent
                start_frontend
                echo ""
                show_status
                log_info "按 Ctrl+C 退出并停止所有服务"
                wait_for_children
                ;;
            *)
                log_error "未知命令: $cmd"
                show_help
                exit 1
                ;;
        esac
    fi
}

main "$@"
