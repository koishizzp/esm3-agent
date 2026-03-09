"""Export GFP sequences from a cleaned dataset to FASTA."""
from __future__ import annotations

import argparse
from pathlib import Path

from protein_agent.surrogate.dataset import read_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Cleaned dataset path")
    parser.add_argument("--output", required=True, help="Output FASTA path")
    parser.add_argument("--sequence-column", default="sequence")
    parser.add_argument("--id-column", default=None, help="Optional stable ID column")
    parser.add_argument("--prefix", default="gfp")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    df = read_table(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for index, row in df.reset_index(drop=True).iterrows():
            sequence = str(row[args.sequence_column]).strip().upper()
            if not sequence:
                continue
            if args.id_column and args.id_column in row.index:
                name = str(row[args.id_column]).strip() or f"{args.prefix}_{index:06d}"
            else:
                name = f"{args.prefix}_{index:06d}"
            handle.write(f">{name}\n{sequence}\n")

    print(f"Exported FASTA: {output_path}")


if __name__ == "__main__":
    main()
