#!/bin/bash
# Docker Compose 快速启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

# 创建数据目录
mkdir -p data/{sqlite,faiss,bm25,uploads,redis} logs

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "[INFO] 创建 .env 文件..."
    cp env.example .env
    echo "[WARN] 请编辑 .env 文件配置 API Keys"
fi

# 启动服务
echo "[INFO] 启动 Docker 服务..."

if command -v docker-compose &> /dev/null; then
    docker-compose "$@"
else
    docker compose "$@"
fi
