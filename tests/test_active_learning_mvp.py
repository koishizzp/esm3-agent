from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from protein_agent.active_learning.acquisition import batch_ucb
from protein_agent.active_learning.selection import hamming_distance, select_diverse_topk
from protein_agent.memory.experiment_memory import ExperimentMemory, ExperimentRecord
from protein_agent.scripts.build_active_learning_dataset import merge_active_learning_dataset
from protein_agent.scripts.export_active_learning_batch import select_batch_rows
from protein_agent.scripts.export_retrospective_oracle_batch import score_oracle_pool
from protein_agent.scripts.import_wetlab_results import normalize_wetlab_records
from protein_agent.scripts.promote_surrogate_model import promote_model
from protein_agent.scripts.prepare_retrospective_active_learning_split import parse_split_list
from protein_agent.scripts.simulate_wetlab_from_oracle import simulate_rows


class ActiveLearningMVPTests(unittest.TestCase):
    def test_best_is_none_when_all_records_are_invalid(self) -> None:
        memory = ExperimentMemory(run_metadata={"task": "Design GFP variants"})
        memory.add(
            ExperimentRecord(
                sequence="BADSEQ",
                mutation_history=[],
                score=-2.0,
                iteration=1,
                metadata={"valid_candidate": False},
            )
        )

        self.assertIsNone(memory.best())
        self.assertIsNone(memory.to_dict()["best"])

    def test_experiment_memory_json_round_trip_preserves_metadata(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run.json"
            memory = ExperimentMemory(
                run_metadata={
                    "schema_version": 1,
                    "task": "Design GFP variants",
                    "created_at": "2026-03-11T00:00:00+00:00",
                }
            )
            memory.add(
                ExperimentRecord(
                    sequence="KGEELF",
                    mutation_history=["initial_generate"],
                    score=0.91,
                    iteration=1,
                    metadata={"prediction_std": 0.12, "valid_candidate": True},
                )
            )

            memory.save_json(path)
            loaded = ExperimentMemory.load_json(path)

        self.assertEqual(loaded.run_metadata["task"], "Design GFP variants")
        self.assertEqual(len(loaded.all_records()), 1)
        self.assertAlmostEqual(loaded.all_records()[0].score, 0.91)

    def test_export_batch_uses_acquisition_ranking(self) -> None:
        memory = ExperimentMemory(run_metadata={"surrogate_model_version": "xgb_ensemble_active_v001"})
        memory.add(
            ExperimentRecord(
                sequence="SEQ_A",
                mutation_history=[],
                score=0.8,
                iteration=1,
                metadata={
                    "predicted_fluorescence": 3.0,
                    "prediction_std": 0.1,
                    "surrogate_score": 0.8,
                    "structure_score": 0.5,
                    "valid_candidate": True,
                },
            )
        )
        memory.add(
            ExperimentRecord(
                sequence="SEQ_B",
                mutation_history=[],
                score=0.7,
                iteration=1,
                metadata={
                    "predicted_fluorescence": 3.0,
                    "prediction_std": 0.4,
                    "surrogate_score": 0.7,
                    "structure_score": 0.4,
                    "valid_candidate": True,
                },
            )
        )

        rows = select_batch_rows(
            memory,
            batch_id="gfp_round_001",
            top_k=2,
            acquisition_lambda=0.5,
        )

        self.assertEqual(rows[0]["sequence"], "SEQ_B")
        self.assertEqual(rows[0]["selected_rank"], 1)
        self.assertIn("acquisition_score", rows[0])

    def test_diverse_topk_enforces_minimum_hamming_distance(self) -> None:
        scores = batch_ucb([3.0, 2.9, 2.8], [0.1, 0.5, 0.2], lambda_=0.5)
        selected = select_diverse_topk(
            ["AAAA", "AAAT", "TTTT"],
            scores,
            k=2,
            min_hamming=2,
        )

        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0][0], "AAAT")
        self.assertEqual(selected[1][0], "TTTT")
        self.assertEqual(hamming_distance(selected[0][0], selected[1][0]), 3)

    def test_normalize_wetlab_records_groups_by_batch(self) -> None:
        grouped = normalize_wetlab_records(
            [
                {
                    "batch_id": "gfp_round_001",
                    "sequence": "KGEELF",
                    "measured_log_fluorescence": "3.42",
                    "label_std": "0.08",
                }
            ],
            input_path="results.csv",
        )

        self.assertIn("gfp_round_001", grouped)
        self.assertEqual(grouped["gfp_round_001"][0]["sequence"], "KGEELF")
        self.assertEqual(grouped["gfp_round_001"][0]["sample_weight"], 1.0)

    def test_merge_dataset_prefers_newest_wetlab_row_for_same_sequence(self) -> None:
        base_df = pd.DataFrame(
            [
                {
                    "sequence": "SEQ1",
                    "log_fluorescence": 1.0,
                    "sample_weight": 1.0,
                    "source": "base_public",
                    "split_random": "test",
                    "split_mutation_count": "test",
                }
            ]
        )
        wetlab_df = pd.DataFrame(
            [
                {
                    "sequence": "SEQ1",
                    "log_fluorescence": 2.0,
                    "sample_weight": 1.0,
                    "source": "wetlab",
                    "assay_date": "2026-03-10",
                    "imported_at": "2026-03-11T01:00:00+00:00",
                    "split_random": "train",
                    "split_mutation_count": "train",
                }
            ]
        )

        merged = merge_active_learning_dataset(base_df, wetlab_df)

        self.assertEqual(len(merged), 1)
        self.assertEqual(float(merged.iloc[0]["log_fluorescence"]), 2.0)
        self.assertEqual(merged.iloc[0]["source"], "wetlab")
        self.assertEqual(merged.iloc[0]["split_random"], "train")

    def test_simulate_rows_looks_up_public_oracle_labels(self) -> None:
        simulated, missing = simulate_rows(
            [{"batch_id": "gfp_round_001", "sequence": "SEQ1"}],
            oracle_lookup={
                "SEQ1": {
                    "sequence": "SEQ1",
                    "log_fluorescence": 2.5,
                    "label_std": 0.1,
                }
            },
            label_column="log_fluorescence",
            assay_name="retrospective_public_oracle",
            assay_date="2026-03-11",
            operator="simulator",
            noise_std=0.0,
            seed=7,
            allow_missing=False,
        )

        self.assertEqual(missing, [])
        self.assertEqual(simulated[0]["measured_log_fluorescence"], 2.5)
        self.assertEqual(simulated[0]["notes"], "simulated_from_public_oracle")

    def test_parse_split_list_ignores_empty_items(self) -> None:
        self.assertEqual(parse_split_list("train, valid,,test"), ["train", "valid", "test"])

    def test_score_oracle_pool_ranks_and_filters_sequences(self) -> None:
        class DummyPredictor:
            def predict(self, sequence: str, structure_metrics: dict | None = None) -> dict:
                mapping = {
                    "AAAA": {"predicted_fluorescence": 2.0, "prediction_std": 0.1, "surrogate_score": 0.5, "model_version": "v1"},
                    "AAAT": {"predicted_fluorescence": 2.1, "prediction_std": 0.4, "surrogate_score": 0.55, "model_version": "v1"},
                    "TTTT": {"predicted_fluorescence": 1.9, "prediction_std": 0.2, "surrogate_score": 0.45, "model_version": "v1"},
                }
                return mapping[sequence]

        with TemporaryDirectory() as tmpdir:
            oracle_path = Path(tmpdir) / "oracle.csv"
            pd.DataFrame({"sequence": ["AAAA", "AAAT", "TTTT"]}).to_csv(oracle_path, index=False)
            rows = score_oracle_pool(
                oracle_dataset=oracle_path,
                predictor=DummyPredictor(),
                top_k=2,
                acquisition_lambda=0.5,
                min_hamming=2,
                batch_id="oracle_round_001",
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["sequence"], "AAAT")
        self.assertEqual(rows[1]["sequence"], "TTTT")

    def test_promote_model_updates_env_and_manifest(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model_dir = root / "models" / "xgb_ensemble_active_v001"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "metadata.json").write_text(
                (
                    "{\n"
                    '  "model_version": "xgb_ensemble_active_v001",\n'
                    '  "model_type": "gradient_boosting",\n'
                    '  "ensemble_size": 3,\n'
                    '  "feature_backend": "mutation"\n'
                    "}\n"
                ),
                encoding="utf-8",
            )
            (model_dir / "feature_config.json").write_text(
                (
                    "{\n"
                    '  "feature_backend": "mutation",\n'
                    '  "include_structure_features": false\n'
                    "}\n"
                ),
                encoding="utf-8",
            )
            env_path = root / ".env"
            env_path.write_text("PROTEIN_AGENT_SCORING_BACKEND=structure\n", encoding="utf-8")
            active_model_path = root / "active_model.json"

            summary = promote_model(
                model_dir=model_dir,
                env_file=env_path,
                scoring_backend="hybrid",
                active_model_path=active_model_path,
            )

            env_text = env_path.read_text(encoding="utf-8")
            manifest_text = active_model_path.read_text(encoding="utf-8")

        self.assertIn("PROTEIN_AGENT_SCORING_BACKEND=hybrid", env_text)
        self.assertIn("PROTEIN_AGENT_SURROGATE_MODEL_PATH=", env_text)
        self.assertIn('"status": "active"', manifest_text)
        self.assertEqual(summary["model_version"], "xgb_ensemble_active_v001")


if __name__ == "__main__":
    unittest.main()
