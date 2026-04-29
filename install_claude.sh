#!/bin/bash

echo "🚀 开始配置 Claude Code Conda 环境..."

# 1. 创建 Conda 环境并安装 Node.js
echo -e "\n[1/3] 正在创建 Conda 环境 (claude-env) 并安装 Node.js..."
conda create -n claude-env nodejs=20 -c conda-forge -y

# 2. 激活环境 (为了在 bash 脚本中使 conda activate 生效，需要先 source)
echo -e "\n[2/3] 正在激活环境..."
CONDA_BASE=$(conda info --base)
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate claude-env

# 3. 安装 Claude Code
echo -e "\n[3/3] 正在使用 npm 全局安装 Claude Code..."
npm install -g @anthropic-ai/claude-code

# 4. 创建环境变量快捷启动脚本
echo -e "\n[4/4] 正在生成快捷启动脚本 (start_claude.sh)..."
cat << 'EOF' > start_claude.sh
#!/bin/bash
echo "加载环境变量..."
export ANTHROPIC_AUTH_TOKEN="sk-9U5s6Js2iIq4wAFBQDXFRmaUWoexQpgOiTWQRAHCHoTPVA7u" # 请替换为你的真实 Key
export ANTHROPIC_BASE_URL="http://35.220.164.252:3888"
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1

echo "启动 Claude Code..."
claude
EOF

chmod +x start_claude.sh

echo -e "\n✅ 安装完成！"
echo "👉 以后每次使用，只需两步："
echo "   1. conda activate claude-env"
echo "   2. ./start_claude.sh"