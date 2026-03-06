#!/bin/bash
cd "$(dirname "$0")"
if [ ! -f "esm3-agent.pid" ]; then
    echo "PID文件不存在"
    exit 1
fi
PID=$(cat esm3-agent.pid)
if ps -p $PID > /dev/null 2>&1; then
    kill $PID
    rm esm3-agent.pid
    echo "服务已停止"
else
    echo "进程不存在"
    rm esm3-agent.pid
fi
