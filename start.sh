#!/bin/bash
cd "$(dirname "$0")"
echo "启动 ESM3 Agent..."
if [ -f "esm3-agent.pid" ]; then
    PID=$(cat esm3-agent.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "服务已在运行 (PID: $PID)"
        exit 1
    fi
fi
nohup ./esm3-agent > logs/esm3-agent.log 2>&1 &
echo $! > esm3-agent.pid
echo "服务已启动 PID: $(cat esm3-agent.pid)"
echo "查看日志: tail -f logs/esm3-agent.log"
