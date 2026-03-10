# Phase 2 Rerun With Mature avGFP

Use this when:

- `amino_acid_genotypes_to_brightness.tsv` is the Sarkisyan amino-acid mutation table
- the previous run used a DNA FASTA, or used a 238 aa full-length GFP reference that did not match mutation indexing
- you want a clean rerun with the more consistent 236 aa mature avGFP reference


## Why this rerun is needed

For the Sarkisyan `aaMutations` table, mutation tokens such as:

- `SY90N`
- `SA108D`
- `SM231T`
- `SL234P`

match a mature avGFP-style amino-acid reference better than the 238 aa full-length scaffold.

The practical consequence is:

- the reference length should be `236`
- the chromophore motif `SYG` should start at position `63`


## Correct reference FASTA

Create this file on the server:

```bash
cat > data/gfp/raw/avGFP_reference_mature.fa <<'EOF'
>avGFP_mature_236aa
KGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK
EOF
```

Verify it:

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python - <<'PY'
from pathlib import Path
text = Path("data/gfp/raw/avGFP_reference_mature.fa").read_text().splitlines()
seq = "".join(line.strip() for line in text if line.strip() and not line.startswith(">"))
print("length", len(seq))
print("chromophore", seq[62:65])
for pos in [90, 108, 231, 234]:
    print(pos, seq[pos - 1])
PY
```

Expected output:

- `length 236`
- `chromophore SYG`
- `90 Y`
- `108 A`
- `231 M`
- `234 L`


## Delete stale artifacts

These outputs were built from the wrong reference path:

```bash
rm -rf data/gfp/processed
rm -rf data/gfp/embeddings/esm3_mean_v1
rm -rf models/gfp_surrogate/xgb_ensemble_v1
rm -rf models/gfp_surrogate/xgb_ensemble_v1_randomsplit
```


## Step 1: rebuild processed data

```bash
PYTHONPATH=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent \
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  protein_agent/scripts/prepare_gfp_dataset.py \
  --input data/gfp/raw/amino_acid_genotypes_to_brightness.tsv \
  --reference-fasta data/gfp/raw/avGFP_reference_mature.fa \
  --chromophore-start 63 \
  --output-dir data/gfp/processed
```

Check:

```bash
cat data/gfp/processed/dataset_summary.json
```

What you want to see:

- row count far above `173`
- `motif_intact_fraction` not degenerate for the wrong reason


## Step 2: rebuild embeddings

Make sure the latest versions of these files are on the server first:

- `get_embeddings_offline.py`
- `protein_agent/scripts/extract_gfp_embeddings.py`
- `protein_agent/scripts/train_gfp_surrogate.py`

Then run:

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

Check:

```bash
cat data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json
ls data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz
```


## Step 3: train a baseline hybrid model with random split

Use `split_random` first. This is the safest sanity-check pass.

```bash
PYTHONPATH=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent \
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python \
  /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/protein_agent/scripts/train_gfp_surrogate.py \
  --input /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/processed/cleaned.parquet \
  --output-dir /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1_randomsplit \
  --reference-fasta /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/raw/avGFP_reference_mature.fa \
  --chromophore-start 63 \
  --split-column split_random \
  --model-type xgboost \
  --ensemble-size 5 \
  --feature-backend hybrid \
  --embedding-cache /mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/data/gfp/embeddings/esm3_mean_v1/embedding_cache.npz
```

Check:

```bash
cat models/gfp_surrogate/xgb_ensemble_v1_randomsplit/training_report.json
```


## Step 4: only after that, consider mutation-count split

Do not use `split_mutation_count` until:

- processed row count looks reasonable
- embedding completed successfully
- random-split metrics look sane


## Files to send back for review

If you want a follow-up review, paste these outputs:

```bash
cat data/gfp/processed/dataset_summary.json
cat data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json
cat models/gfp_surrogate/xgb_ensemble_v1_randomsplit/training_report.json
```
