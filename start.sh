#!/bin/bash
# DataHOT 一键启动脚本
# 用法: ./start.sh

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$DIR/backend"
DASHBOARD_DIR="$DIR/dashboard"

echo "🚀 启动 DataHOT..."

# 微信公众号抓取使用 mp.weixin.qq.com 官方 API，不再需要 RSSHub

# 启动后端
cd "$BACKEND_DIR"
source .venv/bin/activate
nohup uvicorn app.main:app --port 8000 > /tmp/datahot-backend.log 2>&1 &
BACKEND_PID=$!
echo "  ✅ 后端已启动 (PID: $BACKEND_PID) → http://localhost:8000"

# 启动前端
cd "$DASHBOARD_DIR"
nohup npm run dev > /tmp/datahot-dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo "  ✅ 前端已启动 (PID: $DASHBOARD_PID) → http://localhost:3000"

echo ""
echo "📡 打开浏览器访问: http://localhost:3000"
echo "📋 查看后端日志: tail -f /tmp/datahot-backend.log"
echo "📋 查看前端日志: tail -f /tmp/datahot-dashboard.log"