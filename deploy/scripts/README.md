## `deploy/scripts/` 脚本说明

本目录包含两类脚本（刻意区分）：

### 1) 在线服务启动脚本（API/Agent/Frontend/Docker）

- `start.sh` / `start_module.sh`：本地（conda）启动
- `start_mcp.sh`：本地（conda）启动 MCP servers（Phase 1: tony retrieval-mcp）
- `start-docker.sh` / `docker-up.sh`：Docker 多模块启动

### 2) 离线流水线脚本（知识库 / 数据集 / 微调 / 模型服务化）

- `pipeline.sh`：统一入口（支持 `--module`）

示例：

```bash
# 构建 tony GraphRAG KB
./deploy/scripts/pipeline.sh kb --module tony --build-index --embedding-backend hash

# 生成训练数据（SFT + 偏好）
./deploy/scripts/pipeline.sh datasets --module tony

# 训练（SFT / DPO）
./deploy/scripts/pipeline.sh train-sft --module tony
./deploy/scripts/pipeline.sh train-dpo --module tony

# 启动/停止模型服务（vLLM docker compose）
./deploy/scripts/pipeline.sh serve-model --module tony up
./deploy/scripts/pipeline.sh serve-model --module tony down
```

