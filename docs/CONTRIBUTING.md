# Contributing to AI 学习小书童

感谢你对本项目的兴趣！我们欢迎各种形式的贡献。

## 行为准则

参与本项目即表示你同意遵守我们的行为准则，创建一个友好、包容的社区环境。

## 如何贡献

### 报告 Bug

1. 在 Issues 中搜索是否已有相同问题
2. 如果没有，创建新的 Issue
3. 使用清晰的标题描述问题
4. 提供复现步骤、期望行为和实际行为
5. 附上相关日志和截图

### 提交功能建议

1. 在 Issues 中创建 Feature Request
2. 描述功能的使用场景
3. 说明为什么这个功能对项目有价值

### 提交代码

1. Fork 本仓库
2. 创建功能分支: `git checkout -b feature/your-feature`
3. 提交更改: `git commit -m 'Add some feature'`
4. 推送分支: `git push origin feature/your-feature`
5. 创建 Pull Request

## 开发环境设置

```bash
# 克隆仓库
git clone https://github.com/your-repo/learning-assistant.git
cd learning-assistant

# 安装依赖
make install

# 运行测试确保环境正常
make test
```

## 代码规范

### Python

- 遵循 PEP 8 规范
- 使用 ruff 进行代码检查和格式化
- 使用 mypy 进行类型检查
- 所有公共函数需要 docstring

```bash
# 检查代码
make lint

# 格式化代码
make format

# 类型检查
make type-check
```

### React/TypeScript

- 使用 ESLint + Prettier
- 组件使用函数式组件 + Hooks
- 使用 TypeScript 严格模式

### 提交信息规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

类型:

- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 构建/工具相关

示例:

```
feat(ocr): add Gemini 2.5 Flash support for exam grading

- Implement GeminiOCRService
- Add subject-specific prompts
- Support thinking_config for deep analysis
```

## 目录结构

```
backend/app/
├── agents/        # LangGraph Agent 实现
├── api/           # API 端点
├── core/          # 核心配置
├── crud/          # 数据库操作
├── db/            # 数据库模型
├── schemas/       # Pydantic 模型
└── services/      # 业务逻辑服务
```

### 添加新 Agent

1. 在 `backend/app/agents/` 创建新文件
2. 继承 `AgentState` 定义状态
3. 实现各个节点函数
4. 使用 `StateGraph` 构建工作流
5. 在 `__init__.py` 中导出
6. 在 `tasks.py` 中添加 Celery 任务

### 添加新 API 端点

1. 在 `backend/app/api/v1/endpoints/` 创建新文件
2. 使用 FastAPI Router
3. 在 `router.py` 中注册

## 测试

```bash
# 运行所有测试
make test

# 运行单元测试
make test-unit

# 运行集成测试
make test-integration

# 生成覆盖率报告
pytest --cov=backend/app --cov-report=html
```

## Pull Request 检查清单

- [ ] 代码符合项目规范
- [ ] 添加了必要的测试
- [ ] 所有测试通过
- [ ] 更新了相关文档
- [ ] 提交信息符合规范

## 获取帮助

如有问题，可以:

- 在 Issues 中提问
- 查看项目文档
- 联系维护者

感谢你的贡献！
