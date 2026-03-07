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

### 0) Web 交互界面（新增）

浏览器打开根路径即可进行多轮对话，不需要手写 curl：

```
http://localhost:8080/
```

页面会持续保留会话上下文，并展示最近一次最佳候选（ID、score、sequence）。

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
