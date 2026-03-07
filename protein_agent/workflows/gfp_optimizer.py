"""Built-in GFP optimization workflow."""
from __future__ import annotations

from protein_agent.agent.executor import ToolExecutor
from protein_agent.agent.workflow import ExperimentLoopEngine
from protein_agent.memory.experiment_memory import ExperimentMemory


GFP_SCAFFOLD = (
    "MSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLV"
    "TTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK"
)


class GFPOptimizer:
    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor
        self.memory = ExperimentMemory()
        self.loop_engine = ExperimentLoopEngine(executor, self.memory)

    def run(self, task: str, max_iterations: int, candidates_per_round: int, patience: int) -> dict:
        plan = {
            "workflow": "gfp_optimizer",
            "target": "GFP",
            "max_iterations": max_iterations,
            "patience": patience,
            "candidates_per_round": candidates_per_round,
            "steps": [
                "identify_gfp_scaffold",
                "generate_mutations",
                "predict_structure",
                "score_candidates",
                "select_best_variants",
                "repeat",
            ],
        }
        full_task = f"{task}. Use GFP scaffold: {GFP_SCAFFOLD}"
        return self.loop_engine.run(plan=plan, task=full_task)
