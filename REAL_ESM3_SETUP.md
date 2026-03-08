# Real ESM3 setup

This repo now supports three ESM3 backends for the Python `protein_agent` flow.

## Backend modes

- `PROTEIN_AGENT_ESM3_BACKEND=http`
  - Calls an already-running ESM3 HTTP service.
  - Expected endpoints: `/generate_sequence`, `/mutate_sequence`, `/predict_structure`.
- `PROTEIN_AGENT_ESM3_BACKEND=local`
  - Spawns the configured ESM3 Python environment and imports your local deployment directly.
  - Best when you have a checked-out ESM3 repo plus local weights/data.
- `PROTEIN_AGENT_ESM3_BACKEND=auto`
  - Tries HTTP first, then local deployment, then generated-Python fallback if enabled.

## Minimal environment for your deployment layout

Given a deployment like:

```text
esm3/
  weights/
  data/
  esm/
  projects/gfp_reproduction/
```

set:

```bash
export PROTEIN_AGENT_ESM3_BACKEND=local
export PROTEIN_AGENT_ESM3_PYTHON_PATH=/path/to/your/esm3/env/bin/python
export PROTEIN_AGENT_ESM3_ROOT=/abs/path/to/esm3
export PROTEIN_AGENT_ESM3_PROJECT_DIR=/abs/path/to/esm3/projects/gfp_reproduction
export PROTEIN_AGENT_ESM3_WEIGHTS_DIR=/abs/path/to/esm3/weights
export PROTEIN_AGENT_ESM3_DATA_DIR=/abs/path/to/esm3/data
export PROTEIN_AGENT_ESM3_MODEL_NAME=esm3-open
```

Optional if your project exposes explicit callables:

```bash
export PROTEIN_AGENT_ESM3_GENERATE_ENTRYPOINT=/abs/path/to/script.py:generate
export PROTEIN_AGENT_ESM3_MUTATE_ENTRYPOINT=/abs/path/to/script.py:mutate
export PROTEIN_AGENT_ESM3_STRUCTURE_ENTRYPOINT=/abs/path/to/script.py:predict_structure
```

## Optional LLM-generated Python fallback

If your local project does not expose stable entrypoints yet, you can allow the agent to generate a small Python helper at runtime:

```bash
export PROTEIN_AGENT_ALLOW_GENERATED_PYTHON=true
export PROTEIN_AGENT_OPENAI_API_KEY=<your_llm_key>
export PROTEIN_AGENT_OPENAI_BASE_URL=<openai-compatible-base-url>
export PROTEIN_AGENT_LLM_MODEL=gpt-4o-mini
```

This fallback is disabled by default because it executes LLM-generated Python in your configured ESM3 environment.

## Information still useful to provide

To finish wiring this to your exact deployment, the most valuable details are:

1. Absolute path of the `esm3/` root.
2. Absolute path of the Python executable in the environment that can import `torch` and your local `esm` package.
3. Whether your project scripts expose importable functions, and if yes, their callable names.
4. If you already have a running HTTP service, one successful `curl` request and response.

## Recommended run sequence

1. Start the Python agent API:

```bash
uvicorn protein_agent.api.main:app --host 0.0.0.0 --port 8000
```

2. Send a task:

```bash
curl -X POST http://127.0.0.1:8000/design_protein \
  -H 'Content-Type: application/json' \
  -d '{"task":"Automatically design GFP and iteratively optimize it", "max_iterations": 5, "candidates_per_round": 6}'
```

If local deployment loading fails, the bridge returns detailed `wrapper_attempts` or model-loading errors to help pinpoint which entrypoint or import needs adjustment.

## Concrete commands for your current machine

Based on the paths you provided:

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent
cp .env.local.example .env

export PROTEIN_AGENT_ESM3_PYTHON_PATH=/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python
export PROTEIN_AGENT_ESM3_ROOT=/mnt/disk3/tio_nekton4/esm3
export PROTEIN_AGENT_ESM3_PROJECT_DIR=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction
export PROTEIN_AGENT_ESM3_WEIGHTS_DIR=/mnt/disk3/tio_nekton4/esm3/weights
export PROTEIN_AGENT_ESM3_DATA_DIR=/mnt/disk3/tio_nekton4/esm3/data
export PROTEIN_AGENT_ESM3_MODEL_NAME=esm3-open
export PROTEIN_AGENT_ESM3_DEVICE=cuda
```

Start the warm local ESM3 service first:

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python -m uvicorn protein_agent.esm3_server.server:app --host 0.0.0.0 --port 8001
```

Then, in another shell, start the agent API:

```bash
export PROTEIN_AGENT_ESM3_BACKEND=http
export PROTEIN_AGENT_ESM3_SERVER_URL=http://127.0.0.1:8001
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python -m uvicorn protein_agent.api.main:app --host 0.0.0.0 --port 8000
```

Quick checks:

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/design_protein \
  -H 'Content-Type: application/json' \
  -d '{"task":"Automatically design GFP and iteratively optimize it", "max_iterations": 3, "candidates_per_round": 4}'
```

Note: `curl http://127.0.0.1:8080/health` only proves the old service is alive; it does not prove the Python `protein_agent` is connected to real ESM3.
