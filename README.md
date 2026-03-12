# 基于 ESM3 的自治蛋白设计 Agent（中文详细版）

本仓库新增了一套 **Python 模块化自治蛋白设计系统**，目标是让用户通过自然语言任务（如：`Design an improved GFP and iteratively optimize it.`）触发自动化实验循环：

> 用户任务 → LLM 规划 → 工具执行 → ESM3 推理（生成/突变/结构）→ 候选评分 → 迭代优化 → 记忆沉淀

该系统强调：

- **本地真实 ESM3 模型服务**（非 mock）
- **可扩展工具化架构**
- **可追踪实验记忆**
- **可通过 REST API 直接集成**

## 文档入口

当前建议优先阅读下面这些文档：

- `README.md`
  - 安装、运行、API、真实 ESM3 接入总览
- `GFP_SURROGATE_UPGRADE_PLAN.md`
  - GFP surrogate / active learning 的架构路线图
- `GFP_HARD_CONSTRAINTS_USAGE.md`
  - GFP 硬约束和 `fixed_residues` 用法
- `PHASE2_GFP_SURROGATE_GUIDE.md`
  - GFP Phase 2 的稳定操作指南
- `PHASE3_ACTIVE_LEARNING_GUIDE.md`
  - GFP Phase 3 / active learning 的稳定操作指南
- `ESM3_DEMO_GUIDE.md`
  - 统一后的演示手册

历史性的 rerun、recovery、closeout、tutorial、demo 快照文档已经合并进以上主文档，不再建议继续维护。

---

## 1. 仓库结构（已实现）

```text
protein_agent/
  agent/
    planner.py             # LLM 规划器：自然语言 -> 结构化计划
    executor.py            # 工具执行层：统一调用生成/突变/结构/评分
    workflow.py            # 迭代实验引擎：generate -> evaluate -> select -> mutate -> repeat

  tools/
    base.py                # Tool 抽象接口（name/description/input_schema/execute）
    esm3_generate.py       # 调用 ESM3 Server 的序列生成接口
    esm3_mutate.py         # 调用 ESM3 Server 的突变接口
    esm3_structure.py      # 调用 ESM3 Server 的结构预测接口
    protein_score.py       # 蛋白评分模块（序列 + 结构置信度）

  esm3_server/
    server.py              # 本地 ESM3 FastAPI 服务（模型单次加载）

  memory/
    experiment_memory.py   # 实验记忆：记录每轮候选与最优结果

  workflows/
    gfp_optimizer.py       # GFP 内置工作流（含 scaffold）

  api/
    main.py                # Agent API：POST /design_protein

  config/
    settings.py            # 统一配置（环境变量 + 默认值）

  scripts/
    run_design_example.py  # 示例请求脚本

requirements.txt
README.md
```

---

## 2. 核心模块详解

### 2.1 LLM Planner（`agent/planner.py`）

职责：把自然语言任务转成结构化 JSON 计划，包含：

- workflow 名称
- target
- max_iterations
- patience
- candidates_per_round
- steps 列表

实现细节：

1. 如果配置了 OpenAI 兼容参数（`PROTEIN_AGENT_OPENAI_API_KEY`），会调用 LLM 生成 JSON 计划。
2. 若未配置或 LLM 输出不可解析，会回退到**确定性计划模板**，保证系统可运行。

> 这样设计的好处是：在线上你可以接入任意兼容网关做更强规划；离线环境仍可稳定执行迭代实验。

### 2.2 Tool Execution Layer（`agent/executor.py` + `tools/*`）

职责：把工作流动作映射为工具调用，统一外部依赖入口。

- `generate(prompt, n)` → `esm3_generate`
- `mutate(sequence, ...)` → `esm3_mutate`
- `evaluate(sequence)` → `esm3_structure + protein_score`

工具统一遵循：

```python
class Tool:
    name
    description
    input_schema
    execute(input_data)
```

这使得后续可非常容易追加新工具（如溶解度预测、二聚体打分、表达可行性约束等）。

### 2.3 ESM3 Model Server（`esm3_server/server.py`）

职责：封装本地 ESM3 推理能力，并通过 FastAPI 提供服务。

启动时：

- 自动检测 GPU（`torch.cuda.is_available()`）
- 执行 `from esm.models.esm3 import ESM3`
- `from_pretrained(...)` 单次加载模型并置为 eval

接口：

- `POST /generate_sequence`
- `POST /mutate_sequence`
- `POST /predict_structure`

> 该层与 Agent 层解耦：你可以单独扩展推理服务（多 GPU、队列、批处理）而不改上层编排逻辑。

### 2.4 Experiment Loop Engine（`agent/workflow.py`）

默认循环逻辑：

1. 初始生成候选（generate）
2. 逐条评估（predict_structure + score）
3. 选出 top 变体
4. 对 top 做突变扩增（mutate）
5. 进入下一轮

停止条件：

- 达到 `max_iterations`（上限 100）
- 连续 `patience` 轮无提升

> 这与“自动化定向进化”的实验过程对应：探索（generate）+开发（top 变体突变）并行推进。

### 2.5 Protein Evaluation Module（`tools/protein_score.py`）

评分输入：

- 序列本身（氨基酸构成）
- 结构预测置信度（来自结构工具）

评分输出：

- `score`
- `metrics`（疏水比例、带电比例、荧光提示残基比例、长度等）

当前实现为可解释的启发式组合分数，便于调参与审计；后续可替换为实验数据拟合模型。

### 2.6 Experiment Memory（`memory/experiment_memory.py`）

每个记录包含：

- `sequence`
- `mutation_history`
- `score`
- `iteration`
- `structure_data`
- `metadata`

支持：

- 全记录导出
- top-k 查询
- best 结果查询

API 返回中包含完整 `history` 与 `best_sequences`，便于复盘。

### 2.7 GFP Workflow（`workflows/gfp_optimizer.py`）

内置 GFP scaffold，并提供固定步骤计划：

1. 识别 GFP scaffold
2. 生成突变候选
3. 结构预测
4. 候选评分
5. 选择最优
6. 继续迭代（可到 100 轮）

当任务文本包含 `gfp` 时，API 会自动走该工作流。

---

## 3. 安装与运行（本地）

## 3.1 Python 环境

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> 依赖里已声明：`fastapi`、`requests`、`pydantic`、`openai`、`torch`、`esm`、`transformers` 等。

## 3.2 启动 ESM3 模型服务

```bash
export ESM3_MODEL_NAME=esm3-open
uvicorn protein_agent.esm3_server.server:app --host 0.0.0.0 --port 8001
```

如果你部署的是其他本地权重名，可替换 `ESM3_MODEL_NAME`。

## 3.3 启动 Agent API

```bash
export PROTEIN_AGENT_ESM3_SERVER_URL=http://127.0.0.1:8001

# 可选：启用 LLM 规划器
export PROTEIN_AGENT_OPENAI_API_KEY=<your_key>
export PROTEIN_AGENT_OPENAI_BASE_URL=<兼容端点，可不填>
export PROTEIN_AGENT_LLM_MODEL=gpt-4o-mini

uvicorn protein_agent.api.main:app --host 0.0.0.0 --port 8000
```

---

## 4. API 使用方式

### 4.1 健康检查

```bash
curl http://127.0.0.1:8000/health
```

### 4.2 发起蛋白设计任务

### Health
```bash
curl -X POST http://127.0.0.1:8000/design_protein \
  -H "Content-Type: application/json" \
  -d '{
    "task": "design a brighter GFP variant",
    "max_iterations": 20,
    "candidates_per_round": 8,
    "patience": 6
  }'
```

返回字段说明：

- `task`: 原始任务
- `plan`: 规划器输出计划
- `history`: 全实验轨迹（每条序列的评分与结构信息）
- `best_sequences`: 当前最优变体摘要

---

## 5. 示例脚本

```bash
python protein_agent/scripts/run_design_example.py
```

该脚本会向 `http://127.0.0.1:8000/design_protein` 提交示例任务并打印返回 JSON。

---

## 6. 关键配置（环境变量）

以 `PROTEIN_AGENT_` 为前缀，常用项：

- `PROTEIN_AGENT_ESM3_SERVER_URL`：ESM3 服务地址（默认 `http://127.0.0.1:8001`）
- `PROTEIN_AGENT_REQUEST_TIMEOUT`：工具请求超时
- `PROTEIN_AGENT_MAX_ITERATIONS`：默认最大迭代（上限 100）
- `PROTEIN_AGENT_DEFAULT_CANDIDATES`：每轮候选数
- `PROTEIN_AGENT_DEFAULT_PATIENCE`：无提升容忍轮数
- `PROTEIN_AGENT_OPENAI_API_KEY`：LLM 规划器密钥
- `PROTEIN_AGENT_OPENAI_BASE_URL`：兼容 LLM 网关地址
- `PROTEIN_AGENT_LLM_MODEL`：规划模型名

---

## 7. 工程说明与扩展建议

### 7.1 关于“真实实现”

本实现没有在主流程里使用 mock 分支：

- 生成/突变/结构接口都走 ESM3 服务
- 评分走真实计算逻辑
- 迭代引擎基于评分结果做真实选择与再突变

### 7.2 推荐下一步（可按你实验目标继续增强）

1. **结构生物学特征增强**：加入二级结构比例、接触图一致性、核心位点约束。
2. **多目标优化**：亮度、稳定性、表达可行性联合 Pareto 排序。
3. **实验闭环**：将湿实验结果回写 memory，做主动学习。
4. **并行化执行**：引入 Redis/Celery/Ray 将结构预测和评分并发化。
5. **持久化记忆**：从内存结构升级到 SQLite/PostgreSQL。

---

## 8. 常见问题排查（FAQ）

### Q1: 启动时报 `No module named fastapi` / `No module named esm`

说明当前 Python 环境未安装依赖，请在激活虚拟环境后执行：

```bash
pip install -r requirements.txt
```

### Q2: ESM3 模型加载失败

请确认：

- `esm` 版本与模型权重兼容
- 运行账号有本地权重访问权限
- CUDA / 驱动版本匹配（如使用 GPU）

### Q3: 结果收敛慢或无提升

可尝试：

- 提高 `candidates_per_round`
- 增大 `max_iterations`
- 调低或调高 `patience`
- 调整评分权重，使目标函数更贴合你的实验目标

---

## 9. 最小可运行命令清单

```bash
# 1) 安装
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2) 启动 ESM3 server
export ESM3_MODEL_NAME=esm3-open
uvicorn protein_agent.esm3_server.server:app --host 0.0.0.0 --port 8001

# 3) 启动 Agent API（另一个终端）
export PROTEIN_AGENT_ESM3_SERVER_URL=http://127.0.0.1:8001
uvicorn protein_agent.api.main:app --host 0.0.0.0 --port 8000

# 4) 请求任务
curl -X POST http://127.0.0.1:8000/design_protein \
  -H "Content-Type: application/json" \
  -d '{"task":"Design an improved GFP and iteratively optimize it."}'
```

---

如果你愿意，我下一步可以继续把 README 再细化成“**你当前服务器部署参数**”的一键版（例如写成 `start_esm3.sh + start_agent.sh + smoke_test.sh`），并加入更贴近 GFP 的定制评分项。

---

## 10. 真实 ESM3 接入与运维手册（2026-03）

这一节面向已经在服务器上部署好了 ESM3、希望 Agent 真正调到本地真实模型的使用者。

### 10.1 推荐架构

推荐把系统拆成两层：

1. **本地常驻 ESM3 服务层**
   - 负责模型加载、生成、突变、结构预测。
   - 模型只在启动时加载一次，避免每轮迭代重复加载权重。
   - 对外暴露：`/generate_sequence`、`/mutate_sequence`、`/predict_structure`、`/health`。

2. **Protein Agent 编排层**
   - 负责自然语言理解、计划生成、实验循环、候选筛选、打分与总结。
   - 对外暴露：`/design_protein`、`/health`。
   - 默认通过 HTTP 调上面的常驻 ESM3 服务。

这样做的优势：

- 模型只加载一次，启动后多轮实验更稳定。
- Agent 不再承担模型初始化成本。
- 后续把 ESM3 单独迁移到另一台机器也更容易。

补充说明：

- `openai` Python 包在当前架构里属于**可选依赖**。
- 只有当你需要：
  - 启用 LLM 规划；或
  - 启用 `PROTEIN_AGENT_ALLOW_GENERATED_PYTHON=true` 的临时代码兜底
  时，它才是必需的。
- 如果你只是使用“本地真实 ESM3 常驻服务 + HTTP 调用”的推荐路径，没有安装 `openai` 也不应该阻止服务启动。

### 10.2 当前仓库里的关键文件

- `protein_agent/esm3_server/server.py`
  - 本地常驻 ESM3 服务入口。
- `protein_agent/esm3_integration/client.py`
  - 统一 ESM3 接入层，支持 `http`、`local`、`generated` 三种后端。
- `protein_agent/esm3_integration/bridge.py`
  - 本地部署桥接层，负责把你的 `esm3/` 仓库、`weights/`、`data/`、`projects/` 加入运行环境。
- `protein_agent/agent/executor.py`
  - 把 Agent 的 `generate` / `mutate` / `evaluate` 动作统一路由到 ESM3 客户端。
- `protein_agent/workflows/gfp_optimizer.py`
  - GFP 工作流，首轮默认使用 GFP scaffold 作为种子。
- `.env`
  - 当前推荐配置文件。
- `start_esm3_server.sh` / `start_agent.sh` / `start_all.sh` / `stop_all.sh` / `status_all.sh`
  - 启动、停止、状态检查脚本。

### 10.3 你当前服务器的推荐配置

如果你的服务器路径和当前会话里提供的一致，推荐核心变量如下：

```bash
PROTEIN_AGENT_ESM3_BACKEND=http
PROTEIN_AGENT_ESM3_SERVER_URL=http://127.0.0.1:8001

PROTEIN_AGENT_ESM3_PYTHON_PATH=/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python
PROTEIN_AGENT_ESM3_ROOT=/mnt/disk3/tio_nekton4/esm3
PROTEIN_AGENT_ESM3_PROJECT_DIR=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction
PROTEIN_AGENT_ESM3_WEIGHTS_DIR=/mnt/disk3/tio_nekton4/esm3/weights
PROTEIN_AGENT_ESM3_DATA_DIR=/mnt/disk3/tio_nekton4/esm3/data
PROTEIN_AGENT_ESM3_MODEL_NAME=esm3_sm_open_v1
PROTEIN_AGENT_ESM3_DEVICE=cuda
```

解释：

- `PROTEIN_AGENT_ESM3_BACKEND=http`
  - 推荐值。Agent 不直接每次起 Python 子进程加载模型，而是请求常驻服务。
- `PROTEIN_AGENT_ESM3_SERVER_URL`
  - Agent 访问 ESM3 常驻服务的地址。
- `PROTEIN_AGENT_ESM3_PYTHON_PATH`
  - 能 `import torch` 和本地 `esm` 的 Python 解释器。
- `PROTEIN_AGENT_ESM3_ROOT`
  - 你的 `esm3/` 根目录。
- `PROTEIN_AGENT_ESM3_PROJECT_DIR`
  - GFP 项目目录，便于桥接层导入你已有项目脚本。
- `PROTEIN_AGENT_ESM3_WEIGHTS_DIR` / `PROTEIN_AGENT_ESM3_DATA_DIR`
  - 供本地模型加载和后续扩展使用。
- `PROTEIN_AGENT_ESM3_MODEL_NAME`
  - 对于你当前这套本地权重目录，推荐使用 `esm3_sm_open_v1`。
- `PROTEIN_AGENT_ESM3_DEVICE`
  - 推荐 `cuda`，如果服务器显存不够可以改成 `cpu`，但会非常慢。

### 10.4 推荐启动方式

#### 方式一：一键启动

```bash
chmod +x start_esm3_server.sh start_agent.sh start_all.sh stop_all.sh status_all.sh
./start_all.sh
```

这个命令会自动完成：

- 读取 `.env`
- 启动本地常驻 ESM3 服务
- 轮询 `http://127.0.0.1:8001/health`
- 等 ESM3 完全就绪后再启动 Agent
- 记录日志和 PID 文件

停止：

```bash
./stop_all.sh
```

查看状态：

```bash
./status_all.sh
```

#### 方式二：手动分两步启动

先启动 ESM3：

```bash
./start_esm3_server.sh
```

再启动 Agent：

```bash
./start_agent.sh
```

这种方式适合你想分别看两个前台日志的场景。

### 10.4.1 浏览器访问入口

现在 Python `protein_agent` 已经自带一个聊天式前端页面，不需要再手写 curl 才能体验。

启动后可直接访问：

```text
http://127.0.0.1:8000/
```

如果你通过 SSH 隧道把远端 `8000` 映射到本机 `8080`，则访问：

```text
http://127.0.0.1:8080/
```

该页面会：

- 提供聊天式输入框
- 调用 `POST /design_protein`
- 自动展示计划、最佳序列、候选历史和完整 JSON
- 支持将上一轮最佳序列自动带入下一轮任务描述
- 支持深色模式、最近任务历史，以及最佳序列差异高亮
- 支持在前端切换“迭代设计 / 逆折叠 / 功能条件化生成”三种任务模式
- 逆折叠模式支持粘贴/上传 PDB，功能条件化模式支持关键词与注释 JSON 辅助编辑

API 文档页面仍保留在：

```text
http://127.0.0.1:8000/docs
```

如果走 SSH 隧道，则通常是：

```text
http://127.0.0.1:8080/docs
```

### 10.5 如何判断“已经真的接上真实 ESM3”

至少满足下面三层检查：

1. **旧服务检查不是关键**
   - `curl http://127.0.0.1:8080/health`
   - 这只能说明旧服务活着，不代表真实 ESM3 已经接上。

2. **常驻 ESM3 服务必须正常**
   - `curl http://127.0.0.1:8001/health`
   - 它应该返回 `status`、`device`、`model`、`root`、`project_dir` 等信息。

3. **Agent 必须能调用常驻 ESM3 服务**
   - `curl http://127.0.0.1:8000/health`
   - 再实际发一个 `/design_protein` 请求，确认不是只启动了 API 空壳。

建议验证顺序：

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/design_protein \
  -H 'Content-Type: application/json' \
  -d '{"task":"请自动设计 GFP 并迭代优化", "max_iterations": 3, "candidates_per_round": 4}'
```

### 10.6 日志、PID、状态文件说明

默认情况下：

- `logs/esm3_server.log`
  - 本地常驻 ESM3 服务日志。
- `logs/protein_agent.log`
  - Agent API 日志。
- `logs/esm3_server.pid`
  - ESM3 服务 PID。
- `logs/protein_agent.pid`
  - Agent API PID。

这些路径都可以通过 `.env` 里的可选变量覆盖。

### 10.7 常见排障思路

#### 1）`8001/health` 起不来

优先怀疑：

- `PROTEIN_AGENT_ESM3_PYTHON_PATH` 不对
- `PROTEIN_AGENT_ESM3_ROOT` 不对
- 本地 `esm` 包导入失败
- 权重或 data 路径不对
- CUDA/显存问题导致启动时加载模型失败

先看：

```bash
tail -n 50 logs/esm3_server.log
```

#### 2）`8001/health` 正常，但 `8000/design_protein` 失败

优先怀疑：

- Agent 没有使用 `http` 后端
- `PROTEIN_AGENT_ESM3_SERVER_URL` 不对
- 结构预测或突变接口返回格式和预期不一致
- 某些候选生成成功，但评分或结构预测失败

先看：

```bash
tail -n 50 logs/protein_agent.log
```

#### 3）GFP 任务能跑，但结果质量一般

这是“接通真实 ESM3”和“设计效果足够好”之间的区别。

如果只是确认链路，先看能不能：

- 正常生成候选
- 正常做突变
- 正常给出结构预测/评分
- 正常迭代多轮

等链路稳定后，再优化：

- 候选数 `candidates_per_round`
- 最大迭代轮数 `max_iterations`
- prompt 设计
- 你项目里的专用生成脚本/模板

#### 4）是否应该启用 `PROTEIN_AGENT_ALLOW_GENERATED_PYTHON`

建议顺序：

1. 先跑通 `http` 常驻服务模式。
2. 再确认本地项目是否真的需要 LLM 临时代码兜底。
3. 只有在你明确接受这个风险时，再打开：

```bash
PROTEIN_AGENT_ALLOW_GENERATED_PYTHON=true
```

因为这个功能本质上是在你的 ESM3 环境里执行 LLM 生成的 Python。

### 10.8 推荐日常命令

启动：

```bash
./start_all.sh
```

检查：

```bash
./status_all.sh
```

停止：

```bash
./stop_all.sh
```

查看 ESM3 服务日志：

```bash
tail -f logs/esm3_server.log
```

查看 Agent 日志：

```bash
tail -f logs/protein_agent.log
```

### 10.9 当前建议结论

对于你现在这套环境，**最佳实践不是让 Agent 每次直接本地加载模型**，而是：

- 用 `protein_agent.esm3_server.server` 启一个常驻的真实 ESM3 服务
- 再让 `protein_agent.api.main` 通过 HTTP 调它

这就是当前仓库里已经改好的推荐路径。

### 10.10 Phase 1 新增能力入口

当前版本已经额外补了两项能力的后端与主 API 入口：

- `POST /inverse_fold`
- `POST /generate_with_function`

### 10.11 多模态设计入口

除了独立的 `inverse_fold` 与 `generate_with_function` 之外，当前版本还把多模态输入接入了主设计入口：

- `POST /design_protein`

现在这个接口除了 `task` 之外，还支持以下可选字段：

- `sequence`
- `sequence_length`
- `pdb_path`
- `pdb_text`
- `function_keywords`
- `function_annotations`

这意味着你可以在一次请求中同时提交：

- 文本目标
- 参考序列
- 结构文件 / 结构文本
- 功能约束

系统会优先尝试把这些多模态信息转成初始候选或种子序列，再进入后续的评估与迭代优化。

最小示例：

```bash
curl -X POST http://127.0.0.1:8000/design_protein \
  -H 'Content-Type: application/json' \
  -d '{
    "task":"请基于给定结构和功能约束继续优化 GFP",
    "sequence":"MSKGEELFTGVV",
    "pdb_path":"/abs/path/to/example.pdb",
    "function_keywords":["fluorescent protein"],
    "sequence_length":128,
    "max_iterations":3,
    "candidates_per_round":4,
    "patience":2
  }'
```

聊天前端中的“迭代设计”模式也已经支持这组高级输入字段。

也就是说，在浏览器工作台里你现在可以直接在“迭代设计”模式下填写：

- 参考序列
- 结构路径 / 结构文本 / 上传结构文件
- 功能关键词
- 功能注释 JSON

这些输入都会一起进入同一个 `design_protein` 设计请求。

在当前版本里，`design_protein` 还额外支持以下进化模拟参数：

- `population_size`
- `elite_size`
- `parent_pool_size`
- `mutations_per_parent`

它们会驱动真正的种群式迭代，而不再只是简单的“top 候选 + 突变”循环。

聊天前端中的“迭代设计”模式也已经支持这组进化模拟参数，并会在右侧展示每一代的统计信息。

#### `POST /inverse_fold`

用途：

- 输入结构信息（当前优先支持 `pdb_path` 或 `pdb_text`）
- 输出一个或多个候选序列

最小示例：

```bash
curl -X POST http://127.0.0.1:8000/inverse_fold \
  -H 'Content-Type: application/json' \
  -d '{"pdb_path":"/abs/path/to/example.pdb","num_candidates":2,"temperature":0.7,"num_steps":1}'
```

#### `POST /generate_with_function`

用途：

- 输入功能标签或功能关键词
- 在功能条件约束下生成候选序列

最小示例：

```bash
curl -X POST http://127.0.0.1:8000/generate_with_function \
  -H 'Content-Type: application/json' \
  -d '{"sequence_length":128,"function_keywords":["fluorescent protein"],"num_candidates":2,"temperature":0.8,"num_steps":8}'
```

也支持显式区间注释：

```bash
curl -X POST http://127.0.0.1:8000/generate_with_function \
  -H 'Content-Type: application/json' \
  -d '{"sequence_length":128,"function_annotations":[{"label":"fluorescent protein","start":1,"end":128}],"num_candidates":2}'
```

#### 当前限制

- `inverse_fold` 目前优先支持 `pdb_path` / `pdb_text`，还没有在前端聊天页单独做上传面板。
- `generate_with_function` 已有 API，但聊天页还没有专门的“功能标签输入卡片”，现阶段更适合通过 `/docs` 或 curl 使用。
- 这两项能力已经进入“可调通、可文档化、可直接测试”的状态，但还没像 GFP 迭代设计那样完全融入主聊天工作流。

### 10.8.1 冒烟测试

如果你想快速确认“真实 ESM3 服务 + Agent 编排链路”是否都正常，可以直接执行：

```bash
./smoke_test.sh
```

这个脚本会自动完成以下检查：

- 访问 ESM3 服务健康检查接口
- 访问 Agent API 健康检查接口
- 直接调用一次 `POST /generate_sequence`
- 直接调用一次 `POST /predict_structure`
- 调用一次最小 `POST /design_protein` 任务

默认测试参数比较保守：

- 序列：`MSKGEELFTGVV`
- 迭代轮数：`1`
- 每轮候选数：`2`

如果你想临时覆盖这些测试参数，可以这样：

```bash
PROTEIN_AGENT_SMOKE_SEQUENCE=MSKGEELFTGVV \
PROTEIN_AGENT_SMOKE_ITERATIONS=1 \
PROTEIN_AGENT_SMOKE_CANDIDATES=2 \
./smoke_test.sh
```

如果冒烟测试失败，脚本会自动输出最近的 ESM3 日志和 Agent 日志，方便你继续定位。

### 10.9 第三方客户端连续追问（`reasoning_context`）

如果你是通过 OpenAI 兼容接口 `POST /v1/chat/completions` 来接入，而不是直接使用内置聊天页，推荐按下面的方式实现“先设计、再解释、再继续追问”。

#### 响应里新增了什么

现在 `POST /v1/chat/completions` 的响应除了标准的 `choices[0].message.content` 之外，还会额外返回：

- `chat_mode`
  - `execution`：这次主要是在跑设计/生成。
  - `reasoning`：这次主要是在解释当前结果，而不是重新跑设计。
- `reasoning_context`
  - 一个可直接缓存并在下一轮原样回传的上下文对象。
  - 用来让服务端知道“当前正在围绕哪一批候选继续解释”。

典型响应片段示例：

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "这一轮已经跑完，当前排在最前面的候选来自第 3 轮……"
      },
      "finish_reason": "stop"
    }
  ],
  "chat_mode": "execution",
  "best_candidate": {
    "id": "cand-3-1",
    "sequence": "MSKGEEL...",
    "score": 0.9132,
    "round": 3
  },
  "total_generated": 12,
  "rounds": 3,
  "reasoning_context": {
    "version": 1,
    "chat_mode": "execution",
    "current_mode": "design",
    "latest_result": {
      "request": {
        "target_protein": "GFP",
        "num_candidates": 4,
        "rounds": 3
      },
      "best_candidate": {
        "id": "cand-3-1",
        "sequence": "MSKGEEL...",
        "score": 0.9132,
        "round": 3
      },
      "all_candidates": [
        { "id": "cand-3-1", "score": 0.9132 },
        { "id": "cand-2-4", "score": 0.9011 }
      ],
      "total_generated": 12,
      "rounds": 3
    },
    "previous_best_sequence": "MSKGEEL...",
    "latest_best_sequence": "MSKGEEL..."
  }
}
```

#### 最推荐的客户端做法

1. 第一次请求只发送正常的 `messages`。
2. 收到响应后，缓存整段 `reasoning_context`。
3. 当用户继续追问“为什么这个候选更适合验证”“帮我比较前两名候选”时：
   - 把新的用户消息继续追加到 `messages`
   - 同时把上一次响应里的 `reasoning_context` 原样回传
4. 服务端会优先把这次请求视为“解释型追问”，而不是重新跑设计。

#### 最小请求示例：先跑设计

```bash
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "esm3-protein-design-agent",
    "messages": [
      {
        "role": "user",
        "content": "请自动设计 GFP，并迭代优化，尽量保留 GSG motif"
      }
    ]
  }'
```

这一步结束后，请把响应中的 `reasoning_context` 缓存起来。

#### 最小请求示例：继续追问解释

```bash
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "esm3-protein-design-agent",
    "messages": [
      {
        "role": "user",
        "content": "请自动设计 GFP，并迭代优化，尽量保留 GSG motif"
      },
      {
        "role": "assistant",
        "content": "这一轮已经跑完，当前排在最前面的候选来自第 3 轮……"
      },
      {
        "role": "user",
        "content": "请解释为什么当前候选更适合验证"
      }
    ],
    "reasoning_context": {
      "version": 1,
      "chat_mode": "execution",
      "current_mode": "design",
      "latest_result": {
        "request": {
          "target_protein": "GFP",
          "num_candidates": 4,
          "rounds": 3
        },
        "best_candidate": {
          "id": "cand-3-1",
          "sequence": "MSKGEEL...",
          "score": 0.9132,
          "round": 3
        },
        "all_candidates": [
          { "id": "cand-3-1", "score": 0.9132 },
          { "id": "cand-2-4", "score": 0.9011 }
        ],
        "total_generated": 12,
        "rounds": 3
      },
      "previous_best_sequence": "MSKGEEL...",
      "latest_best_sequence": "MSKGEEL..."
    }
  }'
```

#### 兼容字段说明

为了兼容旧客户端，目前服务端仍然接受下面两种方式：

- 推荐：只传 `reasoning_context`
- 兼容旧写法：继续传顶层的
  - `latest_result`
  - `previous_best_sequence`

如果两者同时存在，服务端会优先合并使用，不要求你立刻升级所有客户端。

#### 什么时候会进入解释模式

通常当最后一条用户消息包含这些意图时，会被识别为解释型追问：

- “解释为什么当前候选更适合验证”
- “帮我比较前两名候选”
- “分析这一轮结果”
- “为什么它比上一轮更好”

如果没有可用的结果上下文，服务端会明确提示你先提供 `latest_result` / `reasoning_context`，或先调用一次设计。

#### 环境变量说明

Python Agent 侧的 LLM 配置现在支持两组变量，便于和 Go 代理保持一致：

- `PROTEIN_AGENT_OPENAI_API_KEY` / `PROTEIN_AGENT_OPENAI_BASE_URL` / `PROTEIN_AGENT_LLM_MODEL`
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`

如果你已经给 Go 代理配置了 `OPENAI_*`，Python 侧的 reasoner 也会自动复用这组配置。
