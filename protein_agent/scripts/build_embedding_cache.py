"""Build an embedding cache `.npz` from offline ESM3 outputs."""
from __future__ import annotations

import argparse
from pathlib import Path
import gzip
import pickle

import numpy as np


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, help="Output directory produced by get_embeddings_offline.py")
    parser.add_argument("--output", required=True, help="Output `.npz` path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    input_dir = Path(args.input_dir)
    embedding_files = sorted((input_dir / "embeddings").glob("*_emb.pkl.gz"))
    if not embedding_files:
        raise SystemExit("No `*_emb.pkl.gz` files found. Run get_embeddings_offline.py with `--format pkl.gz` or `both`.")

    names: list[str] = []
    sequences: list[str] = []
    vectors: list[np.ndarray] = []

    for file_path in embedding_files:
        with gzip.open(file_path, "rb") as handle:
            name, sequence, embedding = pickle.load(handle)
        names.append(str(name))
        sequences.append(str(sequence).strip().upper())
        vectors.append(np.asarray(embedding, dtype=np.float32))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        names=np.asarray(names, dtype=str),
        sequences=np.asarray(sequences, dtype=str),
        embeddings=np.stack(vectors).astype(np.float32, copy=False),
    )
    print(f"Built embedding cache: {output_path}")


if __name__ == "__main__":
    main()
