# AI 学习小书童

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

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend (React + Vite)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │  Dashboard  │  │  Questions  │  │  ExamUpload │  │  Advisor  │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘ │
└────────────────────────────┬────────────────────────────────────────┘
                             │ REST API
┌────────────────────────────▼────────────────────────────────────────┐
│                      Backend (FastAPI)                               │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    LangGraph Agents                             │ │
│  │  ┌──────────────┐  ┌─────────────┐  ┌───────────────────────┐ │ │
│  │  │QuestionIntake│  │   OCR Agent │  │  SimilarQuestion      │ │ │
│  │  │    Agent     │  │(Gemini 2.5) │  │      Agent (RAG)      │ │ │
│  │  └──────────────┘  └─────────────┘  └───────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                              │                                       │
│  ┌───────────────┐  ┌────────┴────────┐  ┌─────────────────────┐   │
│  │   API Layer   │  │  Service Layer  │  │    Celery Worker    │   │
│  │  (endpoints)  │  │ (hybrid search) │  │ (async processing)  │   │
│  └───────────────┘  └─────────────────┘  └─────────────────────┘   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┬──────────────┐
        ▼                    ▼                    ▼              ▼
┌───────────────┐  ┌─────────────────┐  ┌───────────────┐  ┌─────────┐
│    SQLite     │  │  FAISS + BM25   │  │     Redis     │  │  LLM    │
│  (结构化数据)  │  │  (混合向量检索)  │  │  (缓存/队列)  │  │(Gemini/ │
│               │  │                 │  │               │  │ OpenAI) │
└───────────────┘  └─────────────────┘  └───────────────┘  └─────────┘
```

## 项目结构

```
learning_assistant/
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── agents/             # LangGraph 智能体
│   │   │   ├── question_intake_agent.py   # 错题录入 Agent
│   │   │   ├── similar_question_agent.py  # 举一反三 Agent
│   │   │   ├── ocr_agent.py              # OCR 批改 Agent
│   │   │   ├── state.py                  # Agent 状态定义
│   │   │   ├── prompts.py                # Prompt 模板
│   │   │   └── tasks.py                  # Celery 异步任务
│   │   ├── api/v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── questions.py   # 错题 API
│   │   │   │   ├── ocr.py         # OCR API
│   │   │   │   ├── learning.py    # 学习建议 API
│   │   │   │   └── guidance.py    # 学习指导 API
│   │   │   └── router.py
│   │   ├── core/               # 核心配置
│   │   │   ├── config.py       # 配置管理
│   │   │   └── celery_app.py   # Celery 配置
│   │   ├── crud/               # 数据库操作
│   │   ├── db/                 # SQLAlchemy 模型
│   │   ├── schemas/            # Pydantic 模型
│   │   └── services/           # 业务服务层
│   │       ├── hybrid_search_service.py  # FAISS+BM25 混合检索
│   │       ├── gemini_ocr_service.py     # Gemini OCR 服务
│   │       ├── learning_advisor_service.py
│   │       ├── embedding_service.py
│   │       └── llm_service.py
│   ├── main.py                 # 应用入口
│   └── tests/
├── frontend/                    # React 前端
│   └── src/
│       ├── pages/
│       │   ├── ExamUpload.jsx    # AI 批改页面
│       │   ├── LearningAdvisor.jsx
│       │   └── ...
│       ├── components/
│       └── stores/
├── deploy/                      # 部署配置
│   ├── docker/
│   │   ├── Dockerfile.api       # API 服务镜像
│   │   ├── Dockerfile.agent     # Agent Worker 镜像
│   │   └── docker-compose.split.yml
│   └── scripts/
│       ├── start.sh            # Linux/Mac 启动脚本
│       ├── start.bat           # Windows 启动脚本
│       └── docker-up.sh
├── data/                        # 数据目录 (本地持久化)
│   ├── sqlite/                 # SQLite 数据库
│   ├── faiss/                  # FAISS 向量索引
│   ├── bm25/                   # BM25 倒排索引
│   ├── uploads/                # 用户上传文件（按用户隔离）
│   │   └── {username_email}/   # 用户专属目录
│   │       ├── corrections/    # AI批注图片
│   │       │   ├── math/      # 数学试卷
│   │       │   ├── english/   # 英语试卷
│   │       │   └── ...        # 其他学科
│   │       └── questions/     # 错题图片
│   │           ├── math/      # 数学错题
│   │           ├── english/   # 英语错题
│   │           └── ...        # 其他学科
│   └── redis/                  # Redis 数据
├── nginx/                       # Nginx 配置
├── docker-compose.yml          # 标准 Docker 编排
├── Makefile                    # 构建命令
├── pyproject.toml              # Python 依赖
└── env.example                 # 环境变量模板
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Redis (可选，使用 Docker 自动配置)

### 方式一：使用启动脚本

```bash
# Linux/Mac
./deploy/scripts/start.sh all

# Windows
deploy\scripts\start.bat all
```

### 方式二：使用 Makefile

```bash
# 安装依赖
make install

# 启动开发环境
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

### 方式四：手动启动

```bash
# 1. 安装后端依赖
pip install -e ".[dev]"

# 2. 配置环境变量
cp env.example .env
# 编辑 .env 文件，填入 GEMINI_API_KEY 等

# 3. 启动后端
cd backend && uvicorn main:app --reload --port 6000

# 4. 启动前端 (新终端)
cd frontend && npm install && npm run dev
```

访问:
- 前端: http://localhost:8000
- API 文档: http://localhost:6000/docs

## API 接口

### 错题管理

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
