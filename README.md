# ESM3 Agent（自动蛋白设计实验室）

已升级为 **自动蛋白设计 Agent 系统**，包含完整 inference API 层。

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
go run .
```

服务默认监听 `:8080`。

## API

### 1) 健康检查

```bash
curl http://localhost:8080/health
```

### 2) Inference API（核心）

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

### 3) OpenAI 兼容 chat 接口

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-protein-design-agent",
    "messages":[{"role":"user","content":"请自动设计 GFP 变体并迭代优化"}]
  }'
```

## 说明

当前 `esm3_runner` 为可替换执行层（默认提供 mock 变体生成逻辑），后续可以直接接入真实 ESM3 推理脚本或服务。
