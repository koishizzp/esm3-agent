# GFP Surrogate Phase 2 恢复操作手册

适用场景：

- `prepare_gfp_dataset.py` 已经跑完
- 当前卡在 `extract_gfp_embeddings.py` / `get_embeddings_offline.py`
- 报错核心特征是：

```text
FileNotFoundError: [Errno 2] No such file or directory: 'data/data/weights/esm3_sm_open_v1.pth'
```

这不是 GFP 数据本身的问题，核心是 Phase 2 的 embedding 子进程没有稳定拿到 `.env` 里的 ESM3 路径，导致 ESM3 loader 把目录解析错了。


## 1. 本次要同步到服务器的文件

只同步这 3 个文件：

- `get_embeddings_offline.py`
- `protein_agent/scripts/extract_gfp_embeddings.py`
- `protein_agent/scripts/run_gfp_surrogate_pipeline.py`

不要顺手覆盖别的脏文件，尤其是和这次问题无关的改动。


## 2. 这次修复的目的

修复后应满足两件事：

1. `--env-file .env` 不再只是“最后回写 `.env`”，而是会真正传递给 embedding 相关子进程。
2. `get_embeddings_offline.py` 在 fallback 加载 ESM3 时，不再把路径错误拼成 `data/data/weights/...`。


## 3. 服务器上的前置检查

先进入项目目录：

```bash
cd /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent
```

确认 `.env` 里至少有这几项：

```bash
grep -E "PROTEIN_AGENT_ESM3_ROOT|PROTEIN_AGENT_ESM3_WEIGHTS_DIR|PROTEIN_AGENT_ESM3_DATA_DIR|PROTEIN_AGENT_ESM3_MODEL_NAME|PROTEIN_AGENT_ESM3_DEVICE" .env
```

预期类似：

```bash
PROTEIN_AGENT_ESM3_ROOT=/mnt/disk3/tio_nekton4/esm3
PROTEIN_AGENT_ESM3_WEIGHTS_DIR=/mnt/disk3/tio_nekton4/esm3/weights
PROTEIN_AGENT_ESM3_DATA_DIR=/mnt/disk3/tio_nekton4/esm3/data
PROTEIN_AGENT_ESM3_MODEL_NAME=esm3_sm_open_v1
PROTEIN_AGENT_ESM3_DEVICE=cuda
```

再检查关键文件是否真的存在：

```bash
ls /mnt/disk3/tio_nekton4/esm3/weights/esm3_sm_open_v1.pth
ls /mnt/disk3/tio_nekton4/esm3/data
```

如果第一条 `ls` 就失败，先不要继续跑 pipeline，说明你的权重目录本身不完整或路径写错了。


## 4. 先备份服务器上的旧脚本

```bash
mkdir -p tmp/gfp_phase2_backup
cp get_embeddings_offline.py tmp/gfp_phase2_backup/get_embeddings_offline.py.bak
cp protein_agent/scripts/extract_gfp_embeddings.py tmp/gfp_phase2_backup/extract_gfp_embeddings.py.bak
cp protein_agent/scripts/run_gfp_surrogate_pipeline.py tmp/gfp_phase2_backup/run_gfp_surrogate_pipeline.py.bak
```

然后把本地修复后的 3 个文件覆盖到服务器对应位置。


## 5. 不要从头重跑，直接从 embedding 继续

你已经成功产出了：

- `data/gfp/processed/cleaned.parquet`
- `data/gfp/embeddings/esm3_mean_v1/sequences.fasta`

所以现在不要再先跑 `prepare_gfp_dataset.py`。直接从 embedding 恢复。

命令如下：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/protein_agent/scripts/extract_gfp_embeddings.py \
  --input /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/processed/cleaned.parquet \
  --output-dir /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/embeddings/esm3_mean_v1 \
  --embedding-script /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/get_embeddings_offline.py \
  --python /mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  --env-file /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/.env \
  --device cuda \
  --pooling mean \
  --format both
```


## 6. 这一步成功后应检查什么

先看 embedding 目录：

```bash
ls data/gfp/embeddings/esm3_mean_v1
ls data/gfp/embeddings/esm3_mean_v1/offline_run
```

重点看这几个文件：

- `data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz`
- `data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json`
- `data/gfp/embeddings/esm3_mean_v1/offline_run/metadata.csv`

查看 summary：

```bash
cat data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json
```

重点确认：

- `processed` 大于 0
- `failed` 尽量为 0
- `snapshot` 或 `data_root` 不再出现错误的 `data/data/...`


## 7. embedding 成功后继续训练

如果第 5 步成功，训练可以单独继续：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/protein_agent/scripts/train_gfp_surrogate.py \
  --input /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/processed/cleaned.parquet \
  --output-dir /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1 \
  --reference-fasta /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/raw/avGFP_reference_sequence.fa \
  --split-column split_mutation_count \
  --model-type xgboost \
  --ensemble-size 5 \
  --feature-backend hybrid \
  --embedding-cache /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz
```


## 8. 如果你还是想重新走整条 Phase 2 pipeline

前提是上面 3 个修复文件已经同步完成。

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  protein_agent/scripts/run_gfp_surrogate_pipeline.py \
  --raw-input data/gfp/raw/amino_acid_genotypes_to_brightness.tsv \
  --reference-fasta data/gfp/raw/avGFP_reference_sequence.fa \
  --workspace-dir /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent \
  --embedding-script /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/get_embeddings_offline.py \
  --esm-python /mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  --env-file /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/.env \
  --device cuda \
  --pooling mean \
  --model-name xgb_ensemble_v1 \
  --ensemble-size 5
```

但就你当前状态，更推荐先跑第 5 步，把 embedding 单独打通。


## 9. 如果仍然失败，优先回传这些日志

把下面几类信息发回来，不要只发最后一行异常：

```bash
tail -n 80 data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json
```

如果还没生成 `run_summary.json`，则直接重新贴终端输出里这些行：

- `Loading ESM3: ...`
- `snapshot: ...`
- `data: ...`
- `direct_loader_fallback: ...`
- 最后一个 `Traceback`


## 10. 一个额外但次级的问题

你前面 `prepare_gfp_dataset.py` 的输出里有：

```text
'motif_intact_fraction': 0.0
```

这个值可疑，但它不是这次 embedding 失败的主因。

建议顺序是：

1. 先把 embedding 跑通
2. 再单独检查 dataset prep 为何把 GFP 色团位点统计成了全 0

不要把这两个问题混在一起排查。
