# ESM3 Agent（自动蛋白设计实验室）

已升级为 **自动蛋白设计 Agent 系统**，包含 inference API 层。

## 项目结构

```text
esm3-agent
│
├─ agent
│   ├─ planner
│   ├─ evaluator
│   └─ optimizer
│
├─ esm3_runner
├─ protein_pipeline
├─ api_server
└─ web_ui
```

## 核心能力

- 自动设计 GFP 变体
- 自动筛选
- 自动评分
- 自动迭代优化

## 快速启动

```bash
./start.sh
```

> `start.sh` 会先 `go build -o esm3-agent .`，避免跑到旧二进制。

服务默认监听 `:8080`。

## API

### 运行模式（本地 mock / 上游大模型）

默认是本地 mock 设计流程，不会消耗任何外部大模型 token。

如果你希望真实调用 OpenAI 兼容网关（并在后台看到 token 消耗），请先设置：

```bash
export OPENAI_BASE_URL="https://<your-gateway>/v1"
export OPENAI_API_KEY="<your_api_key>"
export OPENAI_MODEL="gpt-5.3-codex"   # 可选，不填则沿用请求里的 model
```

然后重启服务并检查：

```bash
curl http://localhost:8080/v1/debug/provider
```

当 `mode=upstream` 且 `upstream_enabled=true` 时，`POST /v1/chat/completions` 会转发到上游并返回原始响应（含 usage 字段时可直接看到 token 计数）。

### 0) Web 交互界面（新增）

浏览器打开根路径即可进行多轮对话，不需要手写 curl：

```
http://localhost:8080/
```

页面会持续保留会话上下文，并展示最近一次最佳候选（ID、score、sequence）。

此外页面会自动请求 `POST /v1/inference/design` 获取完整候选 JSON，并提供“跳转查看”与“复制 JSON/序列”能力，避免长序列单行难读。

### 1) 健康检查

```bash
curl http://localhost:8080/health
```

### 2) Inference API（核心，返回完整结果）

```bash
curl -X POST http://localhost:8080/v1/inference/design \
  -H "Content-Type: application/json" \
  -d '{
    "target_protein": "GFP",
    "objective": "提高荧光代理分数",
    "num_candidates": 10,
    "rounds": 4,
    "required_motif": "GSG",
    "forbidden_aas": "C"
  }'
```

### 3) OpenAI 兼容 chat 接口（返回聊天格式）

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-protein-design-agent",
    "messages":[{"role":"user","content":"请自动设计 GFP 变体并迭代优化"}]
  }'
```

也支持浏览器快速调试（GET）：

```bash
http://localhost:8080/v1/chat/completions?q=请自动设计GFP并迭代
```

> 注意：GET 仅用于本地快速演示。真正触发上游大模型调用的是 `POST /v1/chat/completions`。

## 为什么你只看到 `choices`？

这是 OpenAI Chat Completions 标准格式，主文本就在：

- `choices[0].message.content`

如果你想要完整候选列表、每条序列分数、最佳候选等结构化结果，请调用：

- `POST /v1/inference/design`

## Windows 连到服务器后，为什么还是不对？

关键点：`localhost` 永远指“当前访问端”。

- 你在 **服务器终端** 执行 `curl http://localhost:8080/...`：访问的是服务器。
- 你在 **Windows 本地浏览器** 打开 `http://localhost:8080/...`：访问的是你自己的 Windows，不是服务器。

如果你想在 Windows 浏览器访问服务器上的 8080：

1. 用 SSH 端口转发（推荐）

```bash
ssh -L 8080:127.0.0.1:8080 <user>@<server_ip>
```

然后在 Windows 浏览器打开：`http://localhost:8080/health`

2. 或直接访问服务器 IP（需放通防火墙/安全组）

```bash
http://<server_ip>:8080/health
```

## 说明

当前 `esm3_runner` 为可替换执行层（默认提供 mock 变体生成逻辑），后续可以直接接入真实 ESM3 推理脚本或服务。
