# Companion 对话小书童 - 模型选择功能说明

## 功能概述

用户可以在对话小书童功能中选择使用 **SFT（监督微调）** 或 **DPO（直接偏好优化）** 模型进行对话。

## API 使用方式

### 1. 流式对话 (推荐)

```bash
# 使用 DPO 模型（默认）
curl -X POST "http://115.190.90.101:8600/api/v1/companion/chat/stream?subject=economics" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你最擅长什么？",
    "mode": "chat"
  }'

# 使用 SFT 模型
curl -X POST "http://115.190.90.101:8600/api/v1/companion/chat/stream?subject=economics&training_mode=sft" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你最擅长什么？",
    "mode": "chat"
  }'

# 使用 DPO 模型（显式指定）
curl -X POST "http://115.190.90.101:8600/api/v1/companion/chat/stream?subject=economics&training_mode=dpo" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你最擅长什么？",
    "mode": "chat"
  }'
```

### 2. 非流式对话

```bash
curl -X POST "http://115.190.90.101:8600/api/v1/companion/chat?subject=economics&training_mode=sft" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "通货膨胀对普通家庭有什么影响？",
    "mode": "chat"
  }'
```

## 模型选择逻辑

优先级（从高到低）：

1. **training_mode 参数**：如果指定了 `training_mode=sft` 或 `training_mode=dpo`
   - 使用 `<module>-<training_mode>` 模型
   - 例如：`xmx-sft`, `xmx-dpo`, `wzy-sft`, `wzm-dpo`

2. **学科专属模型**：如果指定了 `subject` 且存在学科专属 LoRA
   - 使用 `<module>-sft-<subject>` 模型
   - 例如：`tony-sft-history`, `wzy-sft-math`
   - **注意**：当前统一网关未提供按学科细分的 LoRA

3. **默认模型**：使用环境变量配置的模块默认模型
   - 见 `.env` 中的 `PERSONAL_MODEL_MODEL_<MODULE>` 配置

## 可用模型列表

当前 vLLM 网关（`192.168.0.211:8010`）提供以下 11 个模型：

### 基座模型
- `tony-qwen3-14b` - Qwen 3 14B 基座模型

### 各模块 SFT 模型
- `rpj-sft` - 语文、英语、政治（监督微调）
- `xmx-sft` - 经济学（监督微调）
- `wzy-sft` - 数学、物理（监督微调）
- `wzm-sft` - 化学（监督微调）
- `tony-sft` - 历史、地理、其他（监督微调）

### 各模块 DPO 模型（默认）
- `rpj-dpo` - 语文、英语、政治（DPO 优化）
- `xmx-dpo` - 经济学（DPO 优化）
- `wzy-dpo` - 数学、物理（DPO 优化）
- `wzm-dpo` - 化学（DPO 优化）
- `tony-dpo` - 历史、地理、其他（DPO 优化）

## 学科到模块的映射

| 学科 (subject) | 模块 (module) | 端口 | SFT 模型 | DPO 模型 |
|---------------|--------------|------|----------|----------|
| chinese       | rpj          | 6001 | rpj-sft  | rpj-dpo  |
| english       | rpj          | 6001 | rpj-sft  | rpj-dpo  |
| politics      | rpj          | 6001 | rpj-sft  | rpj-dpo  |
| economics     | xmx          | 6002 | xmx-sft  | xmx-dpo  |
| math          | wzy          | 6003 | wzy-sft  | wzy-dpo  |
| physics       | wzy          | 6003 | wzy-sft  | wzy-dpo  |
| chemistry     | wzm          | 6004 | wzm-sft  | wzm-dpo  |
| history       | tony         | 6005 | tony-sft | tony-dpo |
| geography     | tony         | 6005 | tony-sft | tony-dpo |
| other         | tony         | 6005 | tony-sft | tony-dpo |

## 环境变量配置

当前 `.env` 配置：

```bash
# 统一对话网关（OpenAI 兼容，Nginx 反代 vLLM）
PERSONAL_MODEL_ENABLED_RPJ=true
PERSONAL_MODEL_API_BASE_RPJ=http://192.168.0.211:8010/v1
PERSONAL_MODEL_MODEL_RPJ=rpj-dpo

PERSONAL_MODEL_ENABLED_XMX=true
PERSONAL_MODEL_API_BASE_XMX=http://192.168.0.211:8010/v1
PERSONAL_MODEL_MODEL_XMX=xmx-dpo

PERSONAL_MODEL_ENABLED_WZY=true
PERSONAL_MODEL_API_BASE_WZY=http://192.168.0.211:8010/v1
PERSONAL_MODEL_MODEL_WZY=wzy-dpo

PERSONAL_MODEL_ENABLED_WZM=true
PERSONAL_MODEL_API_BASE_WZM=http://192.168.0.211:8010/v1
PERSONAL_MODEL_MODEL_WZM=wzm-dpo

PERSONAL_MODEL_ENABLED_TONY=true
PERSONAL_MODEL_API_BASE_TONY=http://192.168.0.211:8010/v1
PERSONAL_MODEL_MODEL_TONY=tony-dpo

# 关键开关：允许在无学科专属 LoRA 时回退到默认模型
COMPANION_REQUIRE_SUBJECT_MODEL=false
```

## 前端集成示例

### JavaScript/TypeScript

```typescript
// 使用 DPO 模型（默认）
const response = await fetch('/api/v1/companion/chat/stream?subject=economics', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    message: '你最擅长什么？',
    mode: 'chat',
  }),
});

// 使用 SFT 模型
const response = await fetch('/api/v1/companion/chat/stream?subject=economics&training_mode=sft', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    message: '你最擅长什么？',
    mode: 'chat',
  }),
});
```

### React 示例

```jsx
function CompanionChat() {
  const [trainingMode, setTrainingMode] = useState('dpo'); // 'sft' or 'dpo'
  
  const sendMessage = async (message) => {
    const params = new URLSearchParams({
      subject: 'economics',
      training_mode: trainingMode,
    });
    
    const response = await fetch(`/api/v1/companion/chat/stream?${params}`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message,
        mode: 'chat',
      }),
    });
    
    // 处理 SSE 流式响应...
  };
  
  return (
    <div>
      <select value={trainingMode} onChange={(e) => setTrainingMode(e.target.value)}>
        <option value="dpo">DPO 模型（推荐）</option>
        <option value="sft">SFT 模型</option>
      </select>
      {/* 聊天界面 */}
    </div>
  );
}
```

## 验证模型可用性

检查所有可用模型：

```bash
curl http://192.168.0.211:8010/v1/models
```

返回示例：
```json
{
  "object": "list",
  "data": [
    {"id": "tony-qwen3-14b", "object": "model"},
    {"id": "rpj-sft", "object": "model"},
    {"id": "rpj-dpo", "object": "model"},
    {"id": "xmx-sft", "object": "model"},
    {"id": "xmx-dpo", "object": "model"},
    ...
  ]
}
```

## 故障排查

### 1. 404 Not Found

**问题**：访问 `/api/v1/companion/chat/stream` 返回 404

**原因**：companion 路由未注册到模块的 router

**解决**：已修复，确保所有模块的 `api/router.py` 包含：
```python
from .endpoints.companion import chat as companion_chat
api_router.include_router(companion_chat.router, prefix="/companion", tags=["Companion"])
```

### 2. 503 Service Unavailable

**问题**：Personal model is disabled (or unreachable)

**原因**：
- vLLM 服务未启动
- 网络不通（检查 `192.168.0.211:8010` 是否可达）
- 环境变量 `PERSONAL_MODEL_ENABLED_<MODULE>=false`

**解决**：
1. 检查 vLLM 服务：`curl http://192.168.0.211:8010/v1/models`
2. 确认 `.env` 中对应模块的 `PERSONAL_MODEL_ENABLED_<MODULE>=true`
3. 重启对应模块的 API

### 3. 模型选择未生效

**问题**：指定了 `training_mode=sft` 但实际使用的是 dpo 模型

**原因**：
- 请求的模型在 vLLM 中未加载
- 模型名称拼写错误

**解决**：
1. 检查模型列表：`curl http://192.168.0.211:8010/v1/models`
2. 查看后端日志：`tail -f logs/xmx_api.log | grep "chat request"`
3. 确认日志中的 `model=` 字段

## 修改记录

### 2026-07-08
- ✅ 修复 xmx/wzy/wzm 模块 companion 路由未注册问题
- ✅ 添加 `training_mode` 参数支持 sft/dpo 模型选择
- ✅ 更新所有模块（rpj, xmx, wzy, wzm, tony）的 companion 端点
- ✅ 更新 default 模块代理网关，转发 training_mode 参数
- ✅ 修改 PersonalModelService.resolve_model_for_subject 支持 training_mode
- ✅ 禁用热重载（RELOAD=false）避免日志刷屏

## 相关文件

- `backend/core/services/personal_model_service.py` - 模型服务核心逻辑
- `backend/modules/*/api/endpoints/companion/chat.py` - 各模块对话端点
- `backend/modules/*/api/router.py` - 路由注册
- `backend/modules/default/api/endpoints/companion.py` - 代理网关
- `.env` - 环境变量配置
