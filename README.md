# Autonomous AI Protein Design Agent (ESM3)

This repository now includes a Python modular agent stack for autonomous protein engineering with a local ESM3 server.

## Project Structure

```text
protein_agent/
  agent/
    planner.py
    executor.py
    workflow.py
  tools/
    base.py
    esm3_generate.py
    esm3_mutate.py
    esm3_structure.py
    protein_score.py
  esm3_server/
    server.py
  memory/
    experiment_memory.py
  workflows/
    gfp_optimizer.py
  api/
    main.py
  config/
    settings.py
  scripts/
    run_design_example.py
requirements.txt
README.md
```

## Architecture

User Prompt → LLM Planner → Task Plan → Tool Executor → ESM3 + Evaluation → Iterative Loop + Memory.

### Core Components
- **LLM Planner**: Converts natural language into structured JSON experiment plans.
- **Tool Execution Layer**: Calls ESM3 generate/mutate/structure endpoints and scoring.
- **ESM3 Model Server**: Loads ESM3 once and provides API endpoints.
- **Experiment Loop Engine**: Runs iterative generate/evaluate/select/mutate cycles.
- **Protein Evaluation Module**: Scores candidates with sequence and structure-aware features.
- **Experiment Memory**: Stores sequence, mutation history, score, iteration, and structure data.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run ESM3 Server (local model)

```bash
export ESM3_MODEL_NAME=esm3-open
uvicorn protein_agent.esm3_server.server:app --host 0.0.0.0 --port 8001
```

## Run Agent API

```bash
export PROTEIN_AGENT_ESM3_SERVER_URL=http://127.0.0.1:8001
# Optional LLM planner config
export PROTEIN_AGENT_OPENAI_API_KEY=<your_key>
export PROTEIN_AGENT_OPENAI_BASE_URL=<optional_openai_compatible_endpoint>
export PROTEIN_AGENT_LLM_MODEL=gpt-4o-mini

uvicorn protein_agent.api.main:app --host 0.0.0.0 --port 8000
```

## API Usage

### Health
```bash
curl http://127.0.0.1:8000/health
```

### Design Protein
```bash
curl -X POST http://127.0.0.1:8000/design_protein \
  -H "Content-Type: application/json" \
  -d '{"task":"design a brighter GFP variant","max_iterations":20}'
```

Response contains experiment history, best sequence, and scores.

## GFP Workflow

Built-in workflow in `protein_agent/workflows/gfp_optimizer.py`:
1. Identify GFP scaffold
2. Generate mutations
3. Predict structure
4. Score candidates
5. Select best variants
6. Repeat (up to 100 iterations)

## Example Run Script

```bash
python protein_agent/scripts/run_design_example.py
```

## Notes

- The implementation is designed for **local ESM3 inference** (`from esm.models.esm3 import ESM3`).
- Iterations stop on either `max_iterations` or plateau (`patience` rounds with no improvement).
