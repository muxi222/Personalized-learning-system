# 灵动书童：你的 AI 个性化学习引擎

基于 LangGraph 的个性化学习助手 - 智能错题分析与举一反三推荐系统

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.2+-61DAFB.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 项目愿景

打造一个面向初、高中学生的个性化 AI 学习助手。它不仅是一个错题记录工具，更是一个能够深度理解学生学习状况、提供精准指导、激发学习兴趣的智能伙伴。

## 核心功能

### 📸 AI智能批改
- **试卷上传**：支持拍照或上传试卷图片（JPG/PNG/HEIC）
- **自动识别**：Gemini 2.5 Flash多模态AI识别题目和答案
- **智能评分**：自动打分、计算正确率、生成批改图片
- **错题自动入库**：识别出的错题自动进入错题本，按学科分类存储
- **批改历史**：完整记录每次批改，支持查看和统计分析

### 📝 智能错题管理
- **双模式录入**：文字输入 或 图片上传（OCR自动识别）
- **结构化存储**：自动解析题目、答案、知识点等信息
- **来源追踪**：区分手动录入和AI批注识别的错题
- **图片管理**：按学科分类存储，支持点击放大查看

### 📊 学习统计分析
- **多周期统计**：支持周、月、季度、年度数据统计
- **学科分析**：各学科正确率、错题数、批改次数
- **趋势可视化**：时间序列数据，展示学习进步曲线
- **薄弱点识别**：自动汇总高频错误知识点

### 🔍 深度错题分析
- **AI错因分析**：利用 LLM 深度分析错误原因
- **知识点定位**：精准定位薄弱环节
- **举一反三**：基于 FAISS + BM25 混合检索推荐同类题目

### 🎯 个性化指导
- **学习计划**：动态生成个性化学习路径
- **复习提醒**：基于艾宾浩斯遗忘曲线的智能提醒

## 技术架构

### 5模块分布式架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                           │
│                    Smart Subject-Based Routing                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │  Dashboard  │  │  Questions  │  │  ExamUpload │  │  Advisor  │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘ │
└───────────┬─────────┬─────────┬─────────┬─────────┬─────────────────┘
            │ :6001   │ :6002   │ :6003   │ :6004   │ :6005
            ▼         ▼         ▼         ▼         ▼
┌──────────────┬──────────┬──────────┬──────────┬──────────────┐
│  RPJ Module  │   XMX    │   WZY    │   WZM    │ TONY Module  │
│  语文英语政治 │  经济学   │  数理    │   化学   │ 历史地理其他  │
│              │          │          │          │              │
│ ┌──────────┐ │┌────────┐│┌────────┐│┌────────┐│ ┌──────────┐ │
│ │ FastAPI  │ ││FastAPI ││ FastAPI ││FastAPI ││ │ FastAPI  │ │
│ │   API    │ ││  API   ││  API   ││  API   ││ │   API    │ │
│ └──────────┘ │└────────┘│└────────┘│└────────┘│ └──────────┘ │
│              │          │          │          │              │
│ ┌──────────┐ │┌────────┐│┌────────┐│┌────────┐│ ┌──────────┐ │
│ │  Celery  │ ││ Celery ││ Celery ││ Celery ││ │  Celery  │ │
│ │  Agent   │ ││ Agent  ││ Agent  ││ Agent  ││ │  Agent   │ │
│ └──────────┘ │└────────┘│└────────┘│└────────┘│ └──────────┘ │
│              │          │          │          │              │
│ queue_rpj    │queue_xmx │queue_wzy │queue_wzm │ queue_tony   │
└──────────────┴──────────┴──────────┴──────────┴──────────────┘
       │              │         │         │            │
       └──────────────┴─────────┴─────────┴────────────┘
                             │
        ┌────────────────────┼────────────────────┬──────────────┐
        ▼                    ▼                    ▼              ▼
┌───────────────┐  ┌─────────────────┐  ┌───────────────┐  ┌─────────┐
│ SQLite (共享) │  │ FAISS (按模块)   │  │  Redis (共享) │  │   LLM   │
│  统一数据库    │  │ rpj/xmx/wzy/    │  │  Celery消息   │  │ Gemini  │
│  逻辑隔离      │  │ wzm/tony/       │  │  队列与缓存   │  │ OpenAI  │
└───────────────┘  └─────────────────┘  └───────────────┘  └─────────┘
```

**核心特性:**

- **5个独立模块**: 每个模块处理特定学科，可独立启动/扩展
- **智能路由**: 前端根据学科自动选择模块端口
- **共享数据库**: 统一SQLite，逻辑隔离
- **独立向量库**: 每模块独立FAISS/BM25索引
- **模块化队列**: 独立Celery队列，任务隔离
- **统一认证**: 一次登录访问所有学科

## 项目结构

```
learning_assistant/
├── backend/                     # FastAPI 后端
│   ├── core/                    # 共享核心层 (所有模块共用)
│   │   ├── base_config.py      # 基础配置类
│   │   ├── agents/
│   │   │   ├── base_agent.py   # Agent基类
│   │   │   ├── state.py        # Agent状态定义
│   │   │   └── prompts.py      # Prompt模板 (10个学科)
│   │   ├── db/                 # 共享数据库模型
│   │   ├── services/           # 共享服务层
│   │   │   ├── hybrid_search_service.py
│   │   │   ├── gemini_ocr_service.py
│   │   │   ├── embedding_service.py
│   │   │   └── llm_service.py
│   │   ├── crud/               # 共享CRUD操作
│   │   └── schemas/            # 共享Pydantic模型
│   │
│   └── modules/                # 模块化应用层 (5个独立模块)
│       ├── rpj/    (6001) → 语文、英语、政治
│       │   ├── config.py              # RPJ模块配置
│       │   ├── main.py                # FastAPI应用
│       │   ├── celery_app.py          # Celery配置 (queue_rpj)
│       │   ├── api/endpoints/         # API端点 (9个)
│       │   └── agents/                # Agent实例 (3个)
│       │
│       ├── xmx/    (6002) → 经济学
│       ├── wzy/    (6003) → 数学、物理
│       ├── wzm/    (6004) → 化学
│       └── tony/   (6005) → 历史、地理、其他
│
├── frontend/                    # React 前端
│   └── src/
│       ├── config/
│       │   └── moduleRouting.js    # 智能路由配置 ⭐
│       ├── lib/
│       │   └── api.js              # 动态API客户端 ⭐
│       ├── pages/
│       │   ├── ExamUpload.jsx      # AI批改
│       │   ├── QuestionList.jsx
│       │   └── ...
│       ├── components/
│       └── stores/
│
├── deploy/                      # 部署配置
│   ├── docker/
│   │   ├── Dockerfile.api
│   │   └── docker-compose.split.yml
│   └── scripts/
│       └── start.sh            # 多模块启动脚本 ⭐ (586行)
│
├── data/                        # 数据目录
│   ├── sqlite/                 # 共享SQLite数据库
│   ├── faiss/                  # 按模块分离的FAISS索引
│   │   ├── rpj/  xmx/  wzy/  wzm/  tony/
│   ├── bm25/                   # 按模块分离的BM25索引
│   │   ├── rpj/  xmx/  wzy/  wzm/  tony/
│   └── uploads/                # 用户上传 (按用户隔离)
│
├── MODULE_SPLIT_IMPLEMENTATION.md   # 模块化实施详细指南
├── MODULE_SPLIT_QUICKSTART.md       # 模块化快速启动指南
├── MODULE_SPLIT_COMPLETION_REPORT.md # 模块化完成报告
├── CLAUDE.md                   # Claude Code 工作指南
└── README.md                   # 本文件
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Redis (可选，使用 Docker 自动配置)

### ⭐ 推荐：使用多模块启动脚本

```bash
# Linux/Mac - 启动所有模块 + 前端
./deploy/scripts/start.sh all

# 启动单个模块
./deploy/scripts/start.sh api_tony      # TONY模块 API (历史、地理)
./deploy/scripts/start.sh agent_tony    # TONY模块 Agent Worker

# 启动所有API (5个模块)
./deploy/scripts/start.sh api_all

# 查看所有模块状态
./deploy/scripts/start.sh status

# 停止所有服务
./deploy/scripts/start.sh stop_all

# Windows
deploy\scripts\start.bat all
```

**模块端口:**

- RPJ (6001): 语文、英语、政治
- XMX (6002): 经济学
- WZY (6003): 数学、物理
- WZM (6004): 化学
- TONY (6005): 历史、地理、其他

### 方式二：使用 Makefile (传统方式，不推荐)

```bash
# 安装依赖
make install

# 启动开发环境 (需要手动配置多模块)
make dev

# 查看所有命令
make help
```

### 方式三：使用 Docker

```bash
# 标准部署
make docker-up

# 服务拆分部署 (API + Agent 分离)
make docker-split
```

### 方式四：手动启动 (开发调试用)

```bash
# 1. 安装后端依赖
pip install -e ".[dev]"

# 2. 配置环境变量
cp env.example .env
# 编辑 .env 文件，填入 GEMINI_API_KEY 等

# 3. 启动单个模块 API (例如 TONY 模块)
cd backend
export PYTHONPATH="${PWD}/backend:${PYTHONPATH}"
uvicorn backend.modules.tony.main:app --reload --port 6005

# 4. 启动单个模块 Agent Worker (新终端)
cd backend
celery -A backend.modules.tony.celery_app worker --loglevel=info --queues=queue_tony

# 5. 启动前端 (新终端)
cd frontend && npm install && npm run dev
```

**访问地址:**

- 前端: <http://localhost:8000>
- RPJ模块 API文档: <http://localhost:6001/docs> (语文、英语、政治)
- XMX模块 API文档: <http://localhost:6002/docs> (经济学)
- WZY模块 API文档: <http://localhost:6003/docs> (数学、物理)
- WZM模块 API文档: <http://localhost:6004/docs> (化学)
- TONY模块 API文档: <http://localhost:6005/docs> (历史、地理、其他)

## API 接口

**注意**: 所有API端点在5个模块上都有实现，但每个模块只处理其指定的学科。前端会根据学科自动路由到正确的模块。

### 错题管理 (所有模块)

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/questions/` | 提交新错题（文字） |
| POST | `/api/v1/questions/ocr` | 提交新错题（图片OCR） |
| GET | `/api/v1/questions/` | 获取错题列表 |
| GET | `/api/v1/questions/{id}` | 获取错题详情 |

### OCR 试卷批改

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/ocr/analyze` | 上传试卷图片进行 OCR 分析 |
| GET | `/api/v1/ocr/images/{subject}/{filename}` | 获取批改后的图片 |

### 批改历史

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/corrections/` | 获取批改记录列表（分页+筛选） |
| GET | `/api/v1/corrections/{id}` | 获取批改记录详情 |
| GET | `/api/v1/corrections/statistics/{period}` | 获取统计数据（week/month/quarter/year） |
| DELETE | `/api/v1/corrections/{id}` | 删除批改记录 |

### 学习建议

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/learning/profile` | 获取学习画像 |
| GET | `/api/v1/learning/recommendations` | 获取个性化推荐 |
| GET | `/api/v1/learning/study-plan` | 获取学习计划 |
| GET | `/api/v1/learning/similar-questions/{id}` | 获取相似题目 |
| GET | `/api/v1/learning/summary` | 获取学习总结 |

## Agent 工作流

### 错题录入 Agent

```
用户输入 → OCR处理 → 语义解析 → 存储数据库 → 生成Embedding → 错因分析 → 更新结果
```

### OCR 批改 Agent (Gemini 2.5 Flash)

```
试卷图片 → Gemini OCR → 题目识别 → 答案批改 → 错误分析 → 保存错题 → 推荐练习
```

### 举一反三 Agent (FAISS + BM25 混合检索)

```
原题 → FAISS向量检索 → BM25关键词检索 → 融合排序 → 相似度过滤 → 生成引导
```

## 前端页面

| 路由 | 页面 | 功能 |
|------|------|------|
| `/` | 仪表盘 | 学习概况、快捷入口 |
| `/exam-upload` | **AI智能批改** | 上传试卷、自动批改、查看分析 ⭐ |
| `/corrections` | **批改历史** | 查看所有批改记录、多维度统计 ⭐ |
| `/submit` | 录入错题 | 文字输入或图片上传（OCR识别） |
| `/questions` | 错题本 | 所有错题列表、筛选、搜索 |
| `/questions/:id` | 错题详情 | 错因分析、举一反三、图片放大 |
| `/learning` | 学习建议 | 个性化学习建议和计划 |
| `/review` | 复习 | 复习提醒、间隔重复 |

**核心交互**：
- 所有图片支持点击放大（全屏查看器）
- 批改历史支持周/月/季/年统计切换
- 错题自动标记来源（手动/AI批注）
- 学科颜色编码，视觉区分

## 混合检索策略

系统采用 FAISS + BM25 混合检索，结合语义和关键词两种匹配方式：

```python
# 权重配置 (env.example)
HYBRID_SEARCH_VECTOR_WEIGHT=0.6  # FAISS 语义相似度权重
HYBRID_SEARCH_BM25_WEIGHT=0.4    # BM25 关键词匹配权重
HYBRID_SEARCH_SIMILARITY_THRESHOLD=0.55  # 最低相似度阈值
```

检索流程：
1. **FAISS 向量检索**: 基于 embedding 的语义相似度
2. **BM25 关键词检索**: 基于 TF-IDF 的精确匹配
3. **分数融合**: 加权合并两种检索结果
4. **去重过滤**: 按相似度阈值过滤

## 部署架构

### 单体部署

```yaml
# docker-compose.yml
services:
  backend:      # API + Agent 一体
  frontend:
  redis:
```

### 微服务部署

```yaml
# deploy/docker/docker-compose.split.yml
services:
  api:          # 仅 API 服务
  agent:        # 仅 Agent Worker (可水平扩展)
  frontend:
  redis:
```

## 开发规范

- **Python**: PEP 8, 使用 ruff 格式化和检查
- **React**: ESLint + Prettier
- **Agent**: 按学科模块化，独立 Prompt 模板
- **测试**: pytest (后端), vitest (前端)

```bash
# 代码检查
make lint

# 格式化
make format

# 运行测试
make test
```

## 贡献指南

欢迎贡献代码！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

## License

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph) - Agent 编排框架
- [FastAPI](https://fastapi.tiangolo.com/) - 高性能 API 框架
- [FAISS](https://github.com/facebookresearch/faiss) - 向量相似度搜索
- [Gemini](https://ai.google.dev/) - OCR 与多模态分析
