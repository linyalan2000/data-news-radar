#!/bin/bash
# DataHOT 一键停止

echo "🛑 停止 DataHOT..."
kill $(lsof -ti:3000) 2>/dev/null && echo "  ✅ 前端已停止" || echo "  ⚠️ 前端未运行"
kill $(lsof -ti:8000) 2>/dev/null && echo "  ✅ 后端已停止" || echo "  ⚠️ 后端未运行"
echo "完成"