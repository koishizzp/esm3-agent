# Phase 2 Closeout For Phase 3

Use this after you have a good surrogate model and want to move into the active-learning loop.

This guide assumes you want to use:

- model directory:
  `/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1_randomsplit`
- mature avGFP reference:
  `236 aa`
- chromophore:
  `SYG` at positions `63-65`


## 1. What counts as "Phase 2 complete"

You can treat Phase 2 as complete if all of these are true:

- `data/gfp/processed/dataset_summary.json` looks sane
- `data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json` shows all sequences embedded successfully
- `models/gfp_surrogate/xgb_ensemble_v1_randomsplit/training_report.json` shows sane metrics
- the model directory contains:
  - `model_0.joblib` ... `model_4.joblib`
  - `feature_config.json`
  - `metadata.json`
  - `training_report.json`


## 2. Recommended outputs to keep

Keep these:

- `data/gfp/raw/amino_acid_genotypes_to_brightness.tsv`
- `data/gfp/raw/avGFP_reference_mature.fa`
- `data/gfp/processed/dataset_summary.json`
- `data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json`
- `models/gfp_surrogate/xgb_ensemble_v1_randomsplit/`

You do not need to keep earlier wrong runs based on:

- DNA reference FASTA
- the earlier mismatched 238 aa full-length reference


## 3. Update `.env` to the model you want online

Edit `.env` and make sure these are set:

```bash
PROTEIN_AGENT_SCORING_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_MODEL_PATH=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1_randomsplit
PROTEIN_AGENT_SURROGATE_MODEL_TYPE=xgboost
PROTEIN_AGENT_SURROGATE_ENSEMBLE_SIZE=5
PROTEIN_AGENT_SURROGATE_FEATURE_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_USE_STRUCTURE_FEATURES=false

PROTEIN_AGENT_REQUIRE_GFP_CHROMOPHORE=true
PROTEIN_AGENT_GFP_REFERENCE_LENGTH=236
PROTEIN_AGENT_GFP_CHROMOPHORE_START=63
PROTEIN_AGENT_GFP_CHROMOPHORE_MOTIF=SYG
```

Verify:

```bash
grep -E "PROTEIN_AGENT_SCORING_BACKEND|PROTEIN_AGENT_SURROGATE_|PROTEIN_AGENT_GFP_REFERENCE_LENGTH|PROTEIN_AGENT_GFP_CHROMOPHORE_START|PROTEIN_AGENT_GFP_CHROMOPHORE_MOTIF" .env
```


## 4. Important caution before Phase 3

The current codebase still has a likely mismatch in default GFP seed behavior:

- the online workflow default seed comes from `protein_agent/gfp.py`
- that default scaffold may still be the older full-length GFP sequence
- your trained surrogate is based on mature avGFP (`236 aa`, chromophore start `63`)

That means:

- if you start the GFP workflow without explicitly passing a `sequence`, the optimizer may seed from the wrong scaffold
- scoring and surrogate prediction will then be inconsistent with the design seed


## 5. Fastest safe rule before you patch defaults

Until you explicitly align the code defaults, always pass the mature avGFP seed sequence in your Phase 3 requests.

Use this mature avGFP sequence:

```text
KGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK
```

If you omit `sequence`, do not assume the workflow will automatically use the mature version.


## 6. Restart services after `.env` change

If you use the bundled scripts:

```bash
./stop_all.sh
./start_all.sh
```

Or restart the ESM3 server and Agent API separately if that is how you operate.

Then verify:

```bash
./status_all.sh
```


## 7. Minimal online smoke test

Before starting Phase 3, do one online smoke test against `/design_protein`.

Example:

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

What you want to confirm in the response:

- the request succeeds
- `scoring.backend` is `hybrid`
- best-candidate metadata shows:
  - `score_mode = hybrid`
  - `surrogate_available = true`
  - `model_version = xgb_ensemble_v1_randomsplit`


## 8. What still belongs to Phase 2, even though the model is done

These are the real closeout checks:

1. The model path in `.env` points to the correct model version.
2. The GFP constraint settings in `.env` match the mature avGFP coordinates.
3. The online API can actually load the surrogate model.
4. A live `/design_protein` call returns `hybrid` scoring instead of structure fallback.
5. You have decided whether to:
   - keep passing explicit `sequence` in requests, or
   - patch code defaults to mature avGFP later


## 9. What is not finished yet for Phase 3

The current codebase already has:

- iterative optimizer loop
- in-memory `ExperimentMemory`
- surrogate prediction
- `prediction_std`
- hybrid scoring

But it does not yet fully have:

- persistent experiment memory on disk/db
- wet-lab result import
- automatic surrogate retraining
- model version promotion workflow
- uncertainty-aware acquisition logic

So the next step should be a Phase 3 MVP, not a full active-learning platform.


## 10. Recommended boundary between Phase 2 and Phase 3

Treat Phase 2 as closed only after:

1. `.env` is updated
2. services are restarted
3. online smoke test passes

Once those 3 are done, you can move to Phase 3 MVP implementation.


## 11. Suggested next task after this tutorial

After completing this checklist, the next concrete implementation target should be:

1. persist experiment memory
2. import wet-lab labels
3. retrain surrogate to a new versioned directory
4. switch the active model version

That is the smallest useful active-learning loop.
