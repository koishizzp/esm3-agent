# ESM3-Agent 标准目录方案

这份文档给出一套适合你当前服务器的**最终标准方案**：

- 只有一份主代码仓库
- 数据、模型、日志放到外部工作区
- 在线服务始终从同一个目录启动
- 训练仍然可以靠近 ESM3 本体

这套方案的目的很明确：

1. `git pull` 永远只拉一份代码
2. `./start_all.sh` 永远只在一个地方执行
3. 训练产物不要把主仓库撑大
4. 模型和数据仍然能放在靠近 ESM3 本体的位置

---

## 1. 最终推荐结构

### 1.1 主代码仓库

建议固定为：

```text
/mnt/disk3/tio_nekton4/esm3-agent
```

这是你以后**唯一的代码真源**。

### 1.2 外部工作区

建议固定为：

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace
```

这是你以后**唯一的数据 / 模型 / 训练产物工作区**。

---

## 2. 两个目录分别负责什么

### 2.1 `/mnt/disk3/tio_nekton4/esm3-agent`

这里只放：

- 代码
- 启动脚本
- `.env`
- 文档
- 测试

不要把长期数据、embedding、模型版本、大量运行产物继续堆在这里。

### 2.2 `/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace`

这里只放：

- GFP 原始数据
- processed 数据
- embedding cache
- surrogate 模型
- active learning 数据
- 导出的 batch
- wet-lab 导入结果
- 日志和 PID

不要再把它当第二份代码仓库来维护。

---

## 3. 文件级别应该怎么分

## 3.1 主代码仓库里应该保留的文件

下面这些文件和目录，应该留在：

```text
/mnt/disk3/tio_nekton4/esm3-agent
```

### 启动与运维文件

```text
.env
.env.local.example
.gitignore
start_all.sh
start_agent.sh
start_esm3_server.sh
stop_all.sh
status_all.sh
smoke_test.sh
restart.sh
stop.sh
status.sh
test.sh
```

### 主服务代码

```text
protein_agent/api/main.py
protein_agent/api/chat_ui.html
protein_agent/agent/planner.py
protein_agent/agent/executor.py
protein_agent/agent/workflow.py
protein_agent/agent/reasoner.py
protein_agent/tools/*
protein_agent/workflows/*
protein_agent/config/settings.py
protein_agent/constraints.py
protein_agent/memory/*
protein_agent/esm3_server/*
protein_agent/esm3_integration/*
protein_agent/active_learning/*
protein_agent/gfp.py
```

### 训练脚本代码

训练脚本本身仍然建议留在主代码仓库：

```text
protein_agent/scripts/prepare_gfp_dataset.py
protein_agent/scripts/extract_gfp_embeddings.py
protein_agent/scripts/train_gfp_surrogate.py
protein_agent/scripts/run_gfp_surrogate_pipeline.py
protein_agent/scripts/build_active_learning_dataset.py
protein_agent/scripts/retrain_active_learning_surrogate.py
protein_agent/scripts/promote_surrogate_model.py
protein_agent/scripts/export_active_learning_batch.py
protein_agent/scripts/import_wetlab_results.py
protein_agent/scripts/prepare_retrospective_active_learning_split.py
protein_agent/scripts/export_retrospective_oracle_batch.py
protein_agent/scripts/simulate_wetlab_from_oracle.py
```

原因很简单：

- 这些是“代码”
- 不是“产物”

### 文档与测试

```text
README.md
*.md
tests/*
```

---

## 3.2 外部工作区里应该放的文件

下面这些内容，建议统一放到：

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace
```

### 数据目录

```text
data/gfp/raw/*
data/gfp/processed/*
data/gfp/embeddings/*
```

### 模型目录

```text
models/gfp_surrogate/*
```

### 主动学习目录

```text
data/active_learning/runs/*
data/active_learning/batches/*
data/active_learning/wetlab/*
data/active_learning/datasets/*
data/active_learning/active_model.json
```

### 日志与 PID

```text
logs/esm3_server.log
logs/protein_agent.log
logs/esm3_server.pid
logs/protein_agent.pid
```

### 临时 / 导出 / 历史产物

如果你还有这些：

```text
服务器/
tmp/
exports/
archive/
```

也建议都放到工作区，不要放主代码仓库。

---

## 4. 最推荐的工作区具体结构

建议最终整理成：

```text
/mnt/disk3/tio_nekton4/esm3-agent
  .git/
  .env
  start_all.sh
  start_agent.sh
  start_esm3_server.sh
  stop_all.sh
  status_all.sh
  smoke_test.sh
  protein_agent/
  tests/
  README.md
  *.md

/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace
  data/
    gfp/
      raw/
      processed/
      embeddings/
    active_learning/
      runs/
      batches/
      wetlab/
      datasets/
      active_model.json
  models/
    gfp_surrogate/
  logs/
  tmp/
  exports/
  archive/
```

---

## 5. 以后在线服务应该始终从哪里启动

固定规则：

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent
./start_all.sh
```

以后不要再从第二份代码副本里启动。

也就是说：

- 页面 `8000/8080`
- Agent API
- 本地 ESM3 server

全部都默认从：

```text
/mnt/disk3/tio_nekton4/esm3-agent
```

启动。

---

## 6. `.env` 应该放在哪里

唯一生效的在线服务 `.env` 建议固定为：

```text
/mnt/disk3/tio_nekton4/esm3-agent/.env
```

这份 `.env` 负责两件事：

1. 配置在线服务启动参数
2. 告诉在线服务去哪里读取外部模型和日志

---

## 7. `.env` 里哪些路径应该指向外部工作区

建议你把下面这些项改成指向：

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace
```

### 模型路径

```text
PROTEIN_AGENT_SURROGATE_MODEL_PATH=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/models/gfp_surrogate/xgb_ensemble_v1_randomsplit
```

### 日志路径

```text
PROTEIN_AGENT_ESM3_SERVER_LOG=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/logs/esm3_server.log
PROTEIN_AGENT_API_LOG=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/logs/protein_agent.log
```

### PID 路径

```text
PROTEIN_AGENT_ESM3_SERVER_PID_FILE=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/logs/esm3_server.pid
PROTEIN_AGENT_API_PID_FILE=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/logs/protein_agent.pid
```

### 其余仍然保留在主代码仓库 `.env`

例如：

- `PROTEIN_AGENT_ESM3_PYTHON_PATH`
- `PROTEIN_AGENT_ESM3_ROOT`
- `PROTEIN_AGENT_ESM3_WEIGHTS_DIR`
- `PROTEIN_AGENT_ESM3_DATA_DIR`
- `PROTEIN_AGENT_GFP_REFERENCE_LENGTH`
- `PROTEIN_AGENT_GFP_CHROMOPHORE_START`
- `PROTEIN_AGENT_GFP_CHROMOPHORE_MOTIF`

---

## 8. 训练时应该在哪个目录执行

以后训练也建议统一从：

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent
```

执行。

也就是说：

- 训练脚本仍然用主代码仓库里的脚本
- 但输出路径显式写到外部工作区

这样做的好处是：

1. 代码只有一份
2. 训练和服务吃的是同一套脚本版本
3. 产物仍然落在工作区，不会把主仓库撑大

---

## 9. 训练命令应该怎么写

下面给你“具体到文件”的推荐写法。

### 9.1 数据清洗

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent

python protein_agent/scripts/prepare_gfp_dataset.py \
  --input /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/raw/amino_acid_genotypes_to_brightness.tsv \
  --reference-fasta /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/raw/avGFP_reference_mature.fa \
  --output-dir /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/processed
```

### 9.2 embedding 提取

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent

python protein_agent/scripts/extract_gfp_embeddings.py \
  --input /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/processed/cleaned.parquet \
  --output-dir /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/embeddings/esm3_mean_v1 \
  --embedding-script /mnt/disk3/tio_nekton4/esm3-agent/get_embeddings_offline.py \
  --python /mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  --env-file /mnt/disk3/tio_nekton4/esm3-agent/.env \
  --device cuda \
  --pooling mean \
  --format both
```

### 9.3 surrogate 训练

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent

python protein_agent/scripts/train_gfp_surrogate.py \
  --input /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/processed/cleaned.parquet \
  --output-dir /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/models/gfp_surrogate/xgb_ensemble_v1_randomsplit \
  --reference-fasta /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/raw/avGFP_reference_mature.fa \
  --chromophore-start 63 \
  --chromophore-motif SYG \
  --split-column split_random \
  --model-type xgboost \
  --ensemble-size 5 \
  --feature-backend hybrid \
  --embedding-cache /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz
```

### 9.4 active learning 数据集构建

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent

python protein_agent/scripts/build_active_learning_dataset.py \
  --base-dataset /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/processed/cleaned.parquet \
  --reference-fasta /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/raw/avGFP_reference_mature.fa \
  --output /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/active_learning/datasets/gfp_active_learning_v001.parquet
```

### 9.5 模型晋升

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent

python protein_agent/scripts/promote_surrogate_model.py \
  --model-dir /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/models/gfp_surrogate/xgb_ensemble_active_v001 \
  --env-file /mnt/disk3/tio_nekton4/esm3-agent/.env \
  --active-model-path /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/active_learning/active_model.json
```

---

## 10. 旧的第二份代码仓库应该怎么处理

你现在这个旧目录：

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent
```

如果它还保留整套代码副本，我建议你选一种方式：

### 方案 A：改名归档

例如：

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-code-archive
```

### 方案 B：把里面的产物迁到新工作区后，不再从那里启动任何服务

也就是：

- 不再 `cd` 到那里运行 `start_all.sh`
- 不再 `git pull` 那里
- 不再把它视作在线代码真源

如果你以后仍然保留那份旧代码仓库，也可以，但必须记住：

> 它不能再是在线服务的启动目录

否则你迟早还会再次搞混。

---

## 11. 最推荐的迁移顺序

### Step 1

保留：

```text
/mnt/disk3/tio_nekton4/esm3-agent
```

作为唯一代码仓库。

### Step 2

创建：

```bash
mkdir -p /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/raw
mkdir -p /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/processed
mkdir -p /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/gfp/embeddings
mkdir -p /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/data/active_learning
mkdir -p /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/models/gfp_surrogate
mkdir -p /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/logs
mkdir -p /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/tmp
mkdir -p /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/exports
mkdir -p /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace/archive
```

### Step 3

把旧数据和模型迁过去，例如：

```text
旧的 data/gfp/*
旧的 data/active_learning/*
旧的 models/gfp_surrogate/*
```

### Step 4

改：

```text
/mnt/disk3/tio_nekton4/esm3-agent/.env
```

让模型、日志、PID 指向新工作区。

### Step 5

以后统一：

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent
./start_all.sh
```

---

## 12. 以后判断“这个文件该放哪”的规则

### 放主代码仓库

如果它是：

- Python 源码
- HTML 页面
- 启动脚本
- `.env`
- 测试
- 文档

就放：

```text
/mnt/disk3/tio_nekton4/esm3-agent
```

### 放外部工作区

如果它是：

- 原始数据
- 清洗后的数据
- embedding
- 模型文件
- batch 导出
- wet-lab 导入
- active learning 中间产物
- 日志
- PID

就放：

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace
```

---

## 13. 最后的固定原则

你以后只要记住这三句话就够了：

1. **代码只有一份**：`/mnt/disk3/tio_nekton4/esm3-agent`
2. **产物只有一处**：`/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent-workspace`
3. **服务永远从主代码仓库启动**

