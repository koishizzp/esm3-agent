# Phase 3 Active Learning Guide

这份文档是当前仓库里 **唯一建议继续保留的 Phase 3 指南**。它合并了 MVP 说明、逐步教程和 retrospective round 1 命令清单，只保留现在仍然有效的闭环做法。

## 1. 目标和前提

Phase 3 的最小闭环是：

1. 设计或收集候选
2. 用 surrogate 排序
3. 导出一批待验证样本
4. 获得标签
5. 导入标签
6. 合并训练集
7. 重训 surrogate
8. 提升新模型版本
9. 下一轮继续使用新模型

开始之前，默认你已经满足：

- Phase 2 surrogate 可用
- 在线评分模式是 `hybrid`
- GFP 坐标已经统一到 mature avGFP：
  - `reference length = 236`
  - `chromophore start = 63`
  - `motif = SYG`

## 2. 当前仓库里应该使用的脚本

- `protein_agent/scripts/export_active_learning_batch.py`
- `protein_agent/scripts/import_wetlab_results.py`
- `protein_agent/scripts/build_active_learning_dataset.py`
- `protein_agent/scripts/retrain_active_learning_surrogate.py`
- `protein_agent/scripts/promote_surrogate_model.py`
- `protein_agent/scripts/prepare_retrospective_active_learning_split.py`
- `protein_agent/scripts/export_retrospective_oracle_batch.py`
- `protein_agent/scripts/simulate_wetlab_from_oracle.py`

## 3. 推荐目录结构

```text
data/
  active_learning/
    runs/
    batches/
    wetlab/
    datasets/
    retrospective/
    active_model.json
models/
  gfp_surrogate/
    xgb_ensemble_v1_randomsplit/
    xgb_ensemble_active_v001/
    xgb_ensemble_active_v002/
```

## 4. 先记住两条规则

### 规则 A：先做可回放闭环，再接真实湿实验

如果你还没有真实湿实验，最稳的办法不是自由生成新序列，而是：

- 用公共 GFP 数据切出 `initial_base`
- 再切出隐藏的 `oracle_pool`
- 用 `oracle_pool` 回放一轮主动学习

这样验证的是：

- 批次导出是否正确
- acquisition 是否可用
- wet-lab 导入是否正确
- 重训和模型晋升是否闭环

### 规则 B：先不要在这个阶段上复杂 BO

当前阶段不要先做：

- BoTorch
- Bayesian optimization 框架
- 数据库迁移
- 分布式重训
- 自动实验调度

MVP 只需要：

- 文件系统持久化
- 版本化模型目录
- 明确的人控 promotion

## 5. 路线 A：没有真实湿实验，先做 retrospective 回放

### Step 1. 切出 `initial_base` 和 `oracle_pool`

```bash
python protein_agent/scripts/prepare_retrospective_active_learning_split.py \
  --input-dataset data/gfp/processed/cleaned.parquet \
  --split-column split_mutation_count \
  --initial-splits train,valid \
  --oracle-splits test
```

检查：

```bash
cat data/active_learning/retrospective/split_summary.json
ls data/active_learning/retrospective
```

### Step 2. 用 `initial_base` 训练 retrospective baseline

```bash
python protein_agent/scripts/train_gfp_surrogate.py \
  --input data/active_learning/retrospective/initial_base.parquet \
  --output-dir models/gfp_surrogate/xgb_ensemble_active_seed_v001 \
  --reference-fasta data/gfp/raw/avGFP_reference_mature.fa \
  --chromophore-start 63 \
  --chromophore-motif SYG \
  --split-column split_random \
  --model-type xgboost \
  --ensemble-size 5 \
  --feature-backend hybrid \
  --embedding-cache data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz
```

### Step 3. 直接从 `oracle_pool` 导出第一轮 top-k

```bash
python protein_agent/scripts/export_retrospective_oracle_batch.py \
  --oracle-dataset data/active_learning/retrospective/oracle_pool.parquet \
  --model-dir models/gfp_surrogate/xgb_ensemble_active_seed_v001 \
  --top-k 24 \
  --acquisition-lambda 0.5 \
  --min-hamming 5 \
  --batch-id gfp_round_001
```

这里的默认思路是：

- exploit：高预测值
- explore：高 `prediction_std`
- diversify：`min-hamming 5`

### Step 4. 用 oracle 模拟 wet-lab

```bash
python protein_agent/scripts/simulate_wetlab_from_oracle.py \
  --batch-csv data/active_learning/batches/gfp_round_001.csv \
  --oracle-dataset data/active_learning/retrospective/oracle_pool.parquet \
  --label-column log_fluorescence \
  --assay-name retrospective_public_oracle \
  --operator simulator \
  --noise-std 0.0
```

### Step 5. 导入 wet-lab 结果

```bash
python protein_agent/scripts/import_wetlab_results.py \
  --input data/active_learning/wetlab/gfp_round_001_simulated.csv
```

### Step 6. 构建 round 1 合并训练集

```bash
python protein_agent/scripts/build_active_learning_dataset.py \
  --base-dataset data/active_learning/retrospective/initial_base.parquet \
  --reference-fasta data/gfp/raw/avGFP_reference_mature.fa \
  --wetlab-file data/active_learning/wetlab/gfp_round_001.jsonl \
  --output data/active_learning/datasets/gfp_active_learning_round1.parquet
```

### Step 7. 重训 round 1 active-learning surrogate

```bash
python protein_agent/scripts/retrain_active_learning_surrogate.py \
  --input-dataset data/active_learning/datasets/gfp_active_learning_round1.parquet \
  --reference-fasta data/gfp/raw/avGFP_reference_mature.fa \
  --embedding-cache data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz \
  --feature-backend hybrid \
  --split-column split_random \
  --model-root models/gfp_surrogate
```

通常会生成：

```text
models/gfp_surrogate/xgb_ensemble_active_v001
```

### Step 8. 提升模型并验证

```bash
python protein_agent/scripts/promote_surrogate_model.py \
  --model-dir models/gfp_surrogate/xgb_ensemble_active_v001 \
  --env-file .env
```

然后：

```bash
./stop_all.sh
./start_all.sh
```

最小验证：

```bash
curl -X POST http://127.0.0.1:8000/design_protein \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Design an improved GFP and iteratively optimize it",
    "sequence": "KGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK",
    "max_iterations": 1,
    "candidates_per_round": 2,
    "patience": 1
  }'
```

确认：

- `scoring.backend = hybrid`
- `best_candidate.metadata.surrogate_available = true`
- `best_candidate.metadata.model_version = xgb_ensemble_active_v001`

## 6. 路线 B：有真实湿实验时怎么替换

真实 wet-lab 接入时，只替换两步：

1. 不再运行 `simulate_wetlab_from_oracle.py`
2. 直接把实验室返回的 CSV 喂给 `import_wetlab_results.py`

其余流程不变：

1. 导出 batch
2. 导入实验标签
3. 构建 merged dataset
4. 重训 surrogate
5. promotion
6. 下一轮继续使用新模型

## 7. 从在线 design run 直接导出 batch 的最短路径

如果你已经在跑线上 `/design_protein`，响应里会包含 `run_artifact_path`。

然后直接：

```bash
python protein_agent/scripts/export_active_learning_batch.py \
  --run-json data/active_learning/runs/<your_run>.json \
  --top-k 24 \
  --acquisition-lambda 0.5 \
  --min-hamming 5
```

这条路径适合“在线设计已经能稳定产出候选”的场景。

## 8. MVP 验收标准

只要下面这些事能全部完成，Phase 3 MVP 就算跑通：

1. 能把 run 结果落盘到 `data/active_learning/runs/`
2. 能导出 batch CSV
3. 能导入 mock 或真实 wet-lab 结果
4. 能构建新的 active-learning dataset
5. 能训练出新的版本化模型目录
6. 能用脚本提升当前 active model
7. 能在下一轮 API 结果里看到新的 `model_version`

## 9. 这份文档合并了哪些旧文件

以下历史文档已被本指南吸收，不建议继续单独维护：

- `PHASE3_ACTIVE_LEARNING_MVP.md`
- `PHASE3_STEP_BY_STEP_TUTORIAL.md`
- `PHASE3_RETROSPECTIVE_ROUND1_COMMANDS.md`
