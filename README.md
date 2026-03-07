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

### 运行模式（真实 ESM3 / 上游大模型）

默认只允许真实 ESM3 推理，不再允许自动回退 mock。

优先使用 `esm3.endpoint`（HTTP 服务）；若为空，则使用本地 `python_path + script_dir` 调用你部署的 ESM3 环境。若两者都不可用，接口会直接报错。

先配置真实 ESM3（与你当前服务器部署一致）：

```yaml
esm3:
  endpoint: ""   # 如果你已有 HTTP 服务就填；否则留空
  api_key: ""
  model: "esm3-open"
  timeout: 300
  python_path: "/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python"
  script_dir: "/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction"
  entrypoint: ""  # 可选，明确指定 esm_wrapper 入口函数名
```

或使用环境变量：

```bash
export ESM3_ENDPOINT="http://127.0.0.1:8000/v1/esm3/generate"   # 可选
export ESM3_API_KEY="<optional>"
export ESM3_MODEL="esm3-open"
export ESM3_PYTHON_PATH="/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python"
export ESM3_SCRIPT_DIR="/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction"
export ESM3_ENTRYPOINT="generate_variants"   # 可选
```



如果出现 `utils.esm_wrapper.generate_variants not found`：

- 现在桥接器会自动尝试 `generate_variants / generate_sequences / generate / run_generation / design`，以及常见包装类的同名方法。
- 你也可以在 `esm3.entrypoint`（或 `ESM3_ENTRYPOINT`）里显式指定入口名，避免自动探测歧义。
- 失败时 `POST /v1/inference/design` 返回的错误文本会附带 `attempts=` 与 `available_symbols=`，可直接据此定位入口函数名。
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

当前 `esm3_runner` 为严格真实推理执行层：必须接通 HTTP ESM3 或本地 Python ESM3；失败会直接返回错误，避免误用 mock 结果。


## 评分与优化策略（科学严谨性说明）

当前评分函数采用可解释的加权模型（每条候选会返回 metrics 明细）：

- 正向项：
  - `stability_component`：疏水比例接近 0.35 时更高。
  - `fluor_component`：G/S 比例提升会增加荧光代理得分。
- 负向项：
  - `charge_penalty`：过高带电氨基酸比例触发惩罚。
  - `length_penalty`：超出 `min_length/max_length` 时惩罚。
  - `motif_penalty`：不满足 `required_motif` 时惩罚。
  - `forbidden_penalty`：包含 `forbidden_aas` 时惩罚。

总分公式：

```
score = +0.45*stability +0.75*fluor -0.55*charge -0.30*length -0.35*motif -0.40*forbidden
```

优化策略为“多轮迭代 + best seed 回灌”：每轮基于当前最优序列再生成新候选，持续提高目标分数并保持约束。
