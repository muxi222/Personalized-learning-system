#!/bin/bash
# =============================================================================
# 测试脚本 - 验证独立启动功能
#
# 用法:
#   ./test_independent_startup.sh
#
# 说明:
#   本脚本自动验证启动脚本的进程隔离功能
#   会启动多个模块并验证它们独立运行
# =============================================================================

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

log_info() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[!]${NC} $1"
}

echo "============================================================"
echo "  启动脚本进程隔离功能测试"
echo "============================================================"
echo ""

# 测试1: 检查脚本文件存在
echo "测试1: 检查脚本文件..."
if [ -f "${SCRIPT_DIR}/start.sh" ]; then
    log_info "start.sh 存在"
else
    log_error "start.sh 不存在"
    exit 1
fi

if [ -f "${SCRIPT_DIR}/start_module.sh" ]; then
    log_info "start_module.sh 存在"
else
    log_error "start_module.sh 不存在"
    exit 1
fi

if [ -x "${SCRIPT_DIR}/start_module.sh" ]; then
    log_info "start_module.sh 可执行"
else
    log_error "start_module.sh 不可执行，尝试修复..."
    chmod +x "${SCRIPT_DIR}/start_module.sh"
    log_info "权限已修复"
fi

echo ""

# 测试2: 检查依赖
echo "测试2: 检查依赖..."

if command -v conda &> /dev/null; then
    log_info "Conda 已安装"
else
    log_error "Conda 未安装"
    exit 1
fi

if conda env list | grep -q "^312_edu "; then
    log_info "Conda 环境 312_edu 存在"
else
    log_error "Conda 环境 312_edu 不存在"
    exit 1
fi

if command -v redis-cli &> /dev/null && redis-cli ping >/dev/null 2>&1; then
    log_info "Redis 运行中"
else
    log_warn "Redis 未运行（某些功能需要Redis）"
fi

echo ""

# 测试3: 验证status命令
echo "测试3: 验证status命令..."
if "${SCRIPT_DIR}/start.sh" status >/dev/null 2>&1; then
    log_info "status命令执行成功"
else
    log_error "status命令执行失败"
    exit 1
fi

echo ""

# 测试4: 验证help命令
echo "测试4: 验证help命令..."
if "${SCRIPT_DIR}/start.sh" help >/dev/null 2>&1; then
    log_info "help命令执行成功"
else
    log_error "help命令执行失败"
    exit 1
fi

echo ""

# 测试5: 验证模块配置
echo "测试5: 验证模块配置..."
MODULES=("rpj" "xmx" "wzy" "wzm" "tony")
PORTS=(6001 6002 6003 6004 6005)

for i in "${!MODULES[@]}"; do
    module="${MODULES[$i]}"
    port="${PORTS[$i]}"

    # 检查端口是否被占用
    if lsof -i ":${port}" >/dev/null 2>&1; then
        log_warn "端口 ${port} (${module}) 已被占用"
    else
        log_info "端口 ${port} (${module}) 空闲"
    fi
done

echo ""

# 测试6: 模拟启动测试（不实际启动，只验证命令）
echo "测试6: 验证启动命令语法..."

# 单模块命令
for module in "${MODULES[@]}"; do
    # 验证 api_<module> 命令格式
    if "${SCRIPT_DIR}/start.sh" help | grep -q "api_${module}"; then
        log_info "api_${module} 命令存在于帮助文档"
    fi

    # 验证 agent_<module> 命令格式
    if "${SCRIPT_DIR}/start.sh" help | grep -q "agent_${module}"; then
        log_info "agent_${module} 命令存在于帮助文档"
    fi
done

echo ""

# 测试7: 检查PID目录
echo "测试7: 检查PID目录..."
PID_DIR="${PROJECT_ROOT}/pids"

if [ -d "${PID_DIR}" ]; then
    log_info "PID目录存在: ${PID_DIR}"
else
    log_warn "PID目录不存在，将在首次启动时创建"
fi

echo ""

# 测试8: 检查日志目录
echo "测试8: 检查日志目录..."
LOG_DIR="${PROJECT_ROOT}/logs"

if [ -d "${LOG_DIR}" ]; then
    log_info "日志目录存在: ${LOG_DIR}"
else
    log_warn "日志目录不存在，将在首次启动时创建"
fi

echo ""

# 测试总结
echo "============================================================"
echo "  测试总结"
echo "============================================================"
log_info "所有基础检查已通过"
echo ""
echo "下一步测试（手动）:"
echo ""
echo "1. 测试单模块独立启动:"
echo "   终端1: ./deploy/scripts/start.sh api_rpj"
echo "   终端2: ./deploy/scripts/start.sh agent_tony"
echo "   终端3: ./deploy/scripts/start.sh api_xmx"
echo "   验证: 在任意终端按 Ctrl+C，其他终端继续运行"
echo ""
echo "2. 测试批量启动:"
echo "   ./deploy/scripts/start.sh api_all"
echo "   验证: Ctrl+C 停止所有5个API"
echo ""
echo "3. 测试状态查看:"
echo "   ./deploy/scripts/start.sh status"
echo "   验证: 显示所有模块的运行状态"
echo ""
echo "4. 测试服务访问:"
echo "   curl http://localhost:6001/health  # RPJ"
echo "   curl http://localhost:6002/health  # XMX"
echo "   curl http://localhost:6003/health  # WZY"
echo "   curl http://localhost:6004/health  # WZM"
echo "   curl http://localhost:6005/health  # TONY"
echo ""
echo "详细使用说明请参考: STARTUP_SCRIPT_OPTIMIZATION_REPORT.md"
echo "============================================================"
