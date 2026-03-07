#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path


def read_payload():
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    return json.loads(raw)


def main():
    payload = read_payload()
    seq = (payload.get("sequence") or "").strip().upper()
    if not seq:
        print(json.dumps({"error": "empty sequence"}))
        return

    n = max(1, int(payload.get("num_candidates") or 6))
    required = (payload.get("required_motif") or "").strip().upper()
    forbidden = (payload.get("forbidden_aas") or "").strip().upper()
    round_idx = int(payload.get("round") or 1)

    script_dir = os.environ.get("ESM3_SCRIPT_DIR", "").strip()
    if script_dir:
        sys.path.insert(0, script_dir)
        sys.path.insert(0, str(Path(script_dir) / "utils"))

    try:
        from utils import esm_wrapper  # type: ignore
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"cannot import utils.esm_wrapper from script_dir: {e}"}))
        return

    if not hasattr(esm_wrapper, "generate_variants"):
        print(json.dumps({"error": "utils.esm_wrapper.generate_variants not found"}))
        return

    try:
        variants = esm_wrapper.generate_variants(
            sequence=seq,
            num_candidates=n,
            required_motif=required,
            forbidden_aas=forbidden,
            round_idx=round_idx,
        )
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"generate_variants execution failed: {e}"}))
        return

    if not isinstance(variants, list) or len(variants) == 0:
        print(json.dumps({"error": "generate_variants returned empty"}))
        return

    print(json.dumps({"variants": variants}))


if __name__ == "__main__":
    main()
