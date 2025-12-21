# 环境设置与启动指南

## 前置要求

- **Conda**: Anaconda 或 Miniconda
- **Python**: 3.10+
- **Node.js**: 16+ (用于前端)
- **Redis**: 用于任务队列

## 快速开始

### 1. 创建 Conda 环境

```bash
# 创建环境
conda create -n 312_edu python=3.10 -y

# 激活环境
conda activate 312_edu

# 安装依赖
pip install -r requirements.txt

# 安装项目（开发模式）
pip install -e .
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp env.example .env

# 编辑配置文件
vim .env
```

必需的环境变量：
- `OPENAI_API_KEY`: OpenAI API 密钥
- `ANTHROPIC_API_KEY`: Anthropic API 密钥（可选）
- `GOOGLE_API_KEY`: Google Gemini API 密钥（用于 OCR）
- `REDIS_URL`: Redis 连接地址

### 3. 启动服务

```bash
# 进入脚本目录
cd deploy/scripts

# 启动所有服务
./start.sh

# 仅启动 API 服务
./start.sh api

# 仅启动 Agent Worker
./start.sh agent

# 仅启动前端
./start.sh frontend

# 查看服务状态
./start.sh status

# 停止所有服务
./start.sh stop
```

### 4. 初始化数据目录

首次运行前，创建必要的目录结构：

```bash
# 创建基础数据目录
mkdir -p data/uploads data/faiss data/bm25 data/sqlite logs

# 注意：用户专属目录会在用户首次上传时自动创建
# 格式：data/uploads/{username_email}/corrections/{subject}/
#      data/uploads/{username_email}/questions/{subject}/
```

### 5. 访问服务

- **API 文档**: http://localhost:6000/docs
- **前端界面**: http://localhost:8000

### 6. 功能使用指南

#### AI智能批改
1. 访问 http://localhost:8000/exam-upload
2. 上传试卷图片（支持JPG、PNG、HEIC）
3. 选择学科和年级
4. 等待AI分析（5-30秒）
5. 查看批改结果和详细分析
6. 错题自动进入错题本

#### 批改历史
1. 访问 http://localhost:8000/corrections
2. 查看所有批改记录
3. 切换时间周期（周/月/季/年）
4. 按学科筛选
5. 查看各学科表现统计
6. 点击图片放大查看

#### 错题录入
1. 访问 http://localhost:8000/submit
2. 选择输入模式：
   - **文字输入**：手动输入题目内容
   - **图片上传**：拍照上传，AI自动识别
3. 填写学科和难度
4. 提交后AI自动分析
5. 生成举一反三题目

#### 错题本
1. 访问 http://localhost:8000/questions
2. 查看所有错题（包含AI批注识别的）
3. 按学科、难度筛选
4. 查看错因分析和举一反三

## 依赖说明

**requirements.txt** 包含了所有项目依赖：
- 核心运行时依赖（FastAPI、LangChain、SQLAlchemy 等）
- 开发工具（pytest、black、mypy、ruff 等）
- 模型微调工具（PyTorch、Transformers、PEFT 等）

**注意**: 如需 GPU 支持，请根据 CUDA 版本参考 [PyTorch 官方文档](https://pytorch.org/get-started/locally/) 安装对应版本的 PyTorch。

## 项目结构

```
learning_assistant/
├── backend/              # 后端代码
│   ├── app/             # FastAPI 应用
│   ├── main.py          # 应用入口
│   └── tests/           # 测试代码
├── frontend/            # 前端代码
├── scripts/             # 工具脚本
├── deploy/              # 部署相关
│   └── scripts/         # 启动脚本
├── data/                # 数据目录
├── requirements.txt     # Python 依赖
└── pyproject.toml       # 项目配置
```

## 常见问题

### 1. Conda 环境找不到？

确保已安装 Conda 并初始化：

```bash
conda init bash
source ~/.bashrc  # 或 source ~/.zshrc
```

### 2. Redis 连接失败？

确保 Redis 服务已启动：

```bash
# 启动 Redis
redis-server --daemonize yes

# 检查 Redis 状态
redis-cli ping
```

### 3. 模块导入错误？

确保已激活 Conda 环境：

```bash
conda activate 312_edu
```

### 4. 前端依赖安装失败？

清理缓存并重新安装：

```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

## 开发工作流

### 运行测试

```bash
conda activate 312_edu
pytest backend/tests/ -v
```

### 代码格式化

```bash
# 格式化代码
black backend/
isort backend/

# 检查代码质量
ruff backend/
mypy backend/
```

### 启动微调

```bash
conda activate 312_edu
python scripts/fine_tuning/run_qlora.py --config configs/qlora_config.yaml
```

## Docker 部署（可选）

```bash
# 使用 Docker Compose 启动
cd deploy/scripts
./start.sh docker

# 停止服务
./start.sh stop-docker
```

## 更新依赖

当项目依赖更新后：

```bash
conda activate 312_edu

# 更新 requirements.txt 中的依赖
pip install -r requirements.txt --upgrade

# 更新项目包
pip install -e . --upgrade
```
