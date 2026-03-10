# Phase 2 Post-Run Checklist

适用场景：

- `run_gfp_surrogate_pipeline.py` 已经完整跑完
- 你想确认 Phase 2 产物是否齐全
- 你想定位“流程成功但模型质量可能不对”的问题


## 1. 这次跑成功后，关键目录在哪

### 1.1 模型产物目录

这次的模型产物目录是：

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1
```

### 1.2 训练输出目录

当前这套实现里，训练输出目录和模型产物目录是同一个目录：

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1
```

训练脚本会直接把模型文件和训练报告一起写到这个目录里。

### 1.3 embedding 产物目录

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/embeddings/esm3_mean_v1
```

### 1.4 清洗后的数据目录

```text
/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/processed
```


## 2. 模型目录里应该有什么

先检查：

```bash
ls -la /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1
```

预期至少有这些文件：

- `model_0.joblib`
- `model_1.joblib`
- `model_2.joblib`
- `model_3.joblib`
- `model_4.joblib`
- `feature_config.json`
- `metadata.json`
- `training_report.json`


## 3. embedding 目录里应该有什么

检查：

```bash
ls -la /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/embeddings/esm3_mean_v1
ls -la /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/embeddings/esm3_mean_v1/offline_run
```

预期至少有：

- `sequences.fasta`
- `embedding_cache.npz`
- `offline_run/run_summary.json`
- `offline_run/metadata.csv`


## 4. 先确认这次 run 的成功信号

### 4.1 embedding 成功信号

看：

```bash
cat /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json
```

这次你日志里已经看到：

- `processed = 70`
- `failed = 0`
- `snapshot = /mnt/disk3/tio_nekton4/esm3/weights`

这说明 embedding 阶段已经真正跑通。

### 4.2 训练成功信号

这次日志里已经有：

- `Saved surrogate model to /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1`
- `Updated env file: .env`
- `Pipeline complete. Model directory: /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1`

这说明流程层面是成功的。


## 5. 这次 run 里值得警惕的地方

虽然流程成功，但下面这些数值不理想：

```text
rmse = 1.3316
mae = 0.9507
r2 = -0.8178
spearman = nan
pearson = nan
prediction_std_mean = 0.0
```

这通常意味着至少有一种情况成立：

1. 测试集太小或分布异常，导致相关系数不可计算。
2. ensemble 在测试集上几乎输出常数，导致 `prediction_std_mean = 0.0`。
3. 当前数据切分方式让 train/valid/test 过于退化。
4. 特征工程没有有效利用到 GFP 相关信息。


## 6. 立即建议检查的文件

### 6.1 数据清洗摘要

```bash
cat /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/processed/dataset_summary.json
```

这次最可疑的值是：

```text
motif_intact_fraction = 0.0
```

这对 GFP 来说很反常，后续应该重点排查。

### 6.2 训练报告

```bash
cat /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1/training_report.json
```

重点看：

- `train_rows`
- `valid_rows`
- `test_rows`
- `feature_backend`
- `evaluation`
- `training_summary`

### 6.3 模型元数据

```bash
cat /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1/metadata.json
```

重点看：

- `feature_names`
- `feature_backend`
- `split_column`
- `ensemble_size`

### 6.4 特征配置

```bash
cat /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1/feature_config.json
```

重点看：

- `chromophore_start`
- `chromophore_motif`
- `feature_backend`
- `embedding_cache_path`


## 7. 一次性收集这些信息最省事

建议直接执行：

```bash
ls -la /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1
cat /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1/training_report.json
cat /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1/metadata.json
cat /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/processed/dataset_summary.json
```

如果输出太长，至少把这些字段贴回来：

- `train_rows`
- `valid_rows`
- `test_rows`
- `evaluation`
- `feature_backend`
- `motif_intact_fraction`


## 8. 当前结论

当前状态可以概括为：

1. Phase 2 的工程流程已经跑通。
2. embedding 产物已经完整生成。
3. surrogate 模型已经成功保存并写回 `.env`。
4. 下一阶段不再是“修运行失败”，而是“检查模型质量为什么这么差”。


## 9. 本次实际根因

如果你这次拿到的产物里出现了下面两种信号：

- `feature_config.json` 里的 `reference_sequence` 以 `AGCAAGGGCGAG...` 这类核酸序列开头
- `training_report.json` 里是 `train_rows = 1, valid_rows = 61, test_rows = 8`

那么当前模型应视为“不可信但可复现”，原因通常就是这两个：

1. 参考 FASTA 用成了 DNA，而不是蛋白序列。
2. `split_mutation_count` 对当前这份 0-2 突变的小数据集退化得太严重，最终只给训练集留了 1 条 WT。

对这次 GFP 数据，优先建议：

1. 改用真正的 avGFP 氨基酸参考序列重新构建数据集。
2. 训练时优先用 `--split-column split_random`，不要继续用当前的 `split_mutation_count`。
