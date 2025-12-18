# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **AI批注历史系统**
  - ExamCorrection 数据库模型，完整记录批改历史
  - 按学科分类存储图片（corrections/{subject}/, questions/{subject}/）
  - 批改统计API（周/月/季度/年度）
  - 前端批改历史页面，支持筛选和时间周期切换
  - 批改结果自动创建错题记录
- **错题录入增强**
  - 支持图片上传 + OCR自动识别
  - 双模式：文字输入 / 图片上传
  - OCR识别题目、答案、知识点
- **图片查看器组件**
  - 全屏放大、缩放（50%-300%）、旋转、下载
  - 拖拽移动、滚轮缩放、键盘快捷键
  - 现代化UI，适配移动端和桌面端
  - 所有页面图片统一支持点击放大
- **错题来源追踪**
  - QuestionSourceEnum：MANUAL（手动）/ AI_CORRECTION（AI批注）
  - 错题与批注记录关联（exam_correction_id）
- FAISS + BM25 混合检索系统
- Gemini 2.5 Flash OCR 试卷批改功能
- OCR Agent (LangGraph)
- 服务拆分部署支持 (API + Agent Worker)
- 学习建议 API
- 多学科前端上传页面
- Docker 微服务部署配置
- Makefile 统一构建入口
- pre-commit 代码检查配置
- GitHub Actions CI/CD

### Changed
- 数据库从 PostgreSQL 切换到 SQLite
- 向量检索统一为 FAISS + BM25 混合方案（移除 ChromaDB 依赖）
- 数据存储统一到项目 data/ 目录，**按学科分类**存储图片
- 更新项目文档结构
- 密码哈希算法升级为 bcrypt_sha256，支持任意长度密码（最多500字符）
- bcrypt 依赖锁定到 4.x 版本以确保兼容性
- Tailwind CSS 添加 @tailwindcss/typography 插件支持

### Fixed
- Agent 目录结构整合
- **密码长度限制问题**：bcrypt 72字节限制（使用 bcrypt_sha256 + 密码归一化）
- **JWT Token 认证问题**：修正多个页面的token获取逻辑（从auth-storage获取）
- **学科类型解析**：支持中文学科名称（数学、英语等）自动映射到英文枚举
- **图片中文乱码**：改进字体加载，支持多操作系统中文字体
- **Tailwind prose 类不存在**：添加 typography 插件

## [0.1.0] - 2024-01-01

### Added
- 初始项目结构
- FastAPI 后端框架
- React + Vite 前端
- LangGraph Agent 基础架构
- 错题录入 Agent
- 举一反三 Agent
- 用户认证系统
- SQLAlchemy ORM 模型
- Celery 异步任务队列
- Docker Compose 部署配置

[Unreleased]: https://github.com/your-repo/learning-assistant/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-repo/learning-assistant/releases/tag/v0.1.0
