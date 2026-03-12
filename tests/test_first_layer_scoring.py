from __future__ import annotations

import unittest

from protein_agent.agent.workflow import ExperimentLoopEngine
from protein_agent.config.settings import Settings
from protein_agent.esm3_integration.bridge import normalize_structure
from protein_agent.memory.experiment_memory import ExperimentMemory
from protein_agent.tools.protein_score import HARD_CONSTRAINT_PENALTY, ProteinScoreTool
from protein_agent.workflows.gfp_optimizer import GFP_SCAFFOLD


class DummyExecutor:
    def __init__(self) -> None:
        self.score_tool = ProteinScoreTool(Settings())

    def generate(self, prompt: str, num_candidates: int) -> list[str]:
        return [GFP_SCAFFOLD][:num_candidates]

    def mutate(self, sequence: str, num_mutations: int, num_candidates: int) -> list[str]:
        return [sequence][:num_candidates]

    def evaluate(self, sequence: str, scoring_context: dict | None = None) -> dict:
        structure = {
            "confidence": 0.84,
            "mean_plddt": 84.0,
            "per_residue_plddt": [84.0] * len(sequence),
            "ptm": 0.72,
            "iptm": None,
            "backend": "stub_backend",
        }
        score = self.score_tool.execute(
            {
                "sequence": sequence,
                "structure": structure,
                "scoring_context": scoring_context or {},
            }
        )
        return {"structure": structure, **score}


class FirstLayerScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = ProteinScoreTool(Settings())
        self.scoring_context = {
            "target": "GFP",
            "workflow": "gfp_optimizer",
            "task": "optimize gfp brightness",
            "use_gfp_constraints": True,
        }

    def test_score_depends_on_structure_not_sequence_composition(self) -> None:
        seq_a = GFP_SCAFFOLD
        seq_b = ("A" * 64) + "SYG" + ("A" * (len(GFP_SCAFFOLD) - 67))
        structure = {
            "mean_plddt": 86.0,
            "ptm": 0.75,
            "confidence": 0.86,
        }

        score_a = self.tool.execute(
            {"sequence": seq_a, "structure": structure, "scoring_context": self.scoring_context}
        )
        score_b = self.tool.execute(
            {"sequence": seq_b, "structure": structure, "scoring_context": self.scoring_context}
        )

        self.assertEqual(score_a["score"], score_b["score"])
        self.assertEqual(score_a["score_breakdown"], score_b["score_breakdown"])

    def test_broken_chromophore_is_penalized_and_filtered(self) -> None:
        broken = GFP_SCAFFOLD[:64] + "AAA" + GFP_SCAFFOLD[67:]
        structure = {
            "mean_plddt": 86.0,
            "ptm": 0.75,
            "confidence": 0.86,
        }

        intact = self.tool.execute(
            {"sequence": GFP_SCAFFOLD, "structure": structure, "scoring_context": self.scoring_context}
        )
        broken_result = self.tool.execute(
            {"sequence": broken, "structure": structure, "scoring_context": self.scoring_context}
        )

        self.assertTrue(intact["valid_candidate"])
        self.assertFalse(broken_result["valid_candidate"])
        self.assertEqual(
            broken_result["score"],
            round(intact["score"] - HARD_CONSTRAINT_PENALTY, 6),
        )
        self.assertFalse(broken_result["metrics"]["motif_intact"])

    def test_missing_ptm_uses_confidence_fallback_without_faking_metric(self) -> None:
        result = self.tool.execute(
            {
                "sequence": GFP_SCAFFOLD,
                "structure": {
                    "mean_plddt": 82.0,
                    "per_residue_plddt": [82.0] * len(GFP_SCAFFOLD),
                    "confidence": 0.82,
                },
                "scoring_context": self.scoring_context,
            }
        )

        self.assertIsNone(result["metrics"]["ptm"])
        self.assertFalse(result["metrics"]["ptm_available"])
        self.assertEqual(result["score_breakdown"]["ptm_component_source"], "confidence_fallback")
        self.assertEqual(result["metrics"]["ptm_component_source"], "confidence_fallback")
        self.assertGreater(result["score"], 0.0)

    def test_fixed_residue_violation_is_penalized_and_filtered(self) -> None:
        structure = {
            "mean_plddt": 86.0,
            "ptm": 0.75,
            "confidence": 0.86,
        }
        fixed_position = 96
        intact = self.tool.execute(
            {
                "sequence": GFP_SCAFFOLD,
                "structure": structure,
                "scoring_context": {
                    **self.scoring_context,
                    "fixed_residues": [{"position": fixed_position, "residue": GFP_SCAFFOLD[fixed_position - 1]}],
                },
            }
        )
        broken_sequence = GFP_SCAFFOLD[: fixed_position - 1] + "A" + GFP_SCAFFOLD[fixed_position:]
        broken = self.tool.execute(
            {
                "sequence": broken_sequence,
                "structure": structure,
                "scoring_context": {
                    **self.scoring_context,
                    "fixed_residues": [{"position": fixed_position, "residue": GFP_SCAFFOLD[fixed_position - 1]}],
                },
            }
        )

        self.assertTrue(intact["valid_candidate"])
        self.assertFalse(broken["valid_candidate"])
        self.assertEqual(
            broken["score"],
            round(intact["score"] - HARD_CONSTRAINT_PENALTY, 6),
        )
        self.assertEqual(broken["metrics"]["fixed_residue_penalty"], HARD_CONSTRAINT_PENALTY)
        self.assertEqual(broken["metrics"]["fixed_residue_violations"][0]["position"], fixed_position)

    def test_bridge_keeps_schema_stable_when_ptm_is_missing(self) -> None:
        normalized = normalize_structure(
            {
                "plddt": [0.80, 0.90, 0.85],
                "confidence": 0.85,
                "coordinates": {"atoms": 1},
            }
        )

        self.assertEqual(normalized["mean_plddt"], 85.0)
        self.assertIsNone(normalized["ptm"])
        self.assertEqual(normalized["per_residue_plddt"], [80.0, 90.0, 85.0])
        self.assertIn("pae", normalized)
        self.assertIn("iptm", normalized)

    def test_workflow_memory_records_score_breakdown_and_structure_metrics(self) -> None:
        engine = ExperimentLoopEngine(DummyExecutor(), ExperimentMemory())
        result = engine.run(
            plan={
                "workflow": "gfp_optimizer",
                "target": "GFP",
                "max_iterations": 1,
                "patience": 1,
                "candidates_per_round": 1,
            },
            task="optimize gfp brightness",
            seed_prompt=GFP_SCAFFOLD,
            initial_sequences=[GFP_SCAFFOLD],
        )

        self.assertEqual(len(result["records"]), 1)
        metadata = result["records"][0]["metadata"]
        self.assertIn("score_breakdown", metadata)
        self.assertEqual(metadata["mean_plddt"], 84.0)
        self.assertEqual(metadata["ptm"], 0.72)
        self.assertTrue(metadata["motif_intact"])
        self.assertEqual(metadata["score_version"], "structure_proxy_v3")

    def test_workflow_projects_sequences_to_hard_constraints_before_scoring(self) -> None:
        engine = ExperimentLoopEngine(DummyExecutor(), ExperimentMemory())
        broken = GFP_SCAFFOLD[:62] + "AAA" + GFP_SCAFFOLD[65:95] + "A" + GFP_SCAFFOLD[96:]
        result = engine.run(
            plan={
                "workflow": "gfp_optimizer",
                "target": "GFP",
                "max_iterations": 1,
                "patience": 1,
                "candidates_per_round": 1,
            },
            task="optimize gfp brightness",
            seed_prompt=GFP_SCAFFOLD,
            initial_sequences=[broken],
            multimodal_context={
                "sequence_constraints": {
                    "reference_length": len(GFP_SCAFFOLD),
                    "fixed_residues": [
                        {"position": 63, "residue": "S"},
                        {"position": 64, "residue": "Y"},
                        {"position": 65, "residue": "G"},
                        {"position": 96, "residue": GFP_SCAFFOLD[95]},
                    ],
                }
            },
        )

        self.assertEqual(len(result["records"]), 1)
        record = result["records"][0]
        self.assertEqual(record["sequence"][62:65], "SYG")
        self.assertEqual(record["sequence"][95], GFP_SCAFFOLD[95])
        self.assertTrue(record["metadata"]["motif_intact"])
        self.assertEqual(record["metadata"]["fixed_residue_violations"], [])


if __name__ == "__main__":
    unittest.main()
