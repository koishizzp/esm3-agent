# 服务层仓库 / 训练层仓库 同步教程

这份教程专门回答你现在这个问题：

> 服务器上有两个仓库，一个负责在线服务，一个负责训练模型。  
> 我不知道这次“最新代码”到底应该同步哪些文件。

先直接说结论：

## 1. 这次你遇到的两个问题，**只需要更新服务层仓库**

你刚才遇到的是：

1. `500 - auth_unavailable: no auth available`
2. `8080` 页面里做 GFP 设计时，没有真正锁住参考序列和 `SYG`

这两个问题都发生在：

- 页面层
- Agent API 层
- 规划器 / 解释器 / 内存筛选层

它们**不在训练脚本层**，也**不在 surrogate 模型训练层**。

所以这次：

- **服务层仓库要更新**
- **训练层仓库可以先不动**

---

## 2. 这次必须同步到“服务层仓库”的文件

请把下面这些文件同步到你的 **服务层 repo**：

```text
protein_agent/api/main.py
protein_agent/api/chat_ui.html
protein_agent/agent/planner.py
protein_agent/agent/reasoner.py
protein_agent/memory/experiment_memory.py
```

如果你的服务层仓库里还没有下面这个文件，也一起同步：

```text
protein_agent/constraints.py
```

### 这些文件分别解决什么问题

#### `protein_agent/api/main.py`

解决：

- 任务文本里直接粘长氨基酸序列时，后端自动识别成参考序列
- 固定残基真正进入请求上下文

#### `protein_agent/api/chat_ui.html`

解决：

- `8080` 页面新增“固定残基”输入框
- 页面摘要不再优先把无效候选说成“当前最优”
- 页面提示更明确，告诉你直接粘序列也会被识别

#### `protein_agent/agent/planner.py`

解决：

- 外部 LLM 网关报 `auth_unavailable` 时，不再直接 500
- 会自动回退到本地确定性 plan

#### `protein_agent/agent/reasoner.py`

解决：

- 解释型回复不再优先引用 `valid_candidate=false` 的无效候选

#### `protein_agent/memory/experiment_memory.py`

解决：

- `best()` 不再把无效候选当成真正的最佳候选

#### `protein_agent/constraints.py`

如果你的服务层仓库还没有它，就必须补上。  
它负责固定残基和长度约束的解析与投影。

---

## 3. 这次**不需要**同步到“训练层仓库”的文件

这次问题和下面这些东西无关：

- `prepare_gfp_dataset.py`
- `train_gfp_surrogate.py`
- `run_gfp_surrogate_pipeline.py`
- embedding 提取脚本
- retrospective / active learning 训练脚本
- 模型文件本身

所以对于你当前这次排障：

- **训练层仓库先不要动**
- **模型也不用重训**

除非你后面明确要重新训练 surrogate，否则现在不需要把训练 repo 也跟着同步一遍。

---

## 4. 最简单的理解方式

如果你把服务器分成：

### 仓库 A：服务层仓库

职责：

- 启动 `8000` Agent API
- 启动 `8080` 页面
- 在线调用 ESM3
- 在线调用 surrogate
- 返回当前设计结果

### 仓库 B：训练层仓库

职责：

- 数据清洗
- embedding 提取
- 训练 surrogate
- retrospective / active-learning 数据构建

那么这次你要修的是：

```text
仓库 A（服务层）
```

不是：

```text
仓库 B（训练层）
```

---

## 5. 推荐你现在采用的目录记法

为了避免再混乱，建议你在服务器上先明确两个变量：

```bash
SERVE_REPO=/path/to/your/service_repo
TRAIN_REPO=/path/to/your/training_repo
```

然后你以后每次都先问自己：

### 如果问题是这些，就动 `SERVE_REPO`

- 页面不对
- `/design_protein` 返回不对
- 结果摘要不对
- 任务规划报错
- 在线请求 500
- 固定残基没生效
- 页面没出现新输入框

### 如果问题是这些，就动 `TRAIN_REPO`

- 数据集清洗不对
- embedding 跑不通
- surrogate 训练不对
- active-learning 数据构建不对
- promotion 前的模型训练有问题

---

## 6. 你现在应该怎么同步

下面给你一个“最稳妥”的做法。

### Step 1. 先在本地确认要拷贝的服务层文件

这次只盯这 5 到 6 个文件：

```text
protein_agent/api/main.py
protein_agent/api/chat_ui.html
protein_agent/agent/planner.py
protein_agent/agent/reasoner.py
protein_agent/memory/experiment_memory.py
protein_agent/constraints.py
```

如果你确认服务器服务层仓库里已经有 `constraints.py`，这次就可以不覆盖它。  
但如果你不确定，建议一起同步，最稳。

### Step 2. 只把这些文件覆盖到服务层仓库

也就是：

```text
SERVE_REPO
```

不要先去改 `TRAIN_REPO`。

### Step 3. 修改服务层 `.env`

这次只改 **服务层 repo** 的 `.env`。

把这些项清空：

```text
OPENAI_API_KEY=
OPENAI_BASE_URL=
PROTEIN_AGENT_OPENAI_API_KEY=
PROTEIN_AGENT_OPENAI_BASE_URL=
```

如果你只是想避免 `auth_unavailable`，这一步非常关键。

### Step 4. 重启服务层的 Agent API

如果你用脚本启动：

```bash
cd "$SERVE_REPO"
./stop_all.sh
./start_all.sh
./status_all.sh
```

如果你分开启动，也至少要重启：

- `8000` Agent API

### Step 5. 刷新 `8080` 页面

进入：

```text
http://127.0.0.1:8080/
```

然后先检查页面上有没有新东西：

#### 你应该看到

- “固定残基（可选）”输入框

如果这个输入框都没有出现，说明你当前打开的页面还不是最新服务层代码。

---

## 7. 如何快速确认“服务层代码已经更新成功”

最简单的方法不是看 git，而是直接看页面和行为。

### 检查 1：页面上有没有“固定残基”输入框

如果有，说明：

- `chat_ui.html` 已经是新版本

### 检查 2：把长氨基酸序列直接粘进任务文本

如果后端已经更新，它会自动识别，不再完全忽略这条序列。

### 检查 3：再遇到外部 LLM 鉴权失败时，不应该再直接 500

如果 `planner.py` 已更新，那么即使外部 LLM 网关失败，系统也会回退到本地 plan。

### 检查 4：如果候选违反硬约束，摘要不应再继续把它说成“当前可靠最佳”

如果你看到页面开始提示：

```text
当前没有通过硬约束筛选的可靠最佳序列
```

说明：

- `reasoner.py`
- `experiment_memory.py`
- `chat_ui.html`

这几层已经是新版。

---

## 8. 如果你想最省事地同步，建议只做这一个最小包

你可以把这次服务层更新理解成一个“最小补丁包”：

```text
protein_agent/api/main.py
protein_agent/api/chat_ui.html
protein_agent/agent/planner.py
protein_agent/agent/reasoner.py
protein_agent/memory/experiment_memory.py
protein_agent/constraints.py
```

这就是你这次真正需要的“最新代码”。

其余训练层脚本，这次先不要碰。

---

## 9. 如果你还是分不清，最实用的判断法

以后每次你只要先问自己一句：

> 这次问题发生在“在线设计请求和页面显示”里，还是发生在“离线训练 surrogate”里？

### 如果答案是前者

就更新：

```text
服务层仓库
```

### 如果答案是后者

就更新：

```text
训练层仓库
```

你这次毫无疑问属于前者。

---

## 10. 最后给你一个可直接执行的最短版

你现在直接照这个走就行：

1. 找到服务层仓库目录 `SERVE_REPO`
2. 只同步这几个文件到 `SERVE_REPO`：

```text
protein_agent/api/main.py
protein_agent/api/chat_ui.html
protein_agent/agent/planner.py
protein_agent/agent/reasoner.py
protein_agent/memory/experiment_memory.py
protein_agent/constraints.py
```

3. 打开 `SERVE_REPO/.env`
4. 清空：

```text
OPENAI_API_KEY=
OPENAI_BASE_URL=
PROTEIN_AGENT_OPENAI_API_KEY=
PROTEIN_AGENT_OPENAI_BASE_URL=
```

5. 重启 `SERVE_REPO` 的 Agent 服务
6. 打开 `http://127.0.0.1:8080/`
7. 确认页面里出现“固定残基（可选）”
8. 再按 GFP 设计模板重新跑

---

## 11. 如果你愿意，我下一步还能继续帮你做什么

如果你下一条告诉我：

- 你的服务层仓库路径
- 你的训练层仓库路径
- 你平时是怎么同步文件的（scp / rsync / git pull / 手工覆盖）

我可以直接再给你写一个：

> **按你服务器目录结构定制的“逐条命令版同步教程”**

也就是我直接写成：

```bash
cp xxx 到服务层
改哪个 .env
重启哪个服务
怎么确认已生效
```

你就不用再自己翻译这份通用教程了。

