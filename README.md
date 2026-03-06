# ESM3 Agent

蛋白质AI助手，OpenAI API兼容

## 快速开始
```bash
# 启动
./start.sh

# 停止
./stop.sh

# 重启
./restart.sh

# 状态
./status.sh
```

## 测试
```bash
# 健康检查
curl http://localhost:8080/health

# 环境检查
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"esm3-agent-v1","messages":[{"role":"user","content":"检查环境"}]}'
```

## 日志
```bash
# 实时查看
tail -f logs/esm3-agent.log

# 查看最新
tail -100 logs/esm3-agent.log
```
