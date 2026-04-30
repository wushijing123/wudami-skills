#!/bin/bash
# Live Teleprompter — 本地启动脚本
# 用法: bash serve.sh <teleprompter-directory>

DIR="${1:-.}"

if [ ! -f "$DIR/index.html" ]; then
  echo "❌ 未找到 index.html，请确认目录路径正确"
  exit 1
fi

PORT=8765

# Check if port is occupied
if lsof -i :$PORT > /dev/null 2>&1; then
  echo "⚠️  端口 $PORT 已被占用，尝试使用随机端口..."
  PORT=0
fi

echo "🖥️  Live Teleprompter 启动中..."
echo "📂 目录: $DIR"

cd "$DIR"

# Start server
python3 -m http.server $PORT &
SERVER_PID=$!

# Wait for server to be ready
sleep 1

# Get actual port if random
if [ "$PORT" = "0" ]; then
  PORT=$(lsof -p $SERVER_PID -i -P | grep LISTEN | awk '{print $9}' | cut -d: -f2 | head -1)
fi

echo "✅ 服务已启动: http://localhost:$PORT"
echo "   主控台: http://localhost:$PORT/index.html"
echo "   投屏窗口会从主控台打开"
echo ""
echo "按 Ctrl+C 停止服务器"

# Open in browser
open "http://localhost:$PORT/index.html"

# Wait for server process
trap "kill $SERVER_PID 2>/dev/null; echo ''; echo '🛑 服务已停止'" EXIT
wait $SERVER_PID
