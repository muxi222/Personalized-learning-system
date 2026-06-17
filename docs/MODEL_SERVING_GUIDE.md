# 模型推理服务：启动与监控指南

本文档独立描述 AI 学习小书童各模块模型的 **启动方式**、**状态监控** 与 **运维操作**，不与其他文档耦合。

---

## 1. 架构概览

### 1.1 端口规划

```
                      ┌───────────────────────────────────────┐
                      │           Nginx (:8010)               │
                      │   /v1/rpj/*  →  rpj  :8001           │
                      │   /v1/xmx/*  →  xmx  :8002           │
                      │   /v1/wzy/*  →  wzy  :8003           │
                      │   /v1/wzm/*  →  wzm  :8004           │
                      │   /v1/tony/* →  tony :8005           │
                      │   /v1/*      →  tony :8005 (default) │
                      └───────────────────────────────────────┘
```

| 模块 | vLLM 端口 | 负责学科 |
|------|----------|---------|
| rpj  | 8001 | 语文、英语、政治 |
| xmx  | 8002 | 经济学 |
| wzy  | 8003 | 数学、物理 |
| wzm  | 8004 | 化学 |
| tony | 8005 | 历史、地理、其他 |

### 1.2 关键路径

| 用途 | 路径 |
|------|------|
| PID 文件 | `pids/model_{module}.pid` |
| 推理日志 | `logs/model_{module}.log` |
| Nginx 配置 | `deploy/nginx/nginx.conf` |
| 状态检查脚本 | `deploy/scripts/check_vllm.sh` |
| Pipeline 脚本 | `deploy/scripts/pipeline.sh` |
| 基座模型缓存 | `/root/code/vepfs/.cache/huggingface/hub/` |
| SFT LoRA | `data/training/{module}/checkpoints/sft_lora/` |
| DPO LoRA | `data/training/{module}/checkpoints/dpo_lora/` |

---

## 2. 模型启动

### 2.1 前置条件

- Conda 环境 `312_edu` 已创建并安装依赖（`requirements.txt`）
- 基座模型已下载到 HF 缓存
- GPU 显存足够（Qwen3-14B ≈ 68GB in fp16）

### 2.2 快速启动（推荐）

```bash
# 激活环境
eval "$(/root/code/vepfs/miniconda3/bin/conda shell.bash hook)"
conda activate 312_edu

# 设置 HF 缓存路径
export HF_HOME=/root/code/vepfs/.cache/huggingface
export HF_HUB_CACHE=/root/code/vepfs/.cache/huggingface/hub

# 启动 tony 模块 vLLM
./deploy/scripts/pipeline.sh serve-model --module tony up

# 查看日志确认加载完成
./deploy/scripts/pipeline.sh serve-model --module tony logs
```

### 2.3 手动启动（直接调 vLLM）

当需要更精细的控制（如指定 LoRA、调整参数）时：

```bash
conda activate 312_edu
export HF_HOME=/root/code/vepfs/.cache/huggingface

python -m vllm.entrypoints.openai.api_server \
  --model /root/code/vepfs/.cache/huggingface/hub/models--OpenPipe--Qwen3-14B-Instruct/snapshots/<SHA> \
  --served-model-name tony-qwen3-14b \
  --host 0.0.0.0 \
  --port 8005 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.85 \
  --enforce-eager \
  > logs/model_tony.log 2>&1 &

echo $! > pids/model_tony.pid
```

### 2.4 启动参数说明

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `--port` | 8005 | 服务端口 |
| `--max-model-len` | 4096 | 最大上下文长度（越大显存占用越多） |
| `--gpu-memory-utilization` | 0.85 | GPU 显存使用率上限（0.85 = 85%） |
| `--enforce-eager` | true | 禁用 CUDA Graph（更稳定，略增延迟） |
| `--enable-lora` | - | 启用 LoRA 适配器 |
| `--lora-modules` | - | LoRA 模块列表，格式 `name=path` |
| `--max-lora-rank` | 16 | 最大 LoRA rank（需 ≥ 适配器实际 rank） |

### 2.5 停止与重启

```bash
# 停止
./deploy/scripts/pipeline.sh serve-model --module tony down

# 重启
./deploy/scripts/pipeline.sh serve-model --module tony restart

# 查看状态
./deploy/scripts/pipeline.sh serve-model --module tony status
```

---

## 3. 状态监控

### 3.1 一键检查脚本

```bash
# 检查单个模块
./deploy/scripts/check_vllm.sh tony

# 检查全部模块
./deploy/scripts/check_vllm.sh all
```

**输出示例**：

```
==========================================
  vLLM TONY 模块状态检查
  2026-06-17 02:43:27 UTC
==========================================
[OK] vLLM 进程运行中 (PID: 36601)
[INFO]   主进程: CPU=0.0%, RSS=2MB
[INFO]   子进程 PID=36611: CPU=0.0%, RSS=779MB

--- GPU 占用 ---
[OK] GPU 0: 0% util, 67925 MiB/81920 MiB (82%), 32°C
[INFO] GPU 1: 0% util, 7 MiB/81920 MiB (0%), 33°C

--- 请求统计 ---
[INFO] 累计成功请求: 6 次
[INFO] 累计输出 tokens: 2243.0
[INFO] 累计输入 tokens: 112.0
[INFO] 排队中请求: 0.0
[INFO] 执行中请求: 0.0
[OK] 抢占次数: 0.0 (健康)
[INFO] GPU KV Cache 使用率: 0.0%
[INFO] 平均端到端延迟: 13.38s
[INFO] 平均首 token 延迟: 0.0434s

--- 可用模型 ---
  - tony-qwen3-14b  (max_model_len=4096)
```

### 3.2 进程与端口检查

```bash
# 查看 PID
cat pids/model_tony.pid

# 确认进程存活
kill -0 $(cat pids/model_tony.pid) && echo "运行中" || echo "已退出"

# 确认端口监听
lsof -Pi :8005 -sTCP:LISTEN
ss -tlnp | grep 8005
```

---

## 4. GPU 资源监控

### 4.1 实时监控命令

```bash
# 实时 GPU 状态（每秒刷新）
watch -n 1 nvidia-smi

# 精简输出
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv

# 查看 GPU 上的进程
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv

# vLLM 进程 CPU / 内存
ps aux | grep vllm.entrypoints | grep -v grep
htop -p $(cat pids/model_tony.pid)
```

### 4.2 典型资源占用

| 模型 | GPU 显存 | 说明 |
|------|---------|------|
| Qwen3-14B-Instruct (fp16) | ~68 GB | 模型权重约 28GB + KV Cache 约 40GB |
| 同上 + max_model_len=8192 | ~75 GB | KV Cache 随上下文长度线性增长 |
| 同上 + max_model_len=4096 | ~68 GB | 推荐配置，留出 15% buffer |

> 显存主要组成：**模型权重** (固定) + **KV Cache** (随 max_model_len 和并发量动态变化)。

---

## 5. vLLM Prometheus 指标

vLLM 在每个服务端口上自动暴露 `/metrics` 端点（Prometheus text 格式）。

### 5.1 获取全部指标

```bash
curl -s http://127.0.0.1:8005/metrics | grep "vllm:"
```

### 5.2 核心指标速查表

#### 请求与吞吐

| 指标 | 类型 | 说明 |
|------|------|------|
| `request_success_total{finished_reason="stop"}` | Counter | 正常完成的请求总数 |
| `request_success_total{finished_reason="length"}` | Counter | 因 max_tokens 截断的请求数 |
| `num_requests_running` | Gauge | 当前正在执行的请求数 |
| `num_requests_waiting` | Gauge | 当前排队等待的请求数 |
| `num_requests_swapped` | Gauge | 被换出到 CPU 的请求数（应为 0） |

#### Token 消耗

| 指标 | 类型 | 说明 |
|------|------|------|
| `prompt_tokens_total` | Counter | 累计输入 token 数 |
| `generation_tokens_total` | Counter | 累计输出 token 数 |
| `iteration_tokens_total` | Histogram | 每次 engine step 处理的 token 数分布 |

#### 请求延迟（4 阶段生命周期）

```
Client ──[queue]──▶ Prefill ──▶ Decode (per-token) ──▶ Response
           ↑            ↑              ↑                  ↑
     queue_time    time_to_first   time_per_output    e2e_latency
```

| 指标 | 阶段 | 健康阈值 |
|------|------|---------|
| `request_queue_time_seconds` | 排队等待 | < 0.1s |
| `time_to_first_token_seconds` | Prefill → 首 token | < 2s |
| `time_per_output_token_seconds` | Decode → 每 token | < 100ms/token |
| `e2e_request_latency_seconds` | 端到端总延迟 | < 30s（取决于 max_tokens） |

#### 缓存与内存

| 指标 | 说明 | 告警阈值 |
|------|------|---------|
| `gpu_cache_usage_perc` | GPU KV Cache 使用率 (%) | > 90% 需关注 |
| `cpu_cache_usage_perc` | CPU KV Cache 使用率 (%) | > 50% 性能下降 |
| `gpu_prefix_cache_hit_rate` | Prefix Cache 命中率 | -1 = 未启用 |
| `num_preemptions_total` | 显存不足抢占次数 | **> 0 需立即处理** (扩容或降低 max_model_len) |

#### 缓存配置信息

```bash
curl -s http://127.0.0.1:8005/metrics | grep "cache_config_info"
```

输出字段解读：

| 字段 | 示例值 | 说明 |
|------|-------|------|
| `gpu_memory_utilization` | 0.85 | GPU 显存利用率上限 |
| `num_gpu_blocks` | 15668 | GPU KV Cache 总块数 |
| `num_cpu_blocks` | 1638 | CPU 换出块数（备用） |
| `block_size` | 16 | 每块 token 数 |
| `enable_prefix_caching` | False | Prefix Cache 是否启用 |

> 粗略估算：`num_gpu_blocks × block_size × 2(hidden_dim) × num_layers × dtype_size` ≈ 可用 KV Cache 字节数。

### 5.3 常用指标查询

```bash
# 请求量
curl -s http://127.0.0.1:8005/metrics | grep "request_success_total"

# 当前负载
curl -s http://127.0.0.1:8005/metrics | grep "num_requests_"

# 延迟摘要
curl -s http://127.0.0.1:8005/metrics | grep -E "e2e_request_latency_seconds_(sum|count)"

# Token 消耗
curl -s http://127.0.0.1:8005/metrics | grep "generation_tokens_total"

# KV Cache 状态
curl -s http://127.0.0.1:8005/metrics | grep -E "gpu_cache|cpu_cache|num_preemptions"

# 首 token 延迟分布
curl -s http://127.0.0.1:8005/metrics | grep "time_to_first_token_seconds_bucket"
```

---

## 6. 请求日志分析

日志文件位置：`logs/model_{module}.log`

### 6.1 实时跟踪

```bash
# 实时跟随日志
tail -f logs/model_tony.log

# 带时间戳过滤最近 100 行
tail -100 logs/model_tony.log
```

### 6.2 统计分析

```bash
# 统计总请求数
grep -c "POST /v1/chat/completions" logs/model_tony.log

# 查看最近 10 条请求
grep "POST /v1/chat/completions" logs/model_tony.log | tail -10

# 统计各 HTTP 状态码分布
grep -oP 'HTTP/1\.1" \K\d+' logs/model_tony.log | sort | uniq -c

# 查看错误日志
grep -E "ERROR|Traceback" logs/model_tony.log | tail -20

# 按小时统计请求量
grep "POST /v1/chat/completions" logs/model_tony.log | \
  grep -oP '^\d{2}:\d{2}' | cut -d: -f1 | sort | uniq -c
```

---

## 7. Nginx 反向代理

### 7.1 配置说明

配置文件：`deploy/nginx/nginx.conf`

对外统一端口 `8010`，按 URL 路径前缀路由到不同模块的 vLLM 端口：

| URL 路径 | 后端 | 端口 |
|---------|------|------|
| `/v1/rpj/*` | RPJ | 8001 |
| `/v1/xmx/*` | XMX | 8002 |
| `/v1/wzy/*` | WZY | 8003 |
| `/v1/wzm/*` | WZM | 8004 |
| `/v1/tony/*` | TONY | 8005 |
| `/v1/*` (无前缀) | TONY (默认) | 8005 |

### 7.2 验证命令

```bash
# Nginx 健康检查
curl http://127.0.0.1:8010/health
# → {"status":"ok","service":"nginx-proxy","port":8010}

# 通过 Nginx 访问模型列表
curl http://127.0.0.1:8010/v1/models

# 模块指定路由
curl http://127.0.0.1:8010/v1/tony/models

# 对话测试
curl http://127.0.0.1:8010/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "tony-qwen3-14b",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 50
  }'
```

### 7.3 Nginx 运维

```bash
# 测试配置
nginx -t

# 重载配置（不中断服务）
nginx -s reload

# 停止
nginx -s stop

# 查看 Nginx 日志
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

---

## 8. Prometheus + Grafana 集成（可选）

### 8.1 Prometheus 抓取配置

在 `prometheus.yml` 中添加：

```yaml
scrape_configs:
  - job_name: 'vllm-tony'
    scrape_interval: 15s
    static_configs:
      - targets: ['127.0.0.1:8005']
        labels:
          module: 'tony'
  - job_name: 'vllm-rpj'
    scrape_interval: 15s
    static_configs:
      - targets: ['127.0.0.1:8001']
        labels:
          module: 'rpj'
  # ... 其余模块类推
```

### 8.2 推荐 Grafana 面板（4 大 Golden Signals）

| 信号 | PromQL 示例 | 面板类型 |
|------|-----------|---------|
| **延迟** | `histogram_quantile(0.95, rate(vllm:e2e_request_latency_seconds_bucket[5m]))` | Heatmap / Time series |
| **流量** | `rate(vllm:request_success_total[1m])` | Time series |
| **错误** | `rate(vllm:request_success_total{finished_reason="stop"}[1m]) / rate(vllm:request_success_total[1m])` | Stat / Gauge |
| **饱和度** | `vllm:gpu_cache_usage_perc` + `vllm:num_requests_waiting` | Time series |

### 8.3 Grafana 变量配置

```json
{
  "name": "module",
  "type": "query",
  "query": "label_values(vllm:request_success_total, module)"
}
```

---

## 9. 故障排查

### 9.1 服务无法启动

```bash
# 1. 检查端口是否被占用
lsof -Pi :8005 -sTCP:LISTEN

# 2. 检查 GPU 是否可用
nvidia-smi

# 3. 检查模型文件是否完整
ls /root/code/vepfs/.cache/huggingface/hub/models--OpenPipe--Qwen3-14B-Instruct/snapshots/

# 4. 查看完整错误日志
cat logs/model_tony.log | grep -A 50 "ERROR\|Traceback"
```

### 9.2 请求返回 500 / 超时

```bash
# 检查 KV Cache 是否满了
curl -s http://127.0.0.1:8005/metrics | grep "gpu_cache_usage_perc"

# 检查是否有抢占
curl -s http://127.0.0.1:8005/metrics | grep "num_preemptions_total"

# 检查排队情况
curl -s http://127.0.0.1:8005/metrics | grep "num_requests_waiting"
```

处理方式：
- `gpu_cache_usage_perc` > 90%：降低 `max_model_len` 或增加 `gpu_memory_utilization`
- `num_preemptions_total` > 0：同上，或使用多 GPU
- `num_requests_waiting` 持续增长：增加并发实例

### 9.3 显存不足 (OOM)

症状：日志中出现 `CUDA out of memory` 或 `num_preemptions_total` 持续增长。

```bash
# 方案 1：降低 max_model_len
# 编辑 pipeline.sh 或设置环境变量
export VLLM_MAX_MODEL_LEN_TONY=2048

# 方案 2：降低显存利用率
export VLLM_GPU_MEMORY_UTILIZATION_TONY=0.75

# 方案 3：使用第二块 GPU
export CUDA_VISIBLE_DEVICES=0,1
```

### 9.4 模型响应质量差

```bash
# 检查是否加载了 LoRA 适配器
curl -s http://127.0.0.1:8005/metrics | grep "lora_requests_info"

# 查看 LoRA 模块列表（vLLM 启动日志）
grep "LoRA" logs/model_tony.log
```

---

## 10. 环境变量速查

所有模块通用的 vLLM 环境变量覆盖（`<MODULE>` 替换为 `RPJ|XMX|WZY|WZM|TONY`）：

| 环境变量 | 默认值 | 说明 |
|---------|-------|------|
| `VLLM_PORT_<MODULE>` | 见端口表 | 覆盖模块端口 |
| `VLLM_MAX_MODEL_LEN_<MODULE>` | 4096 (≤48GB VRAM) / 8192 | 最大上下文长度 |
| `VLLM_GPU_MEMORY_UTILIZATION_<MODULE>` | 0.85 (≤48GB) / 0.90 | GPU 显存利用率 |
| `VLLM_ENFORCE_EAGER_<MODULE>` | true | 禁用 CUDA Graph |
| `VLLM_DTYPE_<MODULE>` | auto | 推理精度 (bfloat16/float16/auto) |
| `VLLM_BASE_MODEL_<MODULE>` | OpenPipe/Qwen3-14B-Instruct | 基座模型 ID 或路径 |
| `VLLM_SERVED_MODEL_NAME_<MODULE>` | `<module>-qwen3-14b` | API 中暴露的模型名 |
| `VLLM_LORA_MODULES_<MODULE>` | (auto-discover) | 手动指定 LoRA 模块 |
| `VLLM_CHAT_TEMPLATE_<MODULE>` | `deploy/vllm/chat_templates/template_chatml.jinja` | Chat template 路径 |
