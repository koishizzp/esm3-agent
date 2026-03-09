"""Feature extraction for GFP surrogate models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
from typing import Any

import numpy as np
from scipy import sparse

from protein_agent.gfp import GFP_SCAFFOLD

AA_ORDER = "ACDEFGHIKLMNPQRSTVWY"
AA_INDEX = {aa: index for index, aa in enumerate(AA_ORDER)}


@dataclass(slots=True)
class FeatureConfig:
    reference_sequence: str = GFP_SCAFFOLD
    chromophore_start: int = 65
    chromophore_motif: str = "SYG"
    feature_backend: str = "mutation"
    include_sequence_stats: bool = True
    include_structure_features: bool = False
    embedding_cache_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeatureConfig":
        return cls(**payload)


class SequenceFeatureExtractor:
    """Build sparse sequence features compatible with online inference."""

    def __init__(self, config: FeatureConfig | None = None) -> None:
        self.config = config or FeatureConfig()
        self.reference_sequence = self.config.reference_sequence.strip().upper()
        self.reference_length = len(self.reference_sequence)
        self._embedding_cache = self._load_embedding_cache(self.config.embedding_cache_path)
        self.feature_names = self._build_feature_names()

    def _load_embedding_cache(self, cache_path: str | None) -> dict[str, np.ndarray]:
        if not cache_path:
            return {}
        path = Path(cache_path)
        if not path.exists():
            return {}
        if path.suffix.lower() == ".npz":
            bundle = np.load(path, allow_pickle=False)
            sequences = bundle["sequences"].tolist()
            embeddings = bundle["embeddings"]
            return {
                str(sequence).strip().upper(): np.asarray(vector, dtype=np.float32)
                for sequence, vector in zip(sequences, embeddings)
            }
        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {
                str(sequence).strip().upper(): np.asarray(vector, dtype=np.float32)
                for sequence, vector in raw.items()
            }
        return {}

    def _build_feature_names(self) -> list[str]:
        names: list[str] = []
        if self.config.feature_backend in {"mutation", "hybrid"}:
            for position, ref_aa in enumerate(self.reference_sequence, start=1):
                for alt_aa in AA_ORDER:
                    names.append(f"mut_{ref_aa}{position}{alt_aa}")

        if self.config.include_sequence_stats:
            names.extend(
                [f"aa_freq_{aa}" for aa in AA_ORDER]
                + [
                    "sequence_length",
                    "length_delta",
                    "num_mutations",
                    "motif_intact",
                ]
            )

        if self.config.include_structure_features:
            names.extend(
                [
                    "mean_plddt",
                    "ptm",
                    "structure_score",
                    "structure_confidence",
                ]
            )

        if self._embedding_cache:
            first_vector = next(iter(self._embedding_cache.values()))
            names.extend([f"embedding_{index}" for index in range(len(first_vector))])
            names.append("embedding_missing")

        return names

    def _num_mutations(self, sequence: str) -> int:
        if len(sequence) != self.reference_length:
            return abs(len(sequence) - self.reference_length)
        return sum(
            1
            for seq_aa, ref_aa in zip(sequence, self.reference_sequence)
            if seq_aa != ref_aa
        )

    def _motif_intact(self, sequence: str) -> float:
        start = self.config.chromophore_start - 1
        end = start + len(self.config.chromophore_motif)
        return float(sequence[start:end] == self.config.chromophore_motif)

    def _mutation_sparse_block(self, sequences: list[str]) -> sparse.csr_matrix:
        rows: list[int] = []
        cols: list[int] = []
        data: list[float] = []
        width = self.reference_length * len(AA_ORDER)
        if self.config.feature_backend not in {"mutation", "hybrid"}:
            return sparse.csr_matrix((len(sequences), 0), dtype=np.float32)

        for row_index, sequence in enumerate(sequences):
            seq = sequence.strip().upper()
            for position in range(min(len(seq), self.reference_length)):
                alt_aa = seq[position]
                if alt_aa not in AA_INDEX or alt_aa == self.reference_sequence[position]:
                    continue
                column = position * len(AA_ORDER) + AA_INDEX[alt_aa]
                rows.append(row_index)
                cols.append(column)
                data.append(1.0)
        return sparse.csr_matrix(
            (data, (rows, cols)),
            shape=(len(sequences), width),
            dtype=np.float32,
        )

    def _dense_sequence_block(
        self,
        sequences: list[str],
        structure_metrics: list[dict[str, Any]] | None = None,
    ) -> np.ndarray:
        blocks: list[np.ndarray] = []
        if self.config.include_sequence_stats:
            seq_features = np.zeros((len(sequences), len(AA_ORDER) + 4), dtype=np.float32)
            for row_index, sequence in enumerate(sequences):
                seq = sequence.strip().upper()
                for aa in seq:
                    if aa in AA_INDEX:
                        seq_features[row_index, AA_INDEX[aa]] += 1.0
                if seq:
                    seq_features[row_index, : len(AA_ORDER)] /= float(len(seq))
                seq_features[row_index, len(AA_ORDER)] = float(len(seq))
                seq_features[row_index, len(AA_ORDER) + 1] = float(len(seq) - self.reference_length)
                seq_features[row_index, len(AA_ORDER) + 2] = float(self._num_mutations(seq))
                seq_features[row_index, len(AA_ORDER) + 3] = self._motif_intact(seq)
            blocks.append(seq_features)

        if self.config.include_structure_features:
            structure_block = np.zeros((len(sequences), 4), dtype=np.float32)
            metrics_list = structure_metrics or [{} for _ in sequences]
            for row_index, metrics in enumerate(metrics_list):
                metrics = metrics or {}
                structure_block[row_index, 0] = float(metrics.get("mean_plddt") or 0.0)
                structure_block[row_index, 1] = float(metrics.get("ptm") or 0.0)
                structure_block[row_index, 2] = float(metrics.get("structure_score") or 0.0)
                structure_block[row_index, 3] = float(metrics.get("structure_confidence") or 0.0)
            blocks.append(structure_block)

        if self._embedding_cache:
            width = len(next(iter(self._embedding_cache.values())))
            embedding_block = np.zeros((len(sequences), width + 1), dtype=np.float32)
            for row_index, sequence in enumerate(sequences):
                vector = self._embedding_cache.get(sequence.strip().upper())
                if vector is None:
                    embedding_block[row_index, -1] = 1.0
                    continue
                embedding_block[row_index, :width] = vector
            blocks.append(embedding_block)

        if not blocks:
            return np.zeros((len(sequences), 0), dtype=np.float32)
        return np.hstack(blocks).astype(np.float32, copy=False)

    def transform(
        self,
        sequences: list[str],
        structure_metrics: list[dict[str, Any]] | None = None,
    ) -> sparse.csr_matrix:
        sparse_block = self._mutation_sparse_block(sequences)
        dense_block = self._dense_sequence_block(sequences, structure_metrics=structure_metrics)
        if dense_block.shape[1] == 0:
            return sparse_block
        dense_sparse = sparse.csr_matrix(dense_block, dtype=np.float32)
        if sparse_block.shape[1] == 0:
            return dense_sparse
        return sparse.hstack([sparse_block, dense_sparse], format="csr", dtype=np.float32)

    def transform_frame(
        self,
        frame: Any,
        structure_metrics: list[dict[str, Any]] | None = None,
    ) -> sparse.csr_matrix:
        sequences = frame["sequence"].tolist()
        if structure_metrics is None and self.config.include_structure_features:
            structure_metrics = frame.to_dict(orient="records")
        return self.transform(sequences, structure_metrics=structure_metrics)
