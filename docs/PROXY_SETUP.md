# API 反向代理配置说明

## 概述

为了满足生产环境只对外暴露 8000 端口的需求，我们配置了 Vite 反向代理，将所有前端 API 请求从 8000 端口转发到后端各个模块的实际端口。

## 架构变更

### 修改前
```
用户浏览器 ──┬─> http://localhost:8000 (前端)
             ├─> http://localhost:6001 (RPJ模块)
             ├─> http://localhost:6002 (XMX模块)
             ├─> http://localhost:6003 (WZY模块)
             ├─> http://localhost:6004 (WZM模块)
             └─> http://localhost:6005 (TONY模块)
```

### 修改后
```
用户浏览器 ──> http://localhost:8000 (前端 + 反向代理)
                       │
                       ├─ /api/rpj/*   ──> http://localhost:6001/api/*
                       ├─ /api/xmx/*   ──> http://localhost:6002/api/*
                       ├─ /api/wzy/*   ──> http://localhost:6003/api/*
                       ├─ /api/wzm/*   ──> http://localhost:6004/api/*
                       ├─ /api/tony/*  ──> http://localhost:6005/api/*
                       ├─ /health/rpj  ──> http://localhost:6001/health
                       ├─ /health/xmx  ──> http://localhost:6002/health
                       └─ ...
```

## 修改的文件

### 1. `frontend/vite.config.js`

添加了 Vite proxy 配置，将请求转发到对应的后端端口：

```javascript
server: {
  host: '0.0.0.0',
  port: 8000,
  proxy: {
    // API 端点转发
    '/api/rpj': {
      target: 'http://localhost:6001',
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api\/rpj/, '/api'),
    },
    // ... 其他模块配置

    // 健康检查端点转发
    '/health/rpj': {
      target: 'http://localhost:6001',
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/health\/rpj/, '/health'),
    },
    // ... 其他模块配置
  },
}
```

### 2. `frontend/src/config/moduleRouting.js`

修改 `getApiBaseUrl()` 函数返回相对路径：

```javascript
// 修改前
export function getApiBaseUrl(subject) {
  const module = getModuleBySubject(subject)
  const port = MODULE_PORTS[module]
  return `http://localhost:${port}`
}

// 修改后
export function getApiBaseUrl(subject) {
  const module = getModuleBySubject(subject)
  return `/api/${module}`  // 返回相对路径
}
```

修改 `getHealthCheckUrl()` 函数：

```javascript
// 修改前
export function getHealthCheckUrl(module) {
  const port = MODULE_PORTS[module]
  return `http://localhost:${port}/health`
}

// 修改后
export function getHealthCheckUrl(module) {
  return `/health/${module}`  // 返回相对路径
}
```

## 路由规则

### API 端点路由

| 前端请求路径 | 后端实际路径 | 模块 | 学科 |
|------------|------------|------|------|
| `/api/rpj/v1/*` | `http://localhost:6001/api/v1/*` | RPJ | 语文、英语、政治 |
| `/api/xmx/v1/*` | `http://localhost:6002/api/v1/*` | XMX | 经济学 |
| `/api/wzy/v1/*` | `http://localhost:6003/api/v1/*` | WZY | 数学、物理 |
| `/api/wzm/v1/*` | `http://localhost:6004/api/v1/*` | WZM | 化学 |
| `/api/tony/v1/*` | `http://localhost:6005/api/v1/*` | TONY | 历史、地理、其他 |
| `/api/default/v1/*` | `http://localhost:6100/api/v1/*` | DEFAULT | 跨学科查询 |

### 健康检查路由

| 前端请求路径 | 后端实际路径 |
|------------|------------|
| `/health/rpj` | `http://localhost:6001/health` |
| `/health/xmx` | `http://localhost:6002/health` |
| `/health/wzy` | `http://localhost:6003/health` |
| `/health/wzm` | `http://localhost:6004/health` |
| `/health/tony` | `http://localhost:6005/health` |

## 测试验证

### 1. 健康检查测试

```bash
# 测试所有模块的健康检查
curl http://localhost:8000/health/rpj
curl http://localhost:8000/health/xmx
curl http://localhost:8000/health/wzy
curl http://localhost:8000/health/wzm
curl http://localhost:8000/health/tony

# 预期响应
{
  "status": "healthy",
  "module": "rpj",
  "subjects": ["chinese", "english", "politics"],
  "app": "AI Learning Assistant",
  "version": "0.1.0",
  "port": 6001
}
```

### 2. API 端点测试

```bash
# 测试用户认证端点
curl -X POST http://localhost:8000/api/rpj/v1/users/token \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test"}'

# 测试错题列表端点（需要认证）
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/tony/v1/questions/?subject=history"
```

## 生产部署注意事项

### 1. 防火墙配置

只需要开放 8000 端口，内部端口（6001-6005, 6100）不需要对外开放：

```bash
# 只允许外部访问 8000 端口
sudo ufw allow 8000/tcp

# 确保内部端口不对外开放（默认情况）
sudo ufw status
```

### 2. Nginx 反向代理（可选）

如果使用 Nginx 作为前端服务器，可以使用类似的配置：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API 转发（如果需要直接在 Nginx 层面处理）
    location /api/rpj/ {
        proxy_pass http://localhost:6001/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # ... 其他模块配置
}
```

### 3. Docker Compose 配置

在 Docker 环境中，只需要暴露前端容器的 8000 端口：

```yaml
services:
  frontend:
    ports:
      - "8000:8000"  # 只暴露前端端口
    depends_on:
      - api_rpj
      - api_xmx
      - api_wzy
      - api_wzm
      - api_tony

  api_rpj:
    # 不暴露端口，只在内部网络访问
    networks:
      - internal

  # ... 其他后端服务
```

## 开发模式

在开发模式下，Vite 的 proxy 功能会自动处理所有转发。只需要：

```bash
# 启动所有后端服务
./deploy/scripts/start.sh all

# 前端会自动通过 Vite proxy 转发请求
# 访问 http://localhost:8000 即可
```

## 故障排查

### 问题1：请求返回 504 Gateway Timeout

**原因**：后端模块未启动或端口不正确

**解决**：
```bash
# 检查所有模块状态
./deploy/scripts/start.sh status

# 启动未运行的模块
./deploy/scripts/start.sh api_all
```

### 问题2：CORS 错误

**原因**：proxy 配置中 `changeOrigin: true` 丢失

**解决**：确保 `vite.config.js` 中所有 proxy 配置都包含 `changeOrigin: true`

### 问题3：路径重写错误

**原因**：rewrite 规则不正确

**解决**：检查 Vite proxy 的 rewrite 配置是否正确替换路径前缀

## 兼容性说明

- ✅ 开发模式：完全兼容，Vite dev server 自动处理
- ✅ 生产模式：需要确保前端构建后的静态文件通过支持 proxy 的服务器（如 Nginx）提供
- ✅ Docker 部署：完全兼容，只需暴露 8000 端口
- ✅ 后端代码：无需修改，完全向后兼容

## 总结

通过这次配置，我们实现了：

1. ✅ 只对外暴露 8000 端口
2. ✅ 前端自动将请求路由到正确的后端模块
3. ✅ 保持后端代码不变
4. ✅ 支持所有 5 个模块和 10 个学科
5. ✅ 健康检查和 API 端点都正常工作

用户现在只需要访问 `http://localhost:8000` 或 `http://your-domain.com:8000`，所有 API 请求会自动转发到正确的后端服务。
