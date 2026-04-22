#!/bin/bash
# 双击启动实时中文字幕翻译工具。
# 第一次用前:
#   1. cp .env.example .env  然后把 OPENAI_API_KEY 填进 .env
#   2. chmod +x launch.command
#   3. 双击即可启动

set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "错误: 找不到 .venv 虚拟环境。请先在终端里跑一次:"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -r realtime_translator/requirements.txt"
    read -p "按任意键关闭窗口..."
    exit 1
fi

source .venv/bin/activate

if [ ! -f ".env" ]; then
    echo "错误: 找不到 .env 文件。请先复制 .env.example 为 .env 并填入你的 OPENAI_API_KEY:"
    echo "  cp .env.example .env"
    echo "  然后用文本编辑器打开 .env 填入 API key"
    read -p "按任意键关闭窗口..."
    exit 1
fi

set -a
source .env
set +a

if [ -z "$OPENAI_API_KEY" ]; then
    echo "错误: .env 里没有设置 OPENAI_API_KEY"
    read -p "按任意键关闭窗口..."
    exit 1
fi

exec python -m realtime_translator.main
