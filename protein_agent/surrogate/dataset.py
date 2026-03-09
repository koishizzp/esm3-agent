"""Dataset helpers for GFP surrogate training."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from protein_agent.gfp import GFP_SCAFFOLD

AA_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")


@dataclass(slots=True)
class GFPDatasetConfig:
    reference_sequence: str = GFP_SCAFFOLD
    reference_name: str = "avGFP"
    chromophore_start: int = 65
    chromophore_motif: str = "SYG"
    random_seed: int = 7
    train_max_mutations: int = 3
    valid_max_mutations: int = 4


def load_reference_sequence(
    fasta_path: str | Path | None = None,
    fallback: str | None = None,
) -> str:
    if fasta_path is None:
        return (fallback or GFP_SCAFFOLD).strip().upper()

    text = Path(fasta_path).read_text(encoding="utf-8")
    parts = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith(">")]
    sequence = "".join(parts).strip().upper()
    return sequence or (fallback or GFP_SCAFFOLD).strip().upper()


def read_table(path: str | Path) -> pd.DataFrame:
    dataset_path = Path(path)
    suffix = dataset_path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(dataset_path)
    if suffix in {".tsv", ".txt"}:
        return pd.read_csv(dataset_path, sep="\t")
    return pd.read_csv(dataset_path)


def write_table_with_fallback(
    df: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        try:
            df.to_parquet(path, index=False)
            return path
        except Exception:  # noqa: BLE001
            fallback = path.with_suffix(".csv")
            df.to_csv(fallback, index=False)
            return fallback
    if path.suffix.lower() in {".tsv", ".txt"}:
        df.to_csv(path, index=False, sep="\t")
        return path
    df.to_csv(path, index=False)
    return path


def write_json(payload: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _first_present(row: pd.Series, names: list[str]) -> Any:
    for name in names:
        if name in row.index:
            value = row[name]
            if value is not None and not (isinstance(value, float) and math.isnan(value)):
                return value
    return None


def split_mutation_tokens(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, float) and math.isnan(value):
        return []
    text = str(value).strip()
    if not text or text.lower() in {"wt", "wildtype", "wild_type", "[]"}:
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    tokens = [item.strip() for item in re.split(r"[,;:\s]+", text) if item.strip()]
    return tokens


def parse_aa_substitution(token: str) -> tuple[str, int, str] | None:
    cleaned = token.strip().upper()
    if not cleaned:
        return None

    direct = re.fullmatch(r"([A-Z\*])(\d+)([A-Z\*])", cleaned)
    if direct:
        return direct.group(1), int(direct.group(2)), direct.group(3)

    prefixed = re.fullmatch(r"([SDI])([A-Z\*])(\d+)([A-Z\*])", cleaned)
    if not prefixed:
        return None
    if prefixed.group(1) != "S":
        return None
    return prefixed.group(2), int(prefixed.group(3)), prefixed.group(4)


def apply_aa_mutations(
    reference_sequence: str,
    mutation_tokens: list[str],
) -> tuple[str, list[str]]:
    sequence = list(reference_sequence.strip().upper())
    canonical_tokens: list[str] = []

    for token in mutation_tokens:
        parsed = parse_aa_substitution(token)
        if parsed is None:
            raise ValueError(f"Unsupported amino-acid mutation token: {token}")

        ref_aa, raw_position, alt_aa = parsed
        candidate_indices: list[int] = []
        if 1 <= raw_position <= len(sequence):
            candidate_indices.append(raw_position - 1)
        if 0 <= raw_position < len(sequence):
            candidate_indices.append(raw_position)

        chosen_index = None
        for index in candidate_indices:
            if sequence[index] == ref_aa or reference_sequence[index] == ref_aa:
                chosen_index = index
                break

        if chosen_index is None:
            raise ValueError(
                f"Mutation {token} does not match reference sequence at 0/1-based positions"
            )

        sequence[chosen_index] = alt_aa
        canonical_tokens.append(f"{ref_aa}{chosen_index + 1}{alt_aa}")

    return "".join(sequence), canonical_tokens


def canonical_mutations(
    sequence: str,
    reference_sequence: str,
) -> list[str]:
    seq = sequence.strip().upper()
    ref = reference_sequence.strip().upper()
    if len(seq) != len(ref):
        return []
    return [
        f"{ref_aa}{index}{seq_aa}"
        for index, (ref_aa, seq_aa) in enumerate(zip(ref, seq), start=1)
        if ref_aa != seq_aa
    ]


def motif_intact(
    sequence: str,
    chromophore_start: int,
    chromophore_motif: str,
) -> bool:
    start = chromophore_start - 1
    end = start + len(chromophore_motif)
    return sequence[start:end] == chromophore_motif


def build_clean_gfp_dataset(
    raw_df: pd.DataFrame,
    config: GFPDatasetConfig | None = None,
) -> pd.DataFrame:
    config = config or GFPDatasetConfig()
    reference_sequence = config.reference_sequence.strip().upper()
    records: list[dict[str, Any]] = []

    for row_index, row in raw_df.iterrows():
        label = _first_present(
            row,
            [
                "medianBrightness",
                "log_fluorescence",
                "brightness",
                "median_brightness",
            ],
        )
        if label is None:
            continue

        sequence_value = _first_present(
            row,
            [
                "aaSequence",
                "aminoAcidSequence",
                "sequence",
            ],
        )
        mutation_value = _first_present(
            row,
            [
                "aaMutations",
                "aminoAcidMutations",
                "mutations",
            ],
        )

        try:
            if sequence_value is not None and str(sequence_value).strip():
                sequence = str(sequence_value).strip().upper()
                mutations = canonical_mutations(sequence, reference_sequence)
            else:
                sequence, mutations = apply_aa_mutations(
                    reference_sequence=reference_sequence,
                    mutation_tokens=split_mutation_tokens(mutation_value),
                )
        except ValueError:
            continue

        if not sequence or any(residue not in AA_ALPHABET for residue in sequence):
            continue
        if len(sequence) != len(reference_sequence):
            continue

        label_std = _first_present(row, ["std", "label_std", "brightnessStd"])
        sample_weight = _first_present(row, ["uniqueBarcodes", "sample_weight", "count"])

        records.append(
            {
                "sequence": sequence,
                "mutations": " ".join(mutations),
                "num_mutations": len(mutations),
                "log_fluorescence": float(label),
                "label_std": 0.0 if label_std is None else float(label_std),
                "sample_weight": 1.0 if sample_weight is None else max(float(sample_weight), 1.0),
                "motif_intact": motif_intact(
                    sequence,
                    chromophore_start=config.chromophore_start,
                    chromophore_motif=config.chromophore_motif,
                ),
                "reference_name": config.reference_name,
                "source_row_index": int(row_index),
                "raw_mutations": "" if mutation_value is None else str(mutation_value),
            }
        )

    if not records:
        return pd.DataFrame(
            columns=[
                "sequence",
                "mutations",
                "num_mutations",
                "log_fluorescence",
                "label_std",
                "sample_weight",
                "motif_intact",
                "reference_name",
                "source_num_records",
                "split_random",
                "split_mutation_count",
            ]
        )

    cleaned = pd.DataFrame.from_records(records)
    aggregated = (
        cleaned.groupby("sequence", as_index=False)
        .agg(
            {
                "mutations": "first",
                "num_mutations": "first",
                "log_fluorescence": "median",
                "label_std": "median",
                "sample_weight": "sum",
                "motif_intact": "first",
                "reference_name": "first",
                "source_row_index": "count",
            }
        )
        .rename(columns={"source_row_index": "source_num_records"})
    )
    return attach_split_columns(aggregated, config=config)


def attach_split_columns(
    df: pd.DataFrame,
    config: GFPDatasetConfig | None = None,
) -> pd.DataFrame:
    config = config or GFPDatasetConfig()
    if df.empty:
        return df.copy()

    out = df.copy()
    rng = np.random.default_rng(config.random_seed)
    order = np.arange(len(out))
    rng.shuffle(order)

    valid_size = max(1, int(round(len(out) * 0.1)))
    test_size = max(1, int(round(len(out) * 0.1)))
    split_random = np.full(len(out), "train", dtype=object)
    split_random[order[:valid_size]] = "valid"
    split_random[order[valid_size : valid_size + test_size]] = "test"
    out["split_random"] = split_random

    split_mutation = np.full(len(out), "train", dtype=object)
    split_mutation[out["num_mutations"] > config.valid_max_mutations] = "test"
    split_mutation[
        (out["num_mutations"] > config.train_max_mutations)
        & (out["num_mutations"] <= config.valid_max_mutations)
    ] = "valid"

    if "test" not in set(split_mutation):
        max_mutations = int(out["num_mutations"].max())
        split_mutation[out["num_mutations"] == max_mutations] = "test"
    if "valid" not in set(split_mutation):
        candidate = out.loc[split_mutation == "train"]
        if not candidate.empty:
            threshold = int(candidate["num_mutations"].max())
            split_mutation[(split_mutation == "train") & (out["num_mutations"] == threshold)] = "valid"

    out["split_mutation_count"] = split_mutation
    return out


def split_dataset(
    df: pd.DataFrame,
    split_column: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if split_column not in df.columns:
        raise KeyError(f"Missing split column: {split_column}")
    train_df = df[df[split_column] == "train"].reset_index(drop=True)
    valid_df = df[df[split_column] == "valid"].reset_index(drop=True)
    test_df = df[df[split_column] == "test"].reset_index(drop=True)
    return train_df, valid_df, test_df


def dataset_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"num_rows": 0}
    return {
        "num_rows": int(len(df)),
        "num_unique_sequences": int(df["sequence"].nunique()),
        "brightness_min": float(df["log_fluorescence"].min()),
        "brightness_max": float(df["log_fluorescence"].max()),
        "brightness_mean": float(df["log_fluorescence"].mean()),
        "mutation_count_min": int(df["num_mutations"].min()),
        "mutation_count_max": int(df["num_mutations"].max()),
        "motif_intact_fraction": float(df["motif_intact"].mean()),
    }
