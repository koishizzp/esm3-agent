"""Normalize wet-lab result files into active-learning JSONL artifacts."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from protein_agent.memory.storage import ensure_active_learning_layout, read_jsonl, write_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Wet-lab CSV or JSONL file")
    parser.add_argument("--batch-id", default=None, help="Optional batch id override")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional normalized output directory. Defaults to data/active_learning/wetlab",
    )
    return parser


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_input_records(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".jsonl":
        return read_jsonl(file_path)
    if suffix == ".csv":
        with file_path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    raise ValueError(f"Unsupported wet-lab input format: {file_path}")


def normalize_wetlab_records(
    rows: list[dict[str, Any]],
    *,
    input_path: str | Path,
    batch_id_override: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    imported_at = datetime.now(timezone.utc).isoformat()
    fallback_batch_id = batch_id_override or Path(input_path).stem
    grouped: dict[str, list[dict[str, Any]]] = {}

    for index, row in enumerate(rows, start=1):
        sequence = str(row.get("sequence") or "").strip().upper()
        if not sequence:
            raise ValueError(f"Missing sequence in row {index}")

        measured = _to_float(
            row.get("measured_log_fluorescence") or row.get("log_fluorescence")
        )
        if measured is None:
            raise ValueError(f"Missing measured_log_fluorescence in row {index}")

        batch_id = str(batch_id_override or row.get("batch_id") or fallback_batch_id).strip()
        if not batch_id:
            raise ValueError(f"Missing batch_id in row {index}")

        normalized = {
            "batch_id": batch_id,
            "sequence": sequence,
            "measured_log_fluorescence": measured,
            "raw_brightness": _to_float(row.get("raw_brightness")),
            "label_std": _to_float(row.get("label_std")),
            "assay_name": str(row.get("assay_name") or "").strip(),
            "assay_date": str(row.get("assay_date") or "").strip(),
            "operator": str(row.get("operator") or "").strip(),
            "notes": str(row.get("notes") or "").strip(),
            "source": "wetlab",
            "sample_weight": _to_float(row.get("sample_weight")) or 1.0,
            "imported_at": imported_at,
        }
        grouped.setdefault(batch_id, []).append(normalized)

    return grouped


def main() -> None:
    args = build_parser().parse_args()
    records = load_input_records(args.input)
    grouped = normalize_wetlab_records(
        records,
        input_path=args.input,
        batch_id_override=args.batch_id,
    )
    layout = ensure_active_learning_layout()
    output_dir = Path(args.output_dir) if args.output_dir else layout["wetlab"]
    saved_paths: list[Path] = []
    for batch_id, items in grouped.items():
        saved_paths.append(write_jsonl(items, output_dir / f"{batch_id}.jsonl"))
    for path in saved_paths:
        print(f"Saved normalized wet-lab results: {path}")


if __name__ == "__main__":
    main()
