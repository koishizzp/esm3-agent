from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import gzip
import pickle
import subprocess
import sys
import unittest

import numpy as np
import pandas as pd

from protein_agent.agent.executor import ToolExecutor
from protein_agent.config.settings import Settings
from protein_agent.surrogate.dataset import GFPDatasetConfig, build_clean_gfp_dataset
from protein_agent.surrogate.features import FeatureConfig, SequenceFeatureExtractor
from protein_agent.surrogate.models import label_statistics, save_ensemble_bundle, train_ensemble
from protein_agent.surrogate.predictor import GFPFluorescencePredictor
from protein_agent.tools.protein_score import ProteinScoreTool
from protein_agent.workflows.gfp_optimizer import GFP_SCAFFOLD


class DummyStructureTool:
    def __init__(self, structure: dict) -> None:
        self.structure = structure

    def execute(self, input_data: dict) -> dict:
        return dict(self.structure)


class DummyPredictor:
    def __init__(self, available: bool, payload: dict | None = None, load_error: str | None = None) -> None:
        self.available = available
        self.payload = payload or {}
        self.load_error = load_error

    def predict(self, sequence: str, structure_metrics: dict | None = None) -> dict:
        if not self.available:
            raise RuntimeError(self.load_error or "unavailable")
        return dict(self.payload)


def mutate(sequence: str, position_1based: int, alt_aa: str) -> str:
    chars = list(sequence)
    chars[position_1based - 1] = alt_aa
    return "".join(chars)


class SurrogatePipelineTests(unittest.TestCase):
    def test_build_clean_dataset_from_figshare_style_mutations(self) -> None:
        raw = pd.DataFrame(
            [
                {"aaMutations": "", "medianBrightness": 3.0, "std": 0.1, "uniqueBarcodes": 10},
                {"aaMutations": "SY66H", "medianBrightness": 1.2, "std": 0.2, "uniqueBarcodes": 4},
            ]
        )

        cleaned = build_clean_gfp_dataset(raw, config=GFPDatasetConfig(reference_sequence=GFP_SCAFFOLD))

        self.assertEqual(len(cleaned), 2)
        mutated = cleaned.loc[cleaned["num_mutations"] == 1].iloc[0]
        self.assertEqual(mutated["sequence"][65], "H")
        self.assertFalse(bool(mutated["motif_intact"]))
        self.assertIn(mutated["split_random"], {"train", "valid", "test"})
        self.assertIn(mutated["split_mutation_count"], {"train", "valid", "test"})

    def test_predictor_loads_saved_ensemble_and_predicts(self) -> None:
        sequences = [
            GFP_SCAFFOLD,
            mutate(GFP_SCAFFOLD, 10, "A"),
            mutate(GFP_SCAFFOLD, 20, "L"),
            mutate(GFP_SCAFFOLD, 30, "M"),
            mutate(GFP_SCAFFOLD, 40, "Q"),
            mutate(GFP_SCAFFOLD, 50, "R"),
            mutate(GFP_SCAFFOLD, 60, "N"),
            mutate(GFP_SCAFFOLD, 70, "F"),
            mutate(mutate(GFP_SCAFFOLD, 10, "A"), 20, "L"),
            mutate(mutate(GFP_SCAFFOLD, 30, "M"), 40, "Q"),
        ]
        labels = np.asarray([3.0, 2.7, 2.6, 2.4, 2.3, 2.2, 2.0, 1.9, 1.5, 1.4], dtype=np.float32)
        frame = pd.DataFrame(
            {
                "sequence": sequences,
                "log_fluorescence": labels,
                "sample_weight": np.ones(len(sequences), dtype=np.float32),
                "split_random": ["train"] * 8 + ["valid", "test"],
            }
        )

        feature_config = FeatureConfig(reference_sequence=GFP_SCAFFOLD, feature_backend="mutation")
        extractor = SequenceFeatureExtractor(feature_config)
        train_frame = frame.iloc[:8].reset_index(drop=True)
        valid_frame = frame.iloc[8:9].reset_index(drop=True)
        train_features = extractor.transform_frame(train_frame)
        valid_features = extractor.transform_frame(valid_frame)
        models, _ = train_ensemble(
            train_features,
            train_frame["log_fluorescence"].to_numpy(dtype=np.float32),
            features_valid=valid_features,
            labels_valid=valid_frame["log_fluorescence"].to_numpy(dtype=np.float32),
            sample_weight=train_frame["sample_weight"].to_numpy(dtype=np.float32),
            model_type="gradient_boosting",
            ensemble_size=2,
            random_seed=11,
        )

        with TemporaryDirectory() as tmpdir:
            save_ensemble_bundle(
                tmpdir,
                models=models,
                feature_config=feature_config,
                metadata={
                    "model_version": Path(tmpdir).name,
                    "model_type": "gradient_boosting",
                    "label_stats": label_statistics(labels),
                },
            )
            predictor = GFPFluorescencePredictor(
                Settings(
                    surrogate_model_path=tmpdir,
                    surrogate_model_type="gradient_boosting",
                )
            )
            prediction = predictor.predict(GFP_SCAFFOLD)

        self.assertTrue(predictor.available)
        self.assertIn("predicted_fluorescence", prediction)
        self.assertIn("prediction_std", prediction)
        self.assertIn("surrogate_score", prediction)
        self.assertGreaterEqual(prediction["surrogate_score"], 0.0)
        self.assertLessEqual(prediction["surrogate_score"], 1.0)

    def test_build_embedding_cache_outputs_npz_consumable_by_feature_extractor(self) -> None:
        vector = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            offline_dir = tmp_path / "offline_run" / "embeddings"
            offline_dir.mkdir(parents=True, exist_ok=True)
            with gzip.open(offline_dir / "gfp_000000_hash_emb.pkl.gz", "wb") as handle:
                pickle.dump(("gfp_000000", GFP_SCAFFOLD, vector), handle)

            cache_path = tmp_path / "embedding_cache.npz"
            subprocess.run(
                [
                    sys.executable,
                    "protein_agent/scripts/build_embedding_cache.py",
                    "--input-dir",
                    str(tmp_path / "offline_run"),
                    "--output",
                    str(cache_path),
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
            )

            extractor = SequenceFeatureExtractor(
                FeatureConfig(
                    reference_sequence=GFP_SCAFFOLD,
                    feature_backend="hybrid",
                    embedding_cache_path=str(cache_path),
                )
            )
            features = extractor.transform([GFP_SCAFFOLD]).toarray()

        self.assertEqual(features.shape[0], 1)
        self.assertEqual(features.shape[1], len(extractor.feature_names))

    def test_executor_hybrid_mode_uses_surrogate_prediction(self) -> None:
        settings = Settings(scoring_backend="hybrid")
        executor = ToolExecutor.__new__(ToolExecutor)
        executor.settings = settings
        executor.structure_tool = DummyStructureTool(
            {
                "confidence": 0.84,
                "mean_plddt": 84.0,
                "ptm": 0.72,
                "per_residue_plddt": [84.0] * len(GFP_SCAFFOLD),
                "backend": "stub",
            }
        )
        executor.score_tool = ProteinScoreTool(settings)
        executor.surrogate_predictor = DummyPredictor(
            True,
            payload={
                "predicted_fluorescence": 2.4,
                "prediction_std": 0.1,
                "surrogate_score": 0.9,
                "model_version": "xgb_ensemble_v1",
                "model_type": "gradient_boosting",
                "feature_backend": "mutation",
            },
        )

        result = executor.evaluate(
            GFP_SCAFFOLD,
            scoring_context={
                "target": "GFP",
                "workflow": "gfp_optimizer",
                "task": "optimize gfp brightness",
                "use_gfp_constraints": True,
                "scoring_backend": "hybrid",
            },
        )

        expected = round(0.70 * 0.9 + 0.30 * result["metrics"]["structure_score"], 6)
        self.assertEqual(result["score"], expected)
        self.assertEqual(result["metrics"]["score_mode"], "hybrid")
        self.assertEqual(result["metrics"]["model_version"], "xgb_ensemble_v1")
        self.assertEqual(result["score_breakdown"]["surrogate_component"], 0.9)

    def test_executor_surrogate_mode_falls_back_to_structure(self) -> None:
        settings = Settings(scoring_backend="surrogate")
        executor = ToolExecutor.__new__(ToolExecutor)
        executor.settings = settings
        executor.structure_tool = DummyStructureTool(
            {
                "confidence": 0.84,
                "mean_plddt": 84.0,
                "ptm": 0.72,
                "per_residue_plddt": [84.0] * len(GFP_SCAFFOLD),
                "backend": "stub",
            }
        )
        executor.score_tool = ProteinScoreTool(settings)
        executor.surrogate_predictor = DummyPredictor(False, load_error="missing model")

        result = executor.evaluate(
            GFP_SCAFFOLD,
            scoring_context={
                "target": "GFP",
                "workflow": "gfp_optimizer",
                "task": "optimize gfp brightness",
                "use_gfp_constraints": True,
                "scoring_backend": "surrogate",
            },
        )

        self.assertEqual(result["metrics"]["score_mode"], "structure_fallback")
        self.assertEqual(result["metrics"]["surrogate_error"], "missing model")
        self.assertIsNone(result["metrics"]["predicted_fluorescence"])


if __name__ == "__main__":
    unittest.main()
