#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  SmartCrawler 启动中..."
echo "============================================"

# ---- 优先使用项目自带虚拟环境 ----
PY="python3"
if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
    echo "[信息] 使用虚拟环境 .venv"
elif ! command -v python3 >/dev/null 2>&1; then
    echo "[错误] 未找到 python3"
    exit 1
fi

if ! "$PY" -c "import PySide6" >/dev/null 2>&1; then
    echo "[提示] 未检测到 PySide6，正在安装..."
    "$PY" -m pip install -r requirements.txt
fi

# Linux 上 QtWebEngine 需要禁用沙箱（在非 root 环境可选）
if [[ "$(uname)" == "Linux" ]]; then
    export QTWEBENGINE_DISABLE_SANDBOX=1
fi

"$PY" main.py
