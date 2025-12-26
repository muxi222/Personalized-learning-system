#!/bin/bash
# =============================================================================
# AI Learning Assistant - Docker 多模块启动脚本
#
# 用法:
#   ./start-docker.sh all              # 启动所有服务（包括所有模块 + 前端）
#   ./start-docker.sh api_all          # 启动所有模块 API + Redis
#   ./start-docker.sh agent_all        # 启动所有模块 Agent Worker + Redis
#   ./start-docker.sh default          # 启动 DEFAULT 模块（API + Agent）
#   ./start-docker.sh rpj              # 启动 RPJ 模块（API + Agent）
#   ./start-docker.sh api_default      # 只启动 DEFAULT 模块 API
#   ./start-docker.sh agent_rpj        # 只启动 RPJ 模块 Agent Worker
#   ./start-docker.sh frontend         # 只启动前端
#   ./start-docker.sh stop [module]    # 停止服务
#   ./start-docker.sh restart [module] # 重启服务
#   ./start-docker.sh status           # 查看服务状态
#   ./start-docker.sh logs [service]   # 查看日志
#   ./start-docker.sh build            # 重新构建镜像
# =============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 配置
COMPOSE_FILE="docker-compose.modules.yml"
PROJECT_NAME="learning-assistant"
MODULES=("default" "rpj" "xmx" "wzy" "wzm" "tony")

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

# 检查 Docker 和 Docker Compose
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        log_error "Docker daemon 未运行，请启动 Docker"
        exit 1
    fi

    log_success "Docker 环境检查通过"
}

# 检查 .env 文件
check_env() {
    if [ ! -f ".env" ]; then
        log_warn ".env 文件不存在"
        if [ -f "env.example" ]; then
            log_info "从 env.example 复制..."
            cp env.example .env
            log_warn "请编辑 .env 文件，填入必要的配置"
            exit 1
        else
            log_error "env.example 文件也不存在，请手动创建 .env 文件"
            exit 1
        fi
    fi
}

# 创建必要的目录
setup_directories() {
    log_info "创建数据目录..."
    mkdir -p data/sqlite data/redis data/uploads logs
    for module in "${MODULES[@]}"; do
        mkdir -p "data/faiss/${module}" "data/bm25/${module}"
    done
    log_success "数据目录创建完成"
}

# 构建镜像
build_images() {
    log_info "构建 Docker 镜像..."
    docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" build "$@"
    log_success "镜像构建完成"
}

# 启动服务
start_service() {
    local cmd=$1
    local profiles=()

    case "$cmd" in
        "all")
            log_info "启动所有服务（6个模块 + 前端）..."
            profiles=("--profile" "all")
            ;;
        "api_all")
            log_info "启动所有模块 API..."
            profiles=("--profile" "api")
            ;;
        "agent_all")
            log_info "启动所有模块 Agent Worker..."
            profiles=("--profile" "agent")
            ;;
        "frontend")
            log_info "启动前端服务..."
            profiles=("--profile" "frontend")
            ;;
        "default"|"rpj"|"xmx"|"wzy"|"wzm"|"tony")
            log_info "启动 ${cmd^^} 模块（API + Agent）..."
            profiles=("--profile" "$cmd")
            ;;
        api_*)
            local module="${cmd#api_}"
            log_info "启动 ${module^^} 模块 API..."
            docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" up -d "api-${module}"
            log_success "${module^^} 模块 API 启动成功"
            show_module_info "$module"
            return
            ;;
        agent_*)
            local module="${cmd#agent_}"
            log_info "启动 ${module^^} 模块 Agent Worker..."
            docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" up -d "agent-${module}"
            log_success "${module^^} 模块 Agent Worker 启动成功"
            return
            ;;
        *)
            log_error "未知命令: $cmd"
            show_usage
            exit 1
            ;;
    esac

    docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" "${profiles[@]}" up -d
    log_success "服务启动完成"

    if [ "$cmd" = "all" ]; then
        show_all_info
    fi
}

# 停止服务
stop_service() {
    local target=$1

    if [ -z "$target" ] || [ "$target" = "all" ]; then
        log_info "停止所有服务..."
        docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" down
        log_success "所有服务已停止"
    elif [[ "$target" =~ ^(default|rpj|xmx|wzy|wzm|tony)$ ]]; then
        log_info "停止 ${target^^} 模块..."
        docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" stop "api-${target}" "agent-${target}"
        docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" rm -f "api-${target}" "agent-${target}"
        log_success "${target^^} 模块已停止"
    elif [ "$target" = "frontend" ]; then
        log_info "停止前端服务..."
        docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" stop frontend
        docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" rm -f frontend
        log_success "前端服务已停止"
    else
        log_error "未知服务: $target"
        exit 1
    fi
}

# 重启服务
restart_service() {
    local target=$1
    stop_service "$target"
    sleep 2
    start_service "${target:-all}"
}

# 查看状态
show_status() {
    log_info "服务状态:"
    docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" ps
}

# 查看日志
show_logs() {
    local service=$1
    if [ -z "$service" ]; then
        log_info "查看所有服务日志（Ctrl+C 退出）..."
        docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" logs -f
    else
        log_info "查看 ${service} 日志（Ctrl+C 退出）..."
        docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" logs -f "$service"
    fi
}

# 显示模块信息
show_module_info() {
    local module=$1
    local port

    case "$module" in
        default) port="6100" ;;
        rpj) port="6001" ;;
        xmx) port="6002" ;;
        wzy) port="6003" ;;
        wzm) port="6004" ;;
        tony) port="6005" ;;
    esac

    echo ""
    log_success "${module^^} 模块已启动"
    echo "  API 地址: http://localhost:${port}"
    echo "  API 文档: http://localhost:${port}/docs"
    echo "  健康检查: http://localhost:${port}/health"
    echo ""
}

# 显示所有服务信息
show_all_info() {
    echo ""
    log_success "所有服务已启动"
    echo ""
    echo "模块信息:"
    echo "  DEFAULT (6100): 跨学科查询"
    echo "  RPJ (6001):     语文、英语、政治"
    echo "  XMX (6002):     经济学"
    echo "  WZY (6003):     数学、物理"
    echo "  WZM (6004):     化学"
    echo "  TONY (6005):    历史、地理、其他"
    echo ""
    echo "前端地址: http://localhost:8000"
    echo ""
    echo "查看状态: ./start-docker.sh status"
    echo "查看日志: ./start-docker.sh logs [service]"
    echo ""
}

# 显示使用说明
show_usage() {
    cat << EOF
${CYAN}AI Learning Assistant - Docker 多模块管理${NC}

${YELLOW}用法:${NC}
  $0 <command> [options]

${YELLOW}命令:${NC}
  ${GREEN}启动服务:${NC}
    all                  启动所有服务（6个模块 + 前端）
    api_all              启动所有模块 API
    agent_all            启动所有模块 Agent Worker
    default              启动 DEFAULT 模块（API + Agent）
    rpj, xmx, wzy, wzm, tony  启动指定模块（API + Agent）
    api_default          只启动 DEFAULT 模块 API
    agent_rpj            只启动 RPJ 模块 Agent Worker
    frontend             只启动前端服务

  ${GREEN}管理服务:${NC}
    stop [module]        停止服务（不指定则停止所有）
    restart [module]     重启服务（不指定则重启所有）
    status               查看服务状态
    logs [service]       查看日志（不指定则查看所有）

  ${GREEN}维护:${NC}
    build                重新构建镜像
    clean                清理未使用的容器和镜像

${YELLOW}示例:${NC}
  $0 all                         # 启动所有服务
  $0 rpj                         # 启动 RPJ 模块
  $0 api_default                 # 只启动 DEFAULT API
  $0 stop rpj                    # 停止 RPJ 模块
  $0 logs api-rpj                # 查看 RPJ API 日志
  $0 build                       # 重新构建镜像

${YELLOW}模块端口:${NC}
  DEFAULT: 6100  (跨学科查询)
  RPJ:     6001  (语文、英语、政治)
  XMX:     6002  (经济学)
  WZY:     6003  (数学、物理)
  WZM:     6004  (化学)
  TONY:    6005  (历史、地理、其他)
  Frontend: 8000
EOF
}

# 清理
clean_docker() {
    log_info "清理未使用的 Docker 资源..."
    docker-compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" down --remove-orphans
    docker system prune -f
    log_success "清理完成"
}

# 主函数
main() {
    local cmd="${1:-help}"

    # 检查环境
    check_docker
    check_env
    setup_directories

    case "$cmd" in
        "help"|"-h"|"--help")
            show_usage
            ;;
        "build")
            build_images "${@:2}"
            ;;
        "status")
            show_status
            ;;
        "logs")
            show_logs "$2"
            ;;
        "stop")
            stop_service "$2"
            ;;
        "restart")
            restart_service "$2"
            ;;
        "clean")
            clean_docker
            ;;
        *)
            start_service "$cmd"
            ;;
    esac
}

# 执行主函数
main "$@"
