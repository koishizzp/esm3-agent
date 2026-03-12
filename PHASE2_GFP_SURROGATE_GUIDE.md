# Phase 2 GFP Surrogate Guide

这份文档是当前仓库里 **唯一建议继续保留的 Phase 2 操作指南**。它合并了之前分散的 runbook、rerun、recovery、post-run、closeout 文档，只保留现在仍然有效的稳定结论。

适用场景：

- 你要首次跑通 GFP surrogate Phase 2
- 你之前用错了 GFP reference，想做一次干净重跑
- 你只修正了 chromophore 坐标，想判断 embeddings 能不能复用
- 你要把 Phase 2 结果切到线上，并准备进入 Phase 3

## 1. 当前唯一推荐的 GFP 基线

后续所有数据处理、训练、约束和在线请求，都统一按这套 canonical reference：

- `reference = mature avGFP`
- `reference length = 236`
- `chromophore start = 63`
- `chromophore motif = SYG`
- 第一轮 sanity check 优先使用 `split_random`

不要再混用下面这些旧前提：

- DNA / CDS FASTA
- `238 aa` full-length scaffold
- `chromophore_start = 65`

## 2. 先准备正确的 reference FASTA

推荐文件：

```text
data/gfp/raw/avGFP_reference_mature.fa
```

内容：

```text
>avGFP_mature_236aa
KGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK
```

校验：

```bash
python - <<'PY'
from pathlib import Path
text = Path("data/gfp/raw/avGFP_reference_mature.fa").read_text(encoding="utf-8").splitlines()
seq = "".join(line.strip() for line in text if line.strip() and not line.startswith(">"))
print("length", len(seq))
print("chromophore", seq[62:65])
for pos in [90, 108, 231, 234]:
    print(pos, seq[pos - 1])
PY
```

预期：

- `length 236`
- `chromophore SYG`
- `90 Y`
- `108 A`
- `231 M`
- `234 L`

## 3. Fresh Run：推荐的稳定执行顺序

### Step 1. 清洗数据

```bash
python protein_agent/scripts/prepare_gfp_dataset.py \
  --input data/gfp/raw/amino_acid_genotypes_to_brightness.tsv \
  --reference-fasta data/gfp/raw/avGFP_reference_mature.fa \
  --chromophore-start 63 \
  --chromophore-motif SYG \
  --output-dir data/gfp/processed
```

立刻检查：

```bash
cat data/gfp/processed/dataset_summary.json
```

至少确认：

- `num_rows` 不再退化到几十条
- `motif_intact_fraction` 不再是错误造成的 `0.0`

### Step 2. 提取 embeddings

```bash
python protein_agent/scripts/extract_gfp_embeddings.py \
  --input data/gfp/processed/cleaned.parquet \
  --output-dir data/gfp/embeddings/esm3_mean_v1 \
  --embedding-script ./get_embeddings_offline.py \
  --python <esm_python> \
  --env-file .env \
  --device cuda \
  --pooling mean \
  --format both
```

检查：

```bash
cat data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json
```

至少确认：

- `processed > 0`
- `failed = 0` 或非常低
- 不再出现错误路径 `data/data/weights/...`

### Step 3. 训练第一版基线 surrogate

第一轮优先用 `split_random`，不要急着用更严格的 split。

```bash
python protein_agent/scripts/train_gfp_surrogate.py \
  --input data/gfp/processed/cleaned.parquet \
  --output-dir models/gfp_surrogate/xgb_ensemble_v1_randomsplit \
  --reference-fasta data/gfp/raw/avGFP_reference_mature.fa \
  --chromophore-start 63 \
  --chromophore-motif SYG \
  --split-column split_random \
  --model-type xgboost \
  --ensemble-size 5 \
  --feature-backend hybrid \
  --embedding-cache data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz
```

检查：

```bash
cat models/gfp_surrogate/xgb_ensemble_v1_randomsplit/training_report.json
```

至少确认：

- `train_rows / valid_rows / test_rows` 正常
- 不再出现 `train_rows = 1`
- 不再出现整批 `spearman = nan`、`pearson = nan`、`prediction_std_mean = 0.0`

### Step 4. 切到线上

`.env` 至少对齐这些值：

```bash
PROTEIN_AGENT_SCORING_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_MODEL_PATH=<repo>/models/gfp_surrogate/xgb_ensemble_v1_randomsplit
PROTEIN_AGENT_SURROGATE_MODEL_TYPE=xgboost
PROTEIN_AGENT_SURROGATE_ENSEMBLE_SIZE=5
PROTEIN_AGENT_SURROGATE_FEATURE_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_USE_STRUCTURE_FEATURES=false
PROTEIN_AGENT_REQUIRE_GFP_CHROMOPHORE=true
PROTEIN_AGENT_GFP_REFERENCE_LENGTH=236
PROTEIN_AGENT_GFP_CHROMOPHORE_START=63
PROTEIN_AGENT_GFP_CHROMOPHORE_MOTIF=SYG
```

然后：

```bash
./stop_all.sh
./start_all.sh
./status_all.sh
```

### Step 5. 做最小 smoke test

注意：在 `protein_agent/gfp.py` 默认 scaffold 还没完全对齐前，GFP 请求里继续显式传 mature avGFP `sequence`。

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

返回里重点确认：

- `scoring.backend = hybrid`
- `best_candidate.metadata.score_mode = hybrid`
- `best_candidate.metadata.surrogate_available = true`
- `best_candidate.metadata.model_version` 指向当前模型目录

## 4. 可选：一条命令跑完整条 pipeline

如果你已经确认 reference、chromophore 和 `.env` 都正确，也可以直接用包装脚本：

```bash
python protein_agent/scripts/run_gfp_surrogate_pipeline.py \
  --raw-input data/gfp/raw/amino_acid_genotypes_to_brightness.tsv \
  --reference-fasta data/gfp/raw/avGFP_reference_mature.fa \
  --workspace-dir . \
  --embedding-script ./get_embeddings_offline.py \
  --esm-python <esm_python> \
  --env-file .env \
  --device cuda \
  --pooling mean \
  --model-name xgb_ensemble_v1_randomsplit \
  --split-column split_random \
  --chromophore-start 63 \
  --chromophore-motif SYG \
  --ensemble-size 5
```

这适合“已经知道所有前提都对”的场景；第一次排障时仍建议按第 3 节分步执行。

## 5. 三类常见重跑场景怎么处理

### 场景 A：之前用了 DNA FASTA 或 238 aa full-length reference

处理原则：

- `processed` 重新做
- `embeddings` 重新做
- `model` 重新做

建议先清掉这些产物，避免混用：

```bash
rm -rf data/gfp/processed
rm -rf data/gfp/embeddings/esm3_mean_v1
rm -rf models/gfp_surrogate/xgb_ensemble_v1
rm -rf models/gfp_surrogate/xgb_ensemble_v1_randomsplit
```

典型异常信号：

- `num_rows = 70`
- `motif_intact_fraction = 0.0`
- `train_rows = 1`

### 场景 B：reference 已经对了，但 chromophore 坐标曾经错写成 65

处理原则：

- `prepare_gfp_dataset.py` 重新跑
- `train_gfp_surrogate.py` 必须重跑
- `embeddings` 通常可以复用，但前提是 cleaned `sequence` 集合没有变化

推荐做法：

- 新模型训到新目录
- 旧模型先软废弃，不要立刻物理删除

示例：

```text
models/gfp_surrogate/xgb_ensemble_v2_mature63_randomsplit
```

### 场景 C：当前只卡在 embedding，报 `data/data/weights/...`

处理原则：

- 不要从头重跑 dataset
- 修好 `.env` 传递和 embedding 脚本路径后，从 `extract_gfp_embeddings.py` 继续

先检查：

```bash
grep -E "PROTEIN_AGENT_ESM3_ROOT|PROTEIN_AGENT_ESM3_WEIGHTS_DIR|PROTEIN_AGENT_ESM3_DATA_DIR|PROTEIN_AGENT_ESM3_MODEL_NAME|PROTEIN_AGENT_ESM3_DEVICE" .env
```

如果这些值没问题，就单独重跑 Step 2，而不是整条 pipeline。

## 6. Closeout：进入 Phase 3 之前必须满足什么

只有以下几件事都成立，Phase 2 才算正式结束：

1. 数据摘要、embedding 摘要、训练报告都正常。
2. `.env` 已指向正确模型和 mature avGFP 约束。
3. 服务重启后，在线请求实际返回的是 `hybrid`，不是 `structure_fallback`。
4. 你已经决定：
   - 要么继续在请求里显式传 mature avGFP `sequence`
   - 要么先把代码默认 scaffold 彻底改成 mature avGFP

建议至少保留这些产物：

- `data/gfp/raw/amino_acid_genotypes_to_brightness.tsv`
- `data/gfp/raw/avGFP_reference_mature.fa`
- `data/gfp/processed/dataset_summary.json`
- `data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json`
- `models/gfp_surrogate/<active_model_dir>/`

## 7. 这份文档合并了哪些旧文件

以下历史文档已被本指南吸收，不建议继续单独维护：

- `GFP_SURROGATE_PHASE2_RUNBOOK.md`
- `GFP_SURROGATE_PHASE2_RECOVERY.md`
- `PHASE2_RERUN_WITH_PROTEIN_REFERENCE.md`
- `PHASE2_RERUN_WITH_MATURE_AVGFP.md`
- `PHASE2_RERUN_AFTER_CHROMOPHORE_FIX.md`
- `PHASE2_POSTRUN_CHECKLIST.md`
- `PHASE2_CLOSEOUT_REMINDERS.md`
- `PHASE2_CLOSEOUT_FOR_PHASE3.md`
