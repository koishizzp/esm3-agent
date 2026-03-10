# Phase 2 Rerun With Protein Reference

适用场景：

- 你已经确认 `amino_acid_genotypes_to_brightness.tsv` 是完整的
- 但这次 Phase 2 用错了参考 FASTA
- 你想用同一份 Sarkisyan 数据重新跑一遍


## 1. 先说结论

不用换数据集。

你现在的问题不是 `amino_acid_genotypes_to_brightness.tsv` 不对，而是：

1. 这份表是氨基酸突变表。
2. 你传给 pipeline 的 `avGFP_reference_sequence.fa` 是 DNA/CDS 序列，不是蛋白序列。
3. 脚本拿 DNA 参考序列去解释 amino-acid mutation token，导致绝大多数样本在清洗阶段被丢弃。


## 2. 为什么会只剩 70 条

你下载回来的原始表是完整的，按本地检查有：

```text
54026 lines
```

而清洗后只有：

```text
num_rows = 70
```

这不是因为原始数据太少，而是因为：

- `aaMutations` 里的 token 是类似 `SA108D`、`SY90N` 这样的氨基酸突变
- 但你给的参考 FASTA 以 `AGCAAGGGCGAG...` 开头，是核酸序列
- 清洗逻辑会把突变 token 里的参考残基和参考序列当前位置做匹配
- 用 DNA 去匹配 amino-acid token 时，只有极少数“碰巧是 A/C/G/T 的位置”会误打误撞通过

所以结果就变成：

1. 5 万多条原始记录只剩 70 条
2. `motif_intact_fraction = 0.0`
3. 后续训练集只剩 1 条 WT


## 3. 当前模型为什么这么差

不是 XGBoost 本身有问题，而是训练输入已经坏了。

这次训练报告里的关键信号是：

```text
train_rows = 1
valid_rows = 61
test_rows = 8
prediction_std_mean = 0.0
spearman = nan
pearson = nan
```

这说明：

1. 当前模型几乎只在 1 条训练样本上拟合。
2. ensemble 输出退化成近似常数。
3. 当前这批模型产物不应继续使用。


## 4. 正确做法

还是用这份 Sarkisyan 数据：

- `amino_acid_genotypes_to_brightness.tsv`

但参考序列要换成 avGFP 的蛋白序列，而不是 DNA/CDS FASTA。


## 5. 在服务器上新建正确的蛋白参考 FASTA

进入项目目录：

```bash
cd /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent
```

创建一个新的蛋白参考文件：

```bash
cat > data/gfp/raw/avGFP_reference_protein.fa <<'EOF'
>avGFP_protein
MSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK
EOF
```

然后确认长度是 238 aa：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python - <<'PY'
from pathlib import Path
text = Path("data/gfp/raw/avGFP_reference_protein.fa").read_text().splitlines()
seq = "".join(line.strip() for line in text if line.strip() and not line.startswith(">"))
print(len(seq))
print(seq[64:67])
PY
```

预期输出：

- 长度 `238`
- 色团位点 `SYG`


## 6. 先删除这次错误 run 的产物

只删 GFP surrogate 这次 run 相关目录：

```bash
rm -rf data/gfp/processed
rm -rf data/gfp/embeddings/esm3_mean_v1
rm -rf models/gfp_surrogate/xgb_ensemble_v1
```

如果你不想删，也至少换一个新的输出目录名，但第一次建议直接清掉，避免混用旧产物。


## 7. 先做一次求稳重跑

这次建议先不要继续用 `split_mutation_count` 做第一轮 sanity check。

先分三步跑：

### Step 1. 重新清洗数据

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  protein_agent/scripts/prepare_gfp_dataset.py \
  --input data/gfp/raw/amino_acid_genotypes_to_brightness.tsv \
  --reference-fasta data/gfp/raw/avGFP_reference_protein.fa \
  --output-dir data/gfp/processed
```

跑完立刻检查：

```bash
cat data/gfp/processed/dataset_summary.json
```

这次预期不应该再是：

- `num_rows = 70`
- `motif_intact_fraction = 0.0`


### Step 2. 重新提 embedding

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  protein_agent/scripts/extract_gfp_embeddings.py \
  --input data/gfp/processed/cleaned.parquet \
  --output-dir data/gfp/embeddings/esm3_mean_v1 \
  --embedding-script ./get_embeddings_offline.py \
  --python /mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  --env-file .env \
  --device cuda \
  --pooling mean \
  --format both
```


### Step 3. 先用 `split_random` 训练一版基线模型

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  protein_agent/scripts/train_gfp_surrogate.py \
  --input data/gfp/processed/cleaned.parquet \
  --output-dir models/gfp_surrogate/xgb_ensemble_v1_randomsplit \
  --reference-fasta data/gfp/raw/avGFP_reference_protein.fa \
  --split-column split_random \
  --model-type xgboost \
  --ensemble-size 5 \
  --feature-backend hybrid \
  --embedding-cache data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz
```


## 8. 为什么先用 `split_random`

因为你这次坏掉的一个直接原因是：

- `split_mutation_count` 在错误清洗后的 70 条数据上退化成了 `train = 1`

对于重新修正后的完整数据集，`split_mutation_count` 可能仍然可用，但第一轮最稳的是先用：

```text
split_random
```

先确认：

1. 数据清洗行数正常
2. embedding 正常
3. 训练集规模正常
4. 指标不再退化成常数预测

然后再考虑是否切回 `split_mutation_count` 做更严格外推评估。


## 9. 重跑后最重要的三个检查

### 9.1 数据摘要

```bash
cat data/gfp/processed/dataset_summary.json
```

### 9.2 embedding 摘要

```bash
cat data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json
```

### 9.3 训练报告

```bash
cat models/gfp_surrogate/xgb_ensemble_v1_randomsplit/training_report.json
```

重点看：

- `num_rows`
- `motif_intact_fraction`
- `train_rows`
- `valid_rows`
- `test_rows`
- `evaluation`


## 10. 当前建议

当前不建议换数据集来源。

更合理的做法是：

1. 保留 `amino_acid_genotypes_to_brightness.tsv`
2. 把参考 FASTA 改成蛋白序列
3. 重建 processed / embeddings / model
4. 第一轮先用 `split_random`

等这轮基线结果正常后，再决定是否需要改模型、改特征，或者回到 `split_mutation_count`。
