#!/bin/bash
# 测试 Companion 对话小书童的模型选择功能

set -e

echo "=========================================="
echo "Companion 对话小书童 - 模型选择功能测试"
echo "=========================================="
echo ""

# 获取测试 token（假设用户已登录）
# 这里需要替换为实际的 token
TOKEN="${TEST_TOKEN:-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzUyMDAwMDAwfQ.dummy}"

# 测试基础URL
BASE_URL="http://127.0.0.1:6100"

echo "1️⃣  测试 XMX 模块（经济学）- 默认 DPO 模型"
echo "-------------------------------------------"
RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/companion/chat?subject=economics" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "通货膨胀的主要原因是什么？"
  }' 2>&1)

if echo "$RESPONSE" | grep -q "conversation_id"; then
    echo "✅ 成功：XMX 默认模型测试通过"
    echo "   使用模型：$(echo "$RESPONSE" | grep -o '"assistant_message":"[^"]*"' | head -c 100)..."
else
    echo "❌ 失败：$RESPONSE"
fi
echo ""

echo "2️⃣  测试 XMX 模块 - 显式指定 SFT 模型"
echo "-------------------------------------------"
RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/companion/chat?subject=economics&training_mode=sft" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "什么是供给和需求？"
  }' 2>&1)

if echo "$RESPONSE" | grep -q "conversation_id"; then
    echo "✅ 成功：XMX SFT 模型测试通过"
else
    echo "❌ 失败：$RESPONSE"
fi
echo ""

echo "3️⃣  测试 XMX 模块 - 显式指定 DPO 模型"
echo "-------------------------------------------"
RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/companion/chat?subject=economics&training_mode=dpo" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "宏观经济学和微观经济学的区别？"
  }' 2>&1)

if echo "$RESPONSE" | grep -q "conversation_id"; then
    echo "✅ 成功：XMX DPO 模型测试通过"
else
    echo "❌ 失败：$RESPONSE"
fi
echo ""

echo "4️⃣  测试流式接口 - WZY 模块（数学）"
echo "-------------------------------------------"
echo "测试 training_mode=sft..."
curl -s -N -X POST "${BASE_URL}/api/v1/companion/chat/stream?subject=math&training_mode=sft" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "什么是勾股定理？"
  }' 2>&1 | head -5

echo ""
echo "✅ 流式接口测试完成"
echo ""

echo "5️⃣  检查可用模型列表"
echo "-------------------------------------------"
echo "查询 vLLM 网关的可用模型："
curl -s http://192.168.0.211:8010/v1/models | python3 -m json.tool | grep '"id"' || echo "⚠️  无法连接到 vLLM 网关"
echo ""

echo "=========================================="
echo "测试完成！"
echo "=========================================="
echo ""
echo "💡 使用说明："
echo "   - 默认使用 DPO 模型（无需指定 training_mode）"
echo "   - 指定 training_mode=sft 使用 SFT 模型"
echo "   - 指定 training_mode=dpo 显式使用 DPO 模型"
echo ""
echo "📝 完整文档请查看："
echo "   COMPANION_MODEL_SELECTION.md"
