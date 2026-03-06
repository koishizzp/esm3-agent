#!/bin/bash
cd "$(dirname "$0")"
if [ -f "esm3-agent.pid" ]; then
    PID=$(cat esm3-agent.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "服务运行中 (PID: $PID)"
        echo ""
        echo "最新日志:"
        tail -20 logs/esm3-agent.log
    else
        echo "服务未运行"
    fi
else
    echo "服务未运行"
fi
