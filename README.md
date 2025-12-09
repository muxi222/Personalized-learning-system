# 🎓 学习小书童

基于AI Agent的个性化学习助手 - 智能错题分析与举一反三推荐系统

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.2+-61DAFB.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ 项目愿景

打造一个面向初、高中学生的个性化AI学习助手——"学习小书童"。它不仅是一个错题记录工具，更是一个能够深度理解学生学习状况、提供精准指导、激发学习兴趣的智能伙伴。

## 🎯 核心功能

- 📝 **智能错题管理** - 支持文本、图片OCR录入，自动解析结构化存储
- 🔍 **深度错题分析** - 利用LLM分析错因、定位知识点薄弱环节
- 💡 **举一反三** - 基于RAG技术，智能推荐同类型题目巩固
- 🎯 **个性化指导** - 动态生成学习计划和知识点复习路径
- 🤖 **模型微调** - 为学生训练专属"书童"模型
- 📊 **学习追踪** - 基于艾宾浩斯遗忘曲线的复习提醒

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (React)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  Dashboard  │  │  Questions  │  │   Review    │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└────────────────────────────┬────────────────────────────────────┘
                             │ REST API
┌────────────────────────────▼────────────────────────────────────┐
│                      Backend (FastAPI)                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    LangGraph Agents                      │   │
│  │  ┌─────────────────┐  ┌─────────────────────────────┐   │   │
│  │  │ QuestionIntake  │  │  SimilarQuestion (RAG)      │   │   │
│  │  │     Agent       │  │       Agent                 │   │   │
│  │  │ OCR→解析→存储   │  │ 向量检索→信息整合→生成引导  │   │   │
│  │  │ →Embedding→分析 │  │                             │   │   │
│  │  └─────────────────┘  └─────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  PostgreSQL   │  │    ChromaDB     │  │  LLM (OpenAI/   │
│  (结构化数据)  │  │   (向量数据)    │  │ Anthropic/Qwen) │
└───────────────┘  └─────────────────┘  └─────────────────┘
```

## 📁 项目结构

```
learning_assistant/
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── agents/             # LangGraph 智能体 ⭐
│   │   │   ├── question_intake_agent.py   # 错题录入Agent
│   │   │   ├── similar_question_agent.py  # 举一反三Agent
│   │   │   ├── state.py        # Agent状态定义
│   │   │   └── prompts.py      # Prompt模板
│   │   ├── api/v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── questions.py   # 错题API
│   │   │   │   └── guidance.py    # 学习指导API
│   │   │   └── router.py       # 路由聚合
│   │   ├── core/               # 配置管理
│   │   ├── crud/               # 数据库操作
│   │   ├── db/                 # SQLAlchemy模型
│   │   ├── schemas/            # Pydantic模型
│   │   └── services/           # 业务服务层
│   ├── main.py                 # 应用入口
│   └── tests/                  # 测试代码
├── frontend/                    # React 前端
│   └── src/
│       ├── pages/              # 页面组件
│       ├── components/         # UI组件
│       └── stores/             # 状态管理
├── training/                    # 模型训练 ⭐
│   ├── fine_tuning/
│   │   ├── scripts/
│   │   │   └── train_sft.py    # QLoRA微调脚本
│   │   ├── configs/            # 训练配置
│   │   └── data/               # 训练数据
│   └── embedding/
│       └── scripts/
│           └── embed_questions.py  # Embedding脚本
├── docker-compose.yml          # Docker编排
├── Dockerfile                  # 后端镜像
├── pyproject.toml              # Python依赖
└── README.md
```

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Docker & Docker Compose (可选)

### 1. 克隆项目

```bash
git clone https://github.com/your-repo/learning-assistant.git
cd learning-assistant
```

### 2. 后端配置

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -e ".[dev]"

# 配置环境变量
cp env.example .env
# 编辑 .env 文件，填入 API Key
```

### 3. 前端配置

```bash
cd frontend
npm install
```

### 4. 启动开发服务

```bash
# 后端 (在 backend 目录)
uvicorn main:app --reload --port 8000

# 前端 (新终端)
cd frontend
npm run dev
```

访问:
- 前端: http://localhost:3000
- API文档: http://localhost:8000/docs

### 5. Docker部署

```bash
docker-compose up -d
```

## 📚 API接口

### 错题管理

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/questions/` | 提交新错题 (触发Agent分析) |
| GET | `/api/v1/questions/` | 获取错题列表 |
| GET | `/api/v1/questions/{id}` | 获取错题详情 |

### 学习指导

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/guidance/similar-questions` | 举一反三 (RAG) |
| GET | `/api/v1/guidance/learning-plan` | 获取学习计划 |
| GET | `/api/v1/guidance/student-profile` | 获取学生画像 |

## 🤖 Agent工作流

### 错题录入Agent (QuestionIntakeAgent)

```
用户输入 → OCR处理 → 语义解析 → 存储数据库 → 生成Embedding → 错因分析 → 更新结果
```

### 举一反三Agent (SimilarQuestionAgent)  

```
加载原题 → 向量检索(RAG-Retrieval) → 获取详情 → 生成引导(RAG-Generation)
```

## 📈 模型微调

项目支持使用QLoRA对开源模型进行微调，训练专属"学习小书童"：

```bash
# 准备数据
cd training/fine_tuning

# 运行微调 (推荐使用 Qwen 或 Llama 3)
python scripts/train_sft.py \
    --model Qwen/Qwen2-7B-Instruct \
    --dataset ./data/sample_instructions.jsonl \
    --output ./output/learning_assistant_lora \
    --epochs 3
```

## 🔮 智能化升级方向

根据设计文档第7节，后续可扩展：

1. **知识图谱 (GraphRAG)** - 表达知识点之间的依赖关系
2. **自我反思 (Self-Correction)** - 从用户反馈中学习改进
3. **长期记忆** - 动态更新学生画像，周期性增量微调
4. **多模态** - 直接理解题目中的图形、公式
5. **工具调用** - 集成计算器、代码解释器、搜索引擎

## 📝 开发规范

- Python: PEP 8, 使用 black + isort 格式化
- TypeScript/React: ESLint + Prettier
- Agent: 按学科模块化，独立Prompt模板

## 📄 License

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph) - Agent编排框架
- [FastAPI](https://fastapi.tiangolo.com/) - 高性能API框架  
- [ChromaDB](https://www.trychroma.com/) - 向量数据库
- [HuggingFace](https://huggingface.co/) - 模型微调工具
