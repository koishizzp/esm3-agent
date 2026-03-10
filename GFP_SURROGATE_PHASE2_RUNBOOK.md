# GFP Surrogate Phase 2 Runbook

这份文档用于指导你在服务器上完成第二层改造，也就是：

1. 准备 Sarkisyan GFP 数据
2. 提取 ESM3 embedding
3. 训练 surrogate 模型
4. 把 Agent 切到 `hybrid` 打分
5. 重启服务并验证结果


## 1. 推荐服务器工作区

建议把当前项目完整放在这个目录：

```bash
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent
```

下面所有命令都默认你已经进入这个目录：

```bash
cd /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent
```


## 2. 你需要准备的文件

### 2.1 项目代码

把当前本地仓库同步到服务器工作区。

至少要包含这些新文件：

- `get_embeddings_offline.py`
- `protein_agent/scripts/prepare_gfp_dataset.py`
- `protein_agent/scripts/export_gfp_fasta.py`
- `protein_agent/scripts/build_embedding_cache.py`
- `protein_agent/scripts/extract_gfp_embeddings.py`
- `protein_agent/scripts/train_gfp_surrogate.py`
- `protein_agent/scripts/run_gfp_surrogate_pipeline.py`
- `protein_agent/surrogate/`

### 2.2 数据文件

把 figshare 下载的文件放到：

```bash
data/gfp/raw/amino_acid_genotypes_to_brightness.tsv
data/gfp/raw/avGFP_reference_sequence.fa
```

如果目录不存在，先创建：

```bash
mkdir -p data/gfp/raw
```

### 2.3 embedding 脚本

把服务器原项目里的这个文件复制到当前工作区根目录：

```bash
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/scripts/get_embeddings_offline.py
```

目标位置：

```bash
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/get_embeddings_offline.py
```


## 3. 运行前检查

### 3.1 确认 ESM3 环境

推荐 Python：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python
```

确认它可用：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python -V
```

### 3.2 安装依赖

在工作区执行：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python -m pip install -r requirements.txt
```

### 3.3 检查 `.env`

确认 `.env` 里这几项已经是你服务器现有的真实路径：

```bash
PROTEIN_AGENT_ESM3_PYTHON_PATH=/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python
PROTEIN_AGENT_ESM3_ROOT=/mnt/disk3/tio_nekton4/esm3
PROTEIN_AGENT_ESM3_PROJECT_DIR=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction
PROTEIN_AGENT_ESM3_WEIGHTS_DIR=/mnt/disk3/tio_nekton4/esm3/weights
PROTEIN_AGENT_ESM3_DATA_DIR=/mnt/disk3/tio_nekton4/esm3/data
PROTEIN_AGENT_ESM3_MODEL_NAME=esm3_sm_open_v1
PROTEIN_AGENT_ESM3_DEVICE=cuda
```


## 4. 一键执行第二层 pipeline

直接运行：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python protein_agent/scripts/run_gfp_surrogate_pipeline.py \
  --raw-input data/gfp/raw/amino_acid_genotypes_to_brightness.tsv \
  --reference-fasta data/gfp/raw/avGFP_reference_sequence.fa \
  --workspace-dir /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent \
  --embedding-script /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/get_embeddings_offline.py \
  --esm-python /mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  --env-file .env \
  --device cuda \
  --pooling mean \
  --model-name xgb_ensemble_v1 \
  --ensemble-size 5
```

这条命令会自动完成：

1. 清洗 GFP 数据集
2. 导出 FASTA
3. 跑离线 ESM3 embedding
4. 构建 `embedding_cache.npz`
5. 训练 `xgb_ensemble_v1`
6. 更新 `.env` 中的 surrogate 配置


## 5. 产物检查

跑完后，重点检查下面这些文件。

### 5.1 清洗后的数据

```bash
ls data/gfp/processed
```

预期至少有：

- `cleaned.parquet` 或 `cleaned.csv`
- `dataset_summary.json`

### 5.2 embedding 产物

```bash
ls data/gfp/embeddings/esm3_mean_v1
ls data/gfp/embeddings/esm3_mean_v1/offline_run
ls data/gfp/embeddings/esm3_mean_v1/offline_run/embeddings | head
```

预期至少有：

- `sequences.fasta`
- `embedding_cache.npz`
- `offline_run/metadata.csv`
- `offline_run/run_summary.json`

### 5.3 surrogate 模型

```bash
ls models/gfp_surrogate/xgb_ensemble_v1
```

预期至少有：

- `model_0.joblib`
- `feature_config.json`
- `metadata.json`
- `training_report.json`


## 6. 检查 `.env` 是否已切到第二层

运行：

```bash
grep -E "PROTEIN_AGENT_SCORING_BACKEND|PROTEIN_AGENT_SURROGATE_" .env
```

预期至少看到：

```bash
PROTEIN_AGENT_SCORING_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_MODEL_PATH=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1
PROTEIN_AGENT_SURROGATE_MODEL_TYPE=xgboost
PROTEIN_AGENT_SURROGATE_ENSEMBLE_SIZE=5
PROTEIN_AGENT_SURROGATE_FEATURE_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_USE_STRUCTURE_FEATURES=false
```


## 7. 重启服务

```bash
./stop_all.sh
./start_all.sh
./status_all.sh
```

如果你习惯分开启动，也可以：

```bash
./start_esm3_server.sh
./start_agent.sh
```


## 8. 验证第二层是否已经生效

### 8.1 健康检查

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8000/health
```

### 8.2 跑一个最小 GFP 请求

```bash
curl -X POST http://127.0.0.1:8000/design_protein \
  -H "Content-Type: application/json" \
  -d '{
    "task": "design a brighter GFP variant",
    "max_iterations": 1,
    "candidates_per_round": 2,
    "patience": 1
  }'
```

重点看返回里的 `best_candidate.metadata`。

如果第二层接通，应该能看到类似字段：

- `score_mode`
- `predicted_fluorescence`
- `prediction_std`
- `surrogate_score`
- `model_version`

如果 surrogate 没加载成功，也应该还能正常返回，但 `score_mode` 会是：

- `structure_fallback`


## 9. 推荐额外检查

### 9.1 看训练报告

```bash
cat models/gfp_surrogate/xgb_ensemble_v1/training_report.json
```

关注：

- `evaluation.spearman`
- `evaluation.pearson`
- `evaluation.rmse`

### 9.2 看 embedding 运行摘要

```bash
cat data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json
```

关注：

- `processed`
- `failed`
- `skipped_invalid`
- `throughput_seq_per_sec`


## 10. 如果中间失败，按这个顺序排查

### 10.1 embedding 脚本起不来

先检查：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python -m py_compile get_embeddings_offline.py
```

再检查环境变量：

```bash
echo $PROTEIN_AGENT_ESM3_ROOT
echo $PROTEIN_AGENT_ESM3_WEIGHTS_DIR
echo $PROTEIN_AGENT_ESM3_DATA_DIR
```

### 10.2 数据清洗失败

检查输入文件列名：

```bash
head -n 5 data/gfp/raw/amino_acid_genotypes_to_brightness.tsv
```

当前脚本优先识别这些列：

- `medianBrightness`
- `aaMutations`
- `aaSequence`
- `std`
- `uniqueBarcodes`

### 10.3 模型训练失败

先检查依赖：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python -c "import xgboost, pandas, sklearn, scipy, joblib"
```

### 10.4 服务仍然只走第一层

检查：

```bash
grep -E "PROTEIN_AGENT_SCORING_BACKEND|PROTEIN_AGENT_SURROGATE_MODEL_PATH" .env
```

再重启：

```bash
./stop_all.sh
./start_all.sh
```


## 11. 如果你想分步手动执行

### Step 1. 清洗数据

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python protein_agent/scripts/prepare_gfp_dataset.py \
  --input data/gfp/raw/amino_acid_genotypes_to_brightness.tsv \
  --reference-fasta data/gfp/raw/avGFP_reference_sequence.fa \
  --output-dir data/gfp/processed
```

### Step 2. 导出 FASTA 并提 embedding

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python protein_agent/scripts/extract_gfp_embeddings.py \
  --input data/gfp/processed/cleaned.parquet \
  --output-dir data/gfp/embeddings/esm3_mean_v1 \
  --embedding-script ./get_embeddings_offline.py \
  --python /mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  --device cuda \
  --pooling mean \
  --format both
```

如果没有 `cleaned.parquet`，改成 `cleaned.csv`。

### Step 3. 训练 surrogate

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python protein_agent/scripts/train_gfp_surrogate.py \
  --input data/gfp/processed/cleaned.parquet \
  --output-dir models/gfp_surrogate/xgb_ensemble_v1 \
  --reference-fasta data/gfp/raw/avGFP_reference_sequence.fa \
  --split-column split_mutation_count \
  --model-type xgboost \
  --ensemble-size 5 \
  --feature-backend hybrid \
  --embedding-cache data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz
```

### Step 4. 手动改 `.env`

追加或修改：

```bash
PROTEIN_AGENT_SCORING_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_MODEL_PATH=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1
PROTEIN_AGENT_SURROGATE_MODEL_TYPE=xgboost
PROTEIN_AGENT_SURROGATE_ENSEMBLE_SIZE=5
PROTEIN_AGENT_SURROGATE_FEATURE_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_USE_STRUCTURE_FEATURES=false
```

### Step 5. 重启并验证

```bash
./stop_all.sh
./start_all.sh
curl http://127.0.0.1:8000/health
```


## 12. 当前版本的边界

这一版第二层已经能上线，但有两个事实要明确：

1. 默认线上打分建议用 `hybrid`，不要直接切成 `surrogate-only`
2. 如果 embedding 提取失败，当前流程不会自动退回到 mutation-only 训练；你需要先修复 embedding 步骤，或者改用手动训练命令并省略 `--embedding-cache`


## 13. 成功标准

如果下面 5 条都满足，就说明第二层完成了：

1. `models/gfp_surrogate/xgb_ensemble_v1/` 目录存在并包含模型文件
2. `.env` 已经切到 `PROTEIN_AGENT_SCORING_BACKEND=hybrid`
3. `/design_protein` 返回里出现 `predicted_fluorescence` 和 `prediction_std`
4. `score_mode` 为 `hybrid`
5. 即使模型路径错误，请求仍能返回，只是退回 `structure_fallback`
