## Tony 模型部署（vLLM / 工业常见方案）

这里提供 **可落地的部署骨架**：本地 `docker compose`（开发/验收） + K8s（生产/集群化）。

### 目录约定（产物放 data/）

- **LoRA/SFT/DPO 产物**：`data/training/tony/checkpoints/`
- **合并后的可推理模型（可选）**：`data/training/tony/models/merged/`
- **推理服务配置**：`data/training/tony/serving/`

### 本地/单机（docker compose）

1. 确保你有 GPU / CUDA 驱动（或改用 CPU/小模型做烟测）
2. 准备模型目录（示例）：
- 基座：HF Hub `OpenPipe/Qwen3-14B-Instruct`
   - LoRA：`data/training/tony/checkpoints/sft_lora`
3. 启动：

```bash
docker compose -f training/modules/tony/serving/docker-compose.vllm.yml up -d
```

服务默认暴露 OpenAI-compatible 接口（vLLM）。

### 生产/集群（K8s）

`training/modules/tony/serving/k8s/` 提供基础清单：
- Deployment + Service
- HPA（按 QPS/延迟指标需要接 Prometheus Adapter）

TODO（生产落地必做）：
- GPU 调度（`nvidia.com/gpu`）、节点亲和性、PDB
- 多副本权重同步（建议：模型放对象存储 + initContainer 拉取）
- 灰度发布（Argo Rollouts / Flagger）
- 观测：请求日志、token 计数、延迟、错误率、SLO

