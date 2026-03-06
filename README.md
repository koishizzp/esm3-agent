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


## 详细使用说明（从 0 到 1）

### 1) 配置环境变量

```bash
export UPSTREAM_API="https://api.openai.com/v1/chat/completions"
export UPSTREAM_KEY="sk-xxxx"
export UPSTREAM_MODEL="gpt-4o-mini"

# ESM3 本地执行环境
export PYTHON_PATH="/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python"
export SCRIPT_DIR="/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction"
```

> 不设置 `UPSTREAM_KEY` 时，服务会自动回退为本地规则匹配。

### 2) 启动服务

```bash
./start.sh
./status.sh
```

正常时应能看到 `8080` 端口监听，且健康检查返回 `OK`。

### 3) 基础连通性检查

```bash
curl http://localhost:8080/health
```

### 4) 通过 OpenAI 兼容接口调用 Agent

#### 4.1 环境检查
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-agent-v1",
    "messages":[{"role":"user","content":"请检查esm3运行环境"}]
  }'
```

#### 4.2 序列分析（会调用 `analyze_sequence`）
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-agent-v1",
    "messages":[{"role":"user","content":"帮我分析这个蛋白序列 MKTVRQERLKDLLEK"}]
  }'
```

#### 4.3 蛋白生成（会调用 `generate_protein`）
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-agent-v1",
    "messages":[{"role":"user","content":"请帮我生成一个GFP蛋白"}]
  }'
```

### 5) 查看日志和排错

```bash
# 服务日志
tail -f logs/esm3-agent.log

# 使用日志（包含 tool 决策和耗时）
tail -f logs/usage.log
```

常见问题：
- `tool_args parse failed`：通常是上游模型返回了非 JSON 参数，可换更稳定模型或收紧 prompt。
- `工具执行错误`：一般是本地 Python/ESM3 环境或路径配置问题。
- 生成很慢：`generate_protein` 本身耗时长（2-5 分钟）属正常。

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
