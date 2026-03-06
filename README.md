# ESM3 Agent

蛋白质AI助手，OpenAI API兼容

## 上游LLM（真实 Function Calling）

Agent 现在支持调用 OpenAI 兼容接口进行真实工具选择（function calling）。

可配置环境变量：

```bash
export UPSTREAM_API="https://api.openai.com/v1/chat/completions"
export UPSTREAM_KEY="<your_api_key>"
export UPSTREAM_MODEL="gpt-4o-mini"
```

如果 `UPSTREAM_KEY` 为空，会自动回退到本地关键词匹配逻辑。

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
