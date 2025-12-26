# 多模块架构 - 测试指南

本文档介绍如何使用阶段7创建的集成测试和性能测试脚本,验证多模块系统的正确性和性能。

## 📋 测试概览

### 测试类型

1. **集成测试** (`integration/test_multi_module_integration.py`)
   - 测试所有5个模块的启动和健康状态
   - 测试前端路由到正确的模块端口
   - 测试跨模块认证和数据隔离
   - 测试各模块的学科验证

2. **性能测试** (`performance/test_module_performance.py`)
   - API响应时间基准测试
   - 并发请求处理能力测试
   - 跨模块性能对比分析
   - 系统吞吐量测试

---

## 🚀 快速开始

### 前提条件

在运行测试之前,确保:

```bash
# 1. 启动所有模块的API
./deploy/scripts/start.sh api_all

# 2. 启动所有模块的Agent Worker (可选,性能测试不需要)
./deploy/scripts/start.sh agent_all

# 3. 确认Redis正在运行
redis-cli ping
# 应该输出: PONG

# 4. 检查所有模块状态
./deploy/scripts/start.sh status
```

### 运行集成测试

```bash
# 方式1: 使用pytest (推荐)
cd /Users/antonio/academic_work/learning_assistant
conda activate 312_edu
pytest backend/tests/integration/test_multi_module_integration.py -v

# 方式2: 直接运行
python backend/tests/integration/test_multi_module_integration.py
```

### 运行性能测试

```bash
# 方式1: 直接运行 (推荐,输出更友好)
python backend/tests/performance/test_module_performance.py

# 方式2: 使用pytest
pytest backend/tests/performance/test_module_performance.py -v -s
```

---

## 📊 集成测试详解

### 测试类1: TestModuleHealth

**测试目标**: 验证所有5个模块的健康状态

**测试用例**:
- `test_all_modules_health_check`: 检查所有模块的 `/health` 端点
- `test_api_docs_accessible`: 检查所有模块的 `/docs` API文档

**预期结果**:
```
✅ RPJ模块 (端口 6001) 健康检查通过
   支持学科: chinese, english, politics
✅ XMX模块 (端口 6002) 健康检查通过
   支持学科: economics
✅ WZY模块 (端口 6003) 健康检查通过
   支持学科: math, physics
✅ WZM模块 (端口 6004) 健康检查通过
   支持学科: chemistry
✅ TONY模块 (端口 6005) 健康检查通过
   支持学科: history, geography, other
```

**常见问题**:
- ❌ `ConnectError`: 模块未启动,运行 `./start.sh api_{module}`
- ❌ `status != healthy`: 检查日志 `tail -f logs/{module}_api.log`

---

### 测试类2: TestModuleRouting

**测试目标**: 验证各学科请求路由到正确的模块

**测试用例**:
- `test_subject_routing`: 测试10个学科的路由正确性

**路由映射**:
```
chinese   → RPJ  (6001)
english   → RPJ  (6001)
politics  → RPJ  (6001)
economics → XMX  (6002)
math      → WZY  (6003)
physics   → WZY  (6003)
chemistry → WZM  (6004)
history   → TONY (6005)
geography → TONY (6005)
other     → TONY (6005)
```

**预期结果**:
```
✅ 学科 'chinese' 正确路由到 RPJ模块 (端口 6001)
✅ 学科 'history' 正确路由到 TONY模块 (端口 6005)
...
```

---

### 测试类3: TestSubjectValidation

**测试目标**: 验证各模块拒绝不支持的学科

**测试逻辑**:
- 向RPJ模块提交math学科的题目 → 应该返回400错误
- 向TONY模块提交chemistry学科的题目 → 应该返回400错误

**预期结果**:
```
✅ rpj模块正确拒绝了错误的学科 math
✅ tony模块正确拒绝了错误的学科 chemistry
```

**注意**: 如果返回401 (未认证),说明认证层先拦截了,这也是可以接受的。

---

### 测试类4: TestCrossModuleIsolation

**测试目标**: 验证跨模块数据隔离

**测试逻辑**:
- 查询RPJ模块的chinese学科题目 → 只返回chinese学科的题目
- 查询TONY模块的history学科题目 → 只返回history学科的题目

**预期结果**:
```
✅ RPJ模块 学科 'chinese' 数据隔离正确 (共15道题)
✅ TONY模块 学科 'history' 数据隔离正确 (共8道题)
```

**注意**: 如果数据库为空,此测试会显示0道题,这是正常的。

---

### 测试类5: TestEndToEndWorkflow

**测试目标**: 端到端用户认证和跨模块访问

**测试逻辑**:
1. 在TONY模块注册新用户
2. 获取JWT token
3. 使用token访问其他4个模块的API
4. 验证token在所有模块都有效 (统一认证)

**预期结果**:
```
✅ 用户注册成功: test_user_1735234567
✅ Token可跨模块使用: RPJ模块
✅ Token可跨模块使用: XMX模块
✅ Token可跨模块使用: WZY模块
✅ Token可跨模块使用: WZM模块
✅ Token可跨模块使用: TONY模块
```

---

## ⚡ 性能测试详解

### 测试1: 健康检查端点性能

**测试内容**: 每个模块执行50次健康检查,统计响应时间

**性能基准**: < 50ms (平均值)

**输出示例**:
```
📊 tony - 健康检查
   请求次数: 50
   最小值:   12.34 ms
   最大值:   45.67 ms
   平均值:   23.45 ms
   中位数:   22.10 ms
   P95:      38.90 ms
   P99:      42.30 ms
   ✅ 满足性能基准 (< 50ms)
```

**不满足基准**: 如果平均值 > 50ms,检查:
- 网络延迟 (本地测试应该很低)
- 服务负载 (是否有其他任务在运行)
- 系统资源 (CPU/内存是否充足)

---

### 测试2: API端点性能

**测试内容**: 每个模块执行30次题目列表查询,统计响应时间

**性能基准**: < 200ms (平均值)

**输出示例**:
```
📊 rpj - 题目列表
   请求次数: 30
   最小值:   56.78 ms
   最大值:   189.23 ms
   平均值:   102.34 ms
   中位数:   98.45 ms
   P95:      156.78 ms
   P99:      178.90 ms
   ✅ 满足性能基准 (< 200ms)
```

**不满足基准**: 如果平均值 > 200ms,考虑:
- 添加数据库索引 (尤其是 `subject` 字段)
- 使用Redis缓存常用查询
- 优化SQL查询 (避免N+1问题)

---

### 测试3: 并发请求处理

**测试内容**: 向每个模块并发发送50个请求,测试吞吐量

**性能基准**: < 500ms (平均值)

**输出示例**:
```
📊 tony - 并发50
   总耗时: 1234.56 ms (50个请求)
   吞吐量: 40.53 req/s
   请求次数: 50
   平均值:   246.78 ms
   ✅ 满足性能基准 (< 500ms)
```

**吞吐量计算**: `50 / (总耗时/1000)` = req/s

**不满足基准**: 如果平均值 > 500ms,考虑:
- 增加Uvicorn Worker数量 (`--workers 4`)
- 使用数据库连接池
- 优化数据库查询

---

### 测试4: 跨模块性能对比

**测试内容**: 对比5个模块的健康检查性能,找出最快和最慢的模块

**输出示例**:
```
📊 模块响应时间对比 (健康检查, 平均值):
   1. rpj    18.45 ms █████████
   2. tony   19.23 ms █████████
   3. wzy    20.12 ms ██████████
   4. xmx    21.34 ms ██████████
   5. wzm    22.67 ms ███████████

   ⚡ 最快模块: rpj
   🐌 最慢模块: wzm
```

**分析建议**:
- 如果差异 < 5ms: 正常,可能是启动顺序或系统缓存导致
- 如果差异 > 20ms: 检查慢的模块是否有资源问题

---

### 测试5: 汇总报告

**输出示例**:
```
5. 性能测试汇总报告
============================================================

总测试数: 15
✅ 通过: 14
❌ 失败: 1

💡 性能优化建议:
   1. 如果健康检查 > 50ms, 检查网络延迟和服务启动状态
   2. 如果API端点 > 200ms, 考虑添加数据库索引和缓存
   3. 如果并发性能差, 考虑增加Worker数量或使用连接池
   4. 定期运行此测试以监控性能退化
```

---

## 🔧 故障排查

### 问题1: 无法连接到模块

**错误信息**:
```
❌ 无法连接到 RPJ模块 (端口 6001)
   请先启动模块: ./deploy/scripts/start.sh api_rpj
```

**解决方案**:
```bash
# 1. 检查模块是否启动
./deploy/scripts/start.sh status

# 2. 启动未启动的模块
./deploy/scripts/start.sh api_rpj

# 3. 检查端口是否被占用
lsof -i :6001
```

---

### 问题2: 认证错误 (401)

**说明**: 这是正常的! 测试脚本允许401状态码,因为很多端点需要认证。

**如果想测试完整功能**:
1. 修改测试脚本,添加用户注册和登录逻辑
2. 使用获取的token发送请求

---

### 问题3: 数据库为空

**现象**: 数据隔离测试显示0道题

**解决方案**:
```bash
# 1. 通过前端或API添加测试数据
# 2. 或运行数据库seed脚本 (如果有)
```

---

### 问题4: 性能测试失败

**常见原因**:
- 系统负载过高
- 网络延迟
- 数据库锁竞争

**解决方案**:
```bash
# 1. 关闭其他占用资源的程序
# 2. 重启所有模块
./deploy/scripts/start.sh stop_all
./deploy/scripts/start.sh all

# 3. 清理Redis缓存
redis-cli FLUSHALL

# 4. 重新运行测试
```

---

## 📈 持续集成

### 在CI/CD中运行测试

示例 GitHub Actions workflow:

```yaml
name: Multi-Module Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Start services
        run: |
          docker-compose up -d
          ./deploy/scripts/start.sh all

      - name: Run integration tests
        run: |
          pytest backend/tests/integration/ -v

      - name: Run performance tests
        run: |
          python backend/tests/performance/test_module_performance.py
```

---

## 🎯 最佳实践

1. **定期运行测试**: 每次代码变更后运行集成测试
2. **性能基线**: 记录初始性能数据,监控性能退化
3. **隔离测试**: 使用独立的测试数据库
4. **清理资源**: 测试后清理创建的测试数据
5. **并行测试**: 使用 `pytest -n auto` 并行运行测试

---

## 📚 参考资料

- 集成测试脚本: [backend/tests/integration/test_multi_module_integration.py](integration/test_multi_module_integration.py)
- 性能测试脚本: [backend/tests/performance/test_module_performance.py](performance/test_module_performance.py)
- 模块启动脚本: [deploy/scripts/start.sh](../../deploy/scripts/start.sh)
- 快速启动指南: [MODULE_SPLIT_QUICKSTART.md](../../MODULE_SPLIT_QUICKSTART.md)

---

生成时间: 2025-12-26
版本: 1.0.0
