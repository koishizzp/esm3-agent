# Phase 3 Active Learning MVP

This document is the shortest practical path from your current working Phase 2 surrogate to a real active-learning loop.

Current baseline assumption:

- surrogate model is usable:
  `/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1_randomsplit`
- scoring mode is switched to `hybrid`
- GFP coordinates are aligned to mature avGFP:
  - reference length `236`
  - chromophore start `63`
  - motif `SYG`


## 1. MVP goal

The MVP loop is:

1. Agent proposes GFP variants
2. Online system scores and ranks them
3. You export top candidates for wet-lab testing
4. Wet-lab results are imported back into the project
5. A new surrogate version is retrained
6. The active model version is promoted
7. The next round uses the updated surrogate

That is enough to count as a real Phase 3 start.


## 2. What not to build yet

Do not start with:

- BoTorch
- Bayesian optimization libraries
- database migrations
- distributed retraining
- automatic experiment scheduling
- complicated uncertainty calibration

For MVP, keep it simple:

- filesystem persistence
- CSV/JSON import
- versioned model directories
- explicit human-controlled promotion


## 3. Minimum deliverables

You need only 4 new capabilities:

### 3.1 Persist experiment memory

Current status:

- `ExperimentMemory` exists
- but it is in-memory only

MVP requirement:

- save every design run to disk
- load previous runs back when needed

### 3.2 Import wet-lab results

MVP requirement:

- accept a simple CSV or JSONL file
- map sequence -> measured fluorescence label
- keep metadata such as batch id / assay date / notes

### 3.3 Retrain a new surrogate version

MVP requirement:

- merge the original training dataset with imported wet-lab labels
- write a new model version directory
- keep training report and metadata

### 3.4 Promote the new model version

MVP requirement:

- update the active surrogate path
- restart service
- record which model version is active


## 4. Recommended implementation order

Do these in order.

### Step 1. Persist design memory to disk

Target files:

- `protein_agent/memory/experiment_memory.py`
- new: `protein_agent/memory/storage.py`

What to add:

- `save_json(path)`
- `load_json(path)`
- stable record schema
- run-level metadata:
  - task
  - timestamp
  - scoring backend
  - surrogate model version
  - GFP reference settings

Recommended storage path:

```text
data/active_learning/runs/
```

Recommended file naming:

```text
data/active_learning/runs/20260310_153000_gfp_design.json
```


### Step 2. Export top-k candidates for wet-lab

Target files:

- new: `protein_agent/scripts/export_active_learning_batch.py`

Input:

- saved run JSON

Output:

- CSV for wet-lab handoff

Recommended output path:

```text
data/active_learning/batches/
```

Recommended columns:

- `batch_id`
- `sequence`
- `score`
- `surrogate_score`
- `prediction_std`
- `structure_score`
- `model_version`
- `iteration`
- `selected_rank`
- `notes`


### Step 3. Import wet-lab results

Target files:

- new: `protein_agent/scripts/import_wetlab_results.py`

Input:

- a CSV filled by wet-lab

Recommended input columns:

- `batch_id`
- `sequence`
- `measured_log_fluorescence`
- `raw_brightness`
- `label_std`
- `assay_name`
- `assay_date`
- `operator`
- `notes`

Output:

- normalized results file under:

```text
data/active_learning/wetlab/
```

Recommended normalized file:

```text
data/active_learning/wetlab/<batch_id>.jsonl
```


### Step 4. Build a retraining dataset

Target files:

- new: `protein_agent/scripts/build_active_learning_dataset.py`

Input:

- base processed dataset:
  `data/gfp/processed/cleaned.parquet`
- imported wet-lab labels
- mature avGFP reference FASTA

Output:

- merged training dataset:

```text
data/active_learning/datasets/gfp_active_learning_v001.parquet
```

Rules:

- deduplicate by `sequence`
- keep the newest wet-lab label when conflicts exist
- preserve source columns:
  - `source = base_public` or `source = wetlab`
  - `batch_id`
  - `assay_date`
- preserve `sample_weight`
- preserve `label_std`


### Step 5. Retrain a new surrogate version

Target files:

- new: `protein_agent/scripts/retrain_active_learning_surrogate.py`

This script should call the same training machinery as:

- `protein_agent/scripts/train_gfp_surrogate.py`

Recommended new model version directory:

```text
models/gfp_surrogate/xgb_ensemble_active_v001
```

Then:

- `xgb_ensemble_active_v002`
- `xgb_ensemble_active_v003`

Do not overwrite old model directories.


### Step 6. Promote one model version

Target files:

- new: `protein_agent/scripts/promote_surrogate_model.py`

MVP behavior:

- update `.env`
- set `PROTEIN_AGENT_SURROGATE_MODEL_PATH`
- optionally set `PROTEIN_AGENT_SURROGATE_ENSEMBLE_SIZE`
- keep scoring backend at `hybrid`

Optional:

- write `data/active_learning/active_model.json`


## 5. Recommended directory layout

Add this structure:

```text
data/
  active_learning/
    runs/
    batches/
    wetlab/
    datasets/
    active_model.json
models/
  gfp_surrogate/
    xgb_ensemble_v1_randomsplit/
    xgb_ensemble_active_v001/
    xgb_ensemble_active_v002/
```


## 6. Recommended file schema

### 6.1 Saved run JSON

Top-level fields:

- `task`
- `created_at`
- `scoring`
- `best`
- `records`
- `generation_stats`
- `seed_sequence`
- `reference_length`
- `chromophore_start`
- `chromophore_motif`

Each record should keep at least:

- `sequence`
- `score`
- `iteration`
- `metadata.score_mode`
- `metadata.model_version`
- `metadata.predicted_fluorescence`
- `metadata.prediction_std`
- `metadata.surrogate_score`
- `metadata.mean_plddt`
- `metadata.ptm`
- `metadata.valid_candidate`


### 6.2 Wet-lab normalized JSONL

Each line:

```json
{
  "batch_id": "gfp_round_001",
  "sequence": "KGEELF...",
  "measured_log_fluorescence": 3.42,
  "label_std": 0.08,
  "source": "wetlab",
  "assay_date": "2026-03-10",
  "notes": ""
}
```


## 7. MVP acquisition rule

Do not overcomplicate acquisition yet.

For MVP, use:

```text
acquisition_score = predicted_fluorescence + lambda * prediction_std
```

Recommended starting value:

```text
lambda = 0.5
```

You already have `prediction_std` from the ensemble.

Use acquisition only when selecting candidates for wet-lab export.

Do not change the online design score formula yet.


## 8. Recommended first implementation milestone

The fastest useful milestone is:

1. save every design run to `data/active_learning/runs/`
2. export top-k candidates to CSV
3. import a mock wet-lab CSV back in
4. retrain `xgb_ensemble_active_v001`
5. promote that model path in `.env`

If those 5 steps work, Phase 3 MVP exists.


## 9. Concrete acceptance criteria

Phase 3 MVP is done when you can:

1. run `/design_protein`
2. save the full run to disk
3. export top candidates to a wet-lab batch file
4. import wet-lab labels from a CSV
5. build a merged retraining dataset
6. train a new surrogate version directory
7. update `.env` to point to the new model
8. restart service and verify the new `model_version` is online


## 10. Best next coding tasks

If you want the most efficient implementation sequence, do exactly this:

1. Add disk persistence to `ExperimentMemory`
2. Add `export_active_learning_batch.py`
3. Add `import_wetlab_results.py`
4. Add `build_active_learning_dataset.py`
5. Add `retrain_active_learning_surrogate.py`
6. Add `promote_surrogate_model.py`


## 11. Recommendation for your current state

Given your current progress, the best immediate next task is:

**Implement Step 1 and Step 2 first**

Reason:

- they do not depend on wet-lab yet
- they stabilize the interface between design and experiment
- they give you artifacts you can inspect before writing retraining logic

Only after that should you implement wet-lab import and retraining.
