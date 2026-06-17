#!/bin/bash
# =============================================================================
# vLLM Model Serving Status Check Script
#
# Usage:
#   ./deploy/scripts/check_vllm.sh            # Check all modules
#   ./deploy/scripts/check_vllm.sh tony       # Check specific module
#   ./deploy/scripts/check_vllm.sh all        # Check all modules
#
# Checks:
#   - Process health (PID)
#   - GPU memory usage
#   - Request statistics (via /metrics endpoint)
#   - Model availability (via /v1/models endpoint)
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PID_DIR="${PROJECT_ROOT}/pids"

# Module → port mapping (aligned with pipeline.sh + nginx config)
declare -A MODULE_PORTS
MODULE_PORTS[rpj]=8001
MODULE_PORTS[xmx]=8002
MODULE_PORTS[wzy]=8003
MODULE_PORTS[wzm]=8004
MODULE_PORTS[tony]=8005

MODULE="${1:-all}"

log_info()  { printf "${BLUE}[INFO]${NC} %s\n" "$1"; }
log_ok()    { printf "${GREEN}[OK]${NC} %s\n" "$1"; }
log_warn()  { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
log_err()   { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

check_module() {
    local module="$1"
    local port="${MODULE_PORTS[$module]}"

    echo ""
    echo "=========================================="
    echo "  vLLM ${module^^} 模块状态检查"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=========================================="

    # --- Process health ---
    local pid_file="${PID_DIR}/model_${module}.pid"
    if [ -f "${pid_file}" ]; then
        local pid
        pid=$(cat "${pid_file}" 2>/dev/null || true)
        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
            log_ok "vLLM 进程运行中 (PID: ${pid})"

            # Process resource usage
            local rss cpu
            read -r cpu rss _ <<< "$(ps -p "${pid}" -o %cpu=,rss= 2>/dev/null || echo "0 0 0")"
            rss_mb=$(( rss / 1024 ))
            log_info "  主进程: CPU=${cpu}%, RSS=${rss_mb}MB"

            # Child processes (actual worker)
            local child_count
            child_count=$(pgrep -P "${pid}" 2>/dev/null | wc -l || echo 0)
            if [ "${child_count}" -gt 0 ]; then
                for cp in $(pgrep -P "${pid}" 2>/dev/null); do
                    read -r ccpu crss _ <<< "$(ps -p "${cp}" -o %cpu=,rss= 2>/dev/null || echo "0 0 0")"
                    crss_mb=$(( crss / 1024 ))
                    log_info "  子进程 PID=${cp}: CPU=${ccpu}%, RSS=${crss_mb}MB"
                done
            fi
        else
            log_err "PID 文件存在但进程已退出 (stale PID: ${pid})"
        fi
    else
        log_warn "未找到 PID 文件 (${pid_file})，尝试端口探测..."

        # Fallback: check if port is listening
        if command -v lsof >/dev/null 2>&1; then
            local port_pid
            port_pid=$(lsof -Pi :"${port}" -sTCP:LISTEN -t 2>/dev/null || true)
            if [ -n "${port_pid}" ]; then
                log_ok "端口 ${port} 被进程占用 (PID: ${port_pid})"
            else
                log_err "端口 ${port} 无进程监听 —— 服务可能未启动"
            fi
        else
            if curl -s "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
                log_ok "端口 ${port} 可访问"
            else
                log_err "端口 ${port} 不可达 —— 服务可能未启动"
            fi
        fi
    fi

    # --- GPU usage ---
    echo ""
    echo "--- GPU 占用 ---"
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader 2>/dev/null | \
        while IFS=, read -r idx name util mem_used mem_total temp; do
            idx=$(echo "$idx" | xargs)
            util=$(echo "$util" | xargs)
            mem_used=$(echo "$mem_used" | xargs)
            mem_total=$(echo "$mem_total" | xargs)
            temp=$(echo "$temp" | xargs)

            # Extract numeric values
            mem_used_num=$(echo "$mem_used" | sed 's/[^0-9]//g')
            mem_total_num=$(echo "$mem_total" | sed 's/[^0-9]//g')
            pct=0
            if [ -n "$mem_used_num" ] && [ -n "$mem_total_num" ] && [ "$mem_total_num" -gt 0 ]; then
                pct=$(( mem_used_num * 100 / mem_total_num ))
            fi

            if [ "$pct" -gt 10 ]; then
                log_ok "GPU ${idx}: ${util}% util, ${mem_used}/${mem_total} (${pct}%), ${temp}°C"
            else
                log_info "GPU ${idx}: ${util}% util, ${mem_used}/${mem_total} (${pct}%), ${temp}°C"
            fi
        done
    else
        log_warn "nvidia-smi 不可用"
    fi

    # --- Request metrics (from /metrics endpoint) ---
    echo ""
    echo "--- 请求统计 ---"
    local metrics
    metrics=$(curl -s --max-time 5 "http://127.0.0.1:${port}/metrics" 2>/dev/null || echo "")

    if [ -z "${metrics}" ]; then
        log_warn "无法获取 /metrics 端点（服务可能仍在加载模型或未启动）"
        return 1
    fi

    # Helper: extract metric value (handles counter/gauge/histogram labels)
    get_metric() {
        echo "${metrics}" | grep "^${1}{" | grep -v "^#" | awk '{
            for(i=1;i<=NF;i++) {
                if($i ~ /^[0-9]/) { print $i; exit }
            }
        }' | head -1
    }

    local success_total
    success_total=$(echo "${metrics}" | grep "^vllm:request_success_total{" | grep -v "^#" | awk '{s+=$NF} END {print s+0}')
    log_info "累计成功请求: ${success_total:-0} 次"

    local gen_tokens
    gen_tokens=$(get_metric "vllm:generation_tokens_total")
    log_info "累计输出 tokens: ${gen_tokens:-0}"

    local prompt_tokens
    prompt_tokens=$(get_metric "vllm:prompt_tokens_total")
    log_info "累计输入 tokens: ${prompt_tokens:-0}"

    local waiting
    waiting=$(get_metric "vllm:num_requests_waiting")
    if [ -n "${waiting}" ] && python3 -c "exit(0 if float(${waiting}) > 0 else 1)" 2>/dev/null; then
        log_warn "排队中请求: ${waiting}"
    else
        log_info "排队中请求: ${waiting:-0}"
    fi

    local running
    running=$(get_metric "vllm:num_requests_running")
    log_info "执行中请求: ${running:-0}"

    local preemptions
    preemptions=$(get_metric "vllm:num_preemptions_total")
    if [ -n "${preemptions}" ] && python3 -c "exit(0 if float(${preemptions}) > 0 else 1)" 2>/dev/null; then
        log_warn "抢占次数: ${preemptions} (非零 = 显存压力，需关注)"
    else
        log_ok "抢占次数: ${preemptions:-0} (健康)"
    fi

    local gpu_cache
    gpu_cache=$(get_metric "vllm:gpu_cache_usage_perc")
    log_info "GPU KV Cache 使用率: ${gpu_cache:-0}%"

    # Latency summary
    local e2e_count e2e_sum ttft_sum
    e2e_count=$(get_metric "vllm:e2e_request_latency_seconds_count")
    e2e_sum=$(get_metric "vllm:e2e_request_latency_seconds_sum")
    ttft_sum=$(get_metric "vllm:time_to_first_token_seconds_sum")

    if [ -n "${e2e_count}" ] && [ "${e2e_count%.*}" -gt 0 ]; then
        local avg_e2e avg_ttft
        avg_e2e=$(python3 -c "print(f'{${e2e_sum}/${e2e_count}:.2f}')" 2>/dev/null || echo "N/A")
        avg_ttft=$(python3 -c "print(f'{${ttft_sum}/${e2e_count}:.4f}')" 2>/dev/null || echo "N/A")
        log_info "平均端到端延迟: ${avg_e2e}s"
        log_info "平均首 token 延迟: ${avg_ttft}s"
    fi

    # --- Model list ---
    echo ""
    echo "--- 可用模型 ---"
    local models
    models=$(curl -s --max-time 5 "http://127.0.0.1:${port}/v1/models" 2>/dev/null || echo "")
    if [ -n "${models}" ]; then
        echo "${models}" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for m in data.get('data', []):
        print(f'  - {m[\"id\"]}  (max_model_len={m.get(\"max_model_len\",\"?\")})')
except Exception as e:
    print(f'  (parse error: {e})')
" 2>/dev/null || echo "  ${models}" | head -3
    else
        log_warn "模型列表不可用"
    fi

    echo ""
    echo "--- 快速验证 ---"
    echo "  curl http://127.0.0.1:${port}/v1/models"
    echo "  curl http://127.0.0.1:${port}/metrics | grep request_success"
    echo "  tail -f ${PROJECT_ROOT}/logs/model_${module}.log"
}

if [ "$MODULE" = "all" ]; then
    for m in rpj xmx wzy wzm tony; do
        check_module "$m" || true
    done
else
    check_module "$MODULE" || true
fi

echo ""
echo "=========================================="
echo "  检查完成"
echo "=========================================="
