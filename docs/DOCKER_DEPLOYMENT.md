# Docker 多模块部署指南

本指南介绍如何使用 Docker 部署和管理 AI 学习小书童的多模块架构。

## 📋 目录

- [架构概述](#架构概述)
- [快速开始](#快速开始)
- [启动脚本使用](#启动脚本使用)
- [常见场景](#常见场景)
- [服务管理](#服务管理)
- [故障排查](#故障排查)

## 🏗 架构概述

### 6 模块架构

系统包含 6 个独立模块，每个模块处理特定学科：

| 模块 | 端口 | 负责学科 |
|------|------|----------|
| DEFAULT | 6100 | 跨学科查询、图片转发 |
| RPJ | 6001 | 语文、英语、政治 |
| XMX | 6002 | 经济学 |
| WZY | 6003 | 数学、物理 |
| WZM | 6004 | 化学 |
| TONY | 6005 | 历史、地理、其他 |

### 服务组成

每个模块包含两个服务：
- **API 服务**: 处理 HTTP 请求（FastAPI）
- **Agent Worker**: 处理异步任务（Celery）

共享服务：
- **Redis**: 消息队列和缓存
- **Frontend**: 前端界面（端口 8000）

## 🚀 快速开始

### 1. 环境准备

确保已安装：
- Docker (≥ 20.10)
- Docker Compose (≥ 2.0)

检查安装：
```bash
docker --version
docker-compose --version
```

### 2. 配置环境变量

复制示例配置：
```bash
cp env.example .env
```

编辑 `.env` 文件，填入必要配置：
```bash
# LLM API 配置（必填）
LLM_API_ENDPOINT=http://your-llm-api-endpoint/v1
LLM_API_KEY=your-api-key

# Gemini 配置（可选）
GEMINI_API_KEY=your-gemini-key

# OpenAI 配置（可选）
OPENAI_API_KEY=your-openai-key

# 安全密钥（必填，生产环境请更改）
SECRET_KEY=your-super-secret-key-change-in-production
```

### 3. 启动所有服务

```bash
./deploy/scripts/start-docker.sh all
```

首次启动会自动构建镜像（需要几分钟）。

### 4. 验证服务

访问以下地址验证服务：
- 前端界面: http://localhost:8000
- DEFAULT API: http://localhost:6100/docs
- RPJ API: http://localhost:6001/docs
- 其他模块: 端口 6002-6005

## 📖 启动脚本使用

### 基本命令

```bash
# 查看帮助
./deploy/scripts/start-docker.sh help

# 查看服务状态
./deploy/scripts/start-docker.sh status

# 查看日志
./deploy/scripts/start-docker.sh logs [service]
```

### 启动服务

```bash
# 启动所有服务（6个模块 + 前端）
./deploy/scripts/start-docker.sh all

# 启动所有模块 API
./deploy/scripts/start-docker.sh api_all

# 启动所有模块 Agent Worker
./deploy/scripts/start-docker.sh agent_all

# 启动单个模块（API + Agent）
./deploy/scripts/start-docker.sh rpj
./deploy/scripts/start-docker.sh tony

# 启动单个服务
./deploy/scripts/start-docker.sh api_default    # 只启动 DEFAULT API
./deploy/scripts/start-docker.sh agent_rpj      # 只启动 RPJ Agent

# 只启动前端
./deploy/scripts/start-docker.sh frontend
```

### 停止服务

```bash
# 停止所有服务
./deploy/scripts/start-docker.sh stop

# 停止单个模块
./deploy/scripts/start-docker.sh stop rpj

# 停止前端
./deploy/scripts/start-docker.sh stop frontend
```

### 重启服务

```bash
# 重启所有服务
./deploy/scripts/start-docker.sh restart

# 重启单个模块
./deploy/scripts/start-docker.sh restart rpj
```

### 维护命令

```bash
# 重新构建镜像
./deploy/scripts/start-docker.sh build

# 清理未使用的容器和镜像
./deploy/scripts/start-docker.sh clean
```

## 🎯 常见场景

### 场景 1: 开发单个模块

只启动需要的模块以节省资源：

```bash
# 启动 RPJ 模块（语文、英语、政治）
./deploy/scripts/start-docker.sh rpj

# 启动前端（如果需要）
./deploy/scripts/start-docker.sh frontend
```

### 场景 2: 生产环境部署

启动所有服务并查看状态：

```bash
# 启动所有服务
./deploy/scripts/start-docker.sh all

# 检查状态
./deploy/scripts/start-docker.sh status

# 查看日志确保无错误
./deploy/scripts/start-docker.sh logs
```

### 场景 3: 性能测试

只启动 API 服务进行性能测试：

```bash
# 启动所有 API（不启动 Agent Worker）
./deploy/scripts/start-docker.sh api_all
```

### 场景 4: 调试特定模块

启动模块并查看实时日志：

```bash
# 启动 TONY 模块
./deploy/scripts/start-docker.sh tony

# 查看 TONY API 日志
./deploy/scripts/start-docker.sh logs api-tony

# 查看 TONY Agent 日志
./deploy/scripts/start-docker.sh logs agent-tony
```

## 🛠 服务管理

### 使用 Docker Compose 直接管理

如果需要更高级的控制，可以直接使用 Docker Compose：

```bash
# 查看运行的容器
docker-compose -f docker-compose.modules.yml ps

# 启动特定服务
docker-compose -f docker-compose.modules.yml up -d api-rpj

# 停止特定服务
docker-compose -f docker-compose.modules.yml stop api-rpj

# 查看日志
docker-compose -f docker-compose.modules.yml logs -f api-rpj

# 进入容器
docker-compose -f docker-compose.modules.yml exec api-rpj bash

# 重新构建镜像
docker-compose -f docker-compose.modules.yml build api-rpj
```

### 使用 Profiles

`docker-compose.modules.yml` 使用 profiles 来组织服务：

```bash
# 启动所有服务
docker-compose -f docker-compose.modules.yml --profile all up -d

# 只启动 RPJ 模块
docker-compose -f docker-compose.modules.yml --profile rpj up -d

# 只启动所有 API
docker-compose -f docker-compose.modules.yml --profile api up -d

# 只启动所有 Agent
docker-compose -f docker-compose.modules.yml --profile agent up -d

# 组合多个 profiles
docker-compose -f docker-compose.modules.yml --profile rpj --profile tony up -d
```

### 扩展 Agent Worker

增加 Agent Worker 数量以处理更多并发任务：

```bash
# 扩展 RPJ Agent Worker 到 3 个实例
docker-compose -f docker-compose.modules.yml up -d --scale agent-rpj=3

# 查看扩展后的容器
docker-compose -f docker-compose.modules.yml ps
```

## 🔍 故障排查

### 问题 1: 端口被占用

**现象**: 启动失败，提示端口已被占用

**解决方案**:
```bash
# 查看端口占用
lsof -i :6001

# 停止占用端口的进程
kill <PID>

# 或修改 docker-compose.modules.yml 中的端口映射
```

### 问题 2: 容器启动失败

**现象**: 容器不断重启

**解决方案**:
```bash
# 查看容器日志
./deploy/scripts/start-docker.sh logs api-rpj

# 检查健康检查
docker inspect learning-api-rpj | grep -A 10 Health

# 进入容器检查
docker exec -it learning-api-rpj bash
```

### 问题 3: Redis 连接失败

**现象**: 日志中出现 "Connection refused to redis"

**解决方案**:
```bash
# 检查 Redis 是否运行
docker ps | grep redis

# 重启 Redis
docker-compose -f docker-compose.modules.yml restart redis

# 查看 Redis 日志
./deploy/scripts/start-docker.sh logs redis
```

### 问题 4: 数据库初始化失败

**现象**: API 启动时报数据库错误

**解决方案**:
```bash
# 停止所有服务
./deploy/scripts/start-docker.sh stop

# 删除数据库文件（注意：会丢失所有数据）
rm -rf data/sqlite/*

# 重新启动
./deploy/scripts/start-docker.sh all
```

### 问题 5: 镜像构建失败

**现象**: 构建时出现依赖安装错误

**解决方案**:
```bash
# 清理 Docker 缓存
docker builder prune -a

# 重新构建（不使用缓存）
docker-compose -f docker-compose.modules.yml build --no-cache

# 或使用启动脚本
./deploy/scripts/start-docker.sh build
```

### 问题 6: 内存不足

**现象**: 容器被 OOM Kill

**解决方案**:
```bash
# 查看 Docker 资源使用
docker stats

# 增加 Docker Desktop 内存限制（推荐 ≥ 8GB）
# 或减少同时运行的服务数量

# 只启动必要的模块
./deploy/scripts/start-docker.sh rpj
```

## 📊 监控和日志

### 实时监控

```bash
# 查看所有容器资源使用
docker stats

# 查看特定容器
docker stats learning-api-rpj learning-agent-rpj
```

### 日志管理

```bash
# 查看所有服务日志
./deploy/scripts/start-docker.sh logs

# 查看特定服务日志
./deploy/scripts/start-docker.sh logs api-rpj

# 只查看最新 100 行日志
docker-compose -f docker-compose.modules.yml logs --tail=100 api-rpj

# 导出日志到文件
docker-compose -f docker-compose.modules.yml logs api-rpj > rpj.log
```

### 健康检查

```bash
# 检查所有模块健康状态
for port in 6100 6001 6002 6003 6004 6005; do
  echo "检查端口 $port..."
  curl -s http://localhost:$port/health || echo "失败"
done
```

## 🔄 升级和迁移

### 代码更新后重启

```bash
# 拉取最新代码
git pull

# 重新构建镜像
./deploy/scripts/start-docker.sh build

# 重启服务
./deploy/scripts/start-docker.sh restart
```

### 数据备份

```bash
# 备份数据目录
tar -czf backup-$(date +%Y%m%d).tar.gz data/

# 恢复数据
tar -xzf backup-20231201.tar.gz
```

## 🌐 生产环境建议

1. **使用环境变量**: 不要在代码中硬编码配置
2. **配置日志持久化**: 挂载日志目录到宿主机
3. **设置资源限制**: 在 docker-compose.yml 中配置 CPU 和内存限制
4. **使用 Nginx 反向代理**: 统一入口，支持负载均衡
5. **监控和告警**: 使用 Prometheus + Grafana 监控容器状态
6. **定期备份**: 自动备份数据库和上传文件
7. **安全加固**: 使用 HTTPS，限制容器权限

## 📚 相关文档

- [本地开发部署](./SETUP.md)
- [架构设计文档](./CLAUDE.md)
- [API 文档](http://localhost:6100/docs)

## 💡 提示

- 首次启动需要下载镜像和构建，请耐心等待
- 推荐 Docker Desktop 内存设置 ≥ 8GB
- 使用 SSD 硬盘以获得更好的性能
- 开发时可以只启动需要的模块以节省资源
