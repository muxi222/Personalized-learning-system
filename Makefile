# =============================================================================
# AI 学习小书童 - Makefile
#
# 项目构建、测试、部署的统一入口
# 参考 Google/Facebook 开源项目规范
# =============================================================================

.PHONY: help install dev test lint format build docker-up docker-down clean

# 默认目标
.DEFAULT_GOAL := help

# 变量定义
PYTHON := python3
PIP := pip
DOCKER_COMPOSE := docker compose
PROJECT_NAME := learning-assistant

# ============ 帮助信息 ============
help:
	@echo "AI 学习小书童 - 可用命令:"
	@echo ""
	@echo "  开发环境:"
	@echo "    make install      安装依赖"
	@echo "    make dev          启动开发服务器"
	@echo "    make dev-api      仅启动 API 服务"
	@echo "    make dev-agent    仅启动 Agent Worker"
	@echo "    make dev-frontend 启动前端开发服务器"
	@echo ""
	@echo "  代码质量:"
	@echo "    make test         运行测试"
	@echo "    make lint         代码检查"
	@echo "    make format       格式化代码"
	@echo "    make type-check   类型检查"
	@echo ""
	@echo "  Docker 部署:"
	@echo "    make docker-up    启动 Docker 服务"
	@echo "    make docker-down  停止 Docker 服务"
	@echo "    make docker-build 构建 Docker 镜像"
	@echo "    make docker-logs  查看日志"
	@echo "    make docker-split 启动拆分部署"
	@echo ""
	@echo "  其他:"
	@echo "    make clean        清理临时文件"
	@echo "    make init-db      初始化数据库"

# ============ 开发环境 ============
install:
	@echo "安装 Python 依赖..."
	$(PIP) install -e ".[dev]"
	@echo "安装前端依赖..."
	cd frontend && npm install

dev:
	@echo "启动开发环境..."
	./deploy/scripts/start.sh all

dev-api:
	@echo "启动 API 服务..."
	cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 6100

dev-agent:
	@echo "启动 Agent Worker..."
	celery -A backend.app.core.celery_app worker --loglevel=info

dev-frontend:
	@echo "启动前端开发服务器..."
	cd frontend && npm run dev

# ============ 代码质量 ============
test:
	@echo "运行测试..."
	pytest backend/tests -v --cov=backend/app --cov-report=term-missing

test-unit:
	@echo "运行单元测试..."
	pytest backend/tests/unit -v

test-integration:
	@echo "运行集成测试..."
	pytest backend/tests/integration -v

lint:
	@echo "代码检查..."
	ruff check backend/
	cd frontend && npm run lint

format:
	@echo "格式化代码..."
	ruff format backend/
	cd frontend && npm run format

type-check:
	@echo "类型检查..."
	mypy backend/app --ignore-missing-imports

# ============ Docker 部署 ============
docker-up:
	@echo "启动 Docker 服务..."
	mkdir -p data/{sqlite,faiss,bm25,uploads,redis} logs
	$(DOCKER_COMPOSE) up -d

docker-down:
	@echo "停止 Docker 服务..."
	$(DOCKER_COMPOSE) down

docker-build:
	@echo "构建 Docker 镜像..."
	$(DOCKER_COMPOSE) build

docker-logs:
	@echo "查看日志..."
	$(DOCKER_COMPOSE) logs -f

docker-split:
	@echo "启动拆分部署..."
	mkdir -p data/{sqlite,faiss,bm25,uploads,redis} logs
	$(DOCKER_COMPOSE) -f deploy/docker/docker-compose.split.yml up -d

docker-split-down:
	@echo "停止拆分部署..."
	$(DOCKER_COMPOSE) -f deploy/docker/docker-compose.split.yml down

docker-monitoring:
	@echo "启动监控服务..."
	$(DOCKER_COMPOSE) -f deploy/docker/docker-compose.split.yml --profile monitoring up -d

# ============ 数据库 ============
init-db:
	@echo "初始化数据库..."
	mkdir -p data/sqlite
	$(PYTHON) -c "from backend.app.db.session import init_db; import asyncio; asyncio.run(init_db())"

migrate:
	@echo "运行数据库迁移..."
	alembic upgrade head

# ============ 清理 ============
clean:
	@echo "清理临时文件..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml 2>/dev/null || true
	cd frontend && rm -rf node_modules/.cache 2>/dev/null || true

clean-data:
	@echo "⚠️  警告: 即将删除所有数据!"
	@read -p "确认删除? [y/N] " confirm && [ "$$confirm" = "y" ] && rm -rf data/* logs/*

# ============ 版本发布 ============
version:
	@$(PYTHON) -c "from backend.app.core.config import settings; print(settings.APP_VERSION)"

release-patch:
	@echo "发布补丁版本..."
	bump2version patch

release-minor:
	@echo "发布次要版本..."
	bump2version minor

release-major:
	@echo "发布主要版本..."
	bump2version major
