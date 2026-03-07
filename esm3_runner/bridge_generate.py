#!/usr/bin/env python3
import importlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable


def read_payload():
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    return json.loads(raw)


def normalize_variants(raw: Any):
    if isinstance(raw, list):
        return [str(x).strip().upper() for x in raw if str(x).strip()]
    if isinstance(raw, dict):
        for k in ("variants", "sequences", "data"):
            if k in raw:
                return normalize_variants(raw[k])
    if isinstance(raw, tuple) and len(raw) > 0:
        return normalize_variants(raw[0])
    return []


def call_with_flexible_kwargs(fn: Callable[..., Any], payload: dict):
    seq = (payload.get("sequence") or "").strip().upper()
    n = max(1, int(payload.get("num_candidates") or 6))
    required = (payload.get("required_motif") or "").strip().upper()
    forbidden = (payload.get("forbidden_aas") or "").strip().upper()
    round_idx = int(payload.get("round") or 1)

    aliases = {
        "sequence": ["sequence", "seq", "base_sequence", "seed_sequence", "input_sequence"],
        "num_candidates": ["num_candidates", "n", "count", "batch_size", "num_samples"],
        "required_motif": ["required_motif", "motif"],
        "forbidden_aas": ["forbidden_aas", "forbidden", "forbidden_residues"],
        "round": ["round", "round_idx", "iteration", "step"],
    }
    values = {
        "sequence": seq,
        "num_candidates": n,
        "required_motif": required,
        "forbidden_aas": forbidden,
        "round": round_idx,
    }

    sig = inspect.signature(fn)
    kwargs = {}
    for p_name in sig.parameters:
        for logical, keys in aliases.items():
            if p_name in keys:
                kwargs[p_name] = values[logical]
                break

    return fn(**kwargs)


def instantiate_with_flexible_kwargs(cls_obj: Any, module: Any, payload: dict):
    aliases = {
        "model": ["model", "model_name", "name"],
        "device": ["device", "torch_device"],
        "snapshot_dir": ["snapshot_dir", "snapshot", "esm3_snapshot_dir", "weights_dir"],
        "source_path": ["source_path", "esm_source_path", "repo_path"],
        "data_path": ["data_path", "local_data_path"],
    }
    values = {
        "model": os.environ.get("ESM3_MODEL", "").strip() or payload.get("model") or "",
        "device": os.environ.get("ESM3_DEVICE", "").strip(),
        "snapshot_dir": getattr(module, "ESM3_SNAPSHOT_DIR", None),
        "source_path": getattr(module, "ESM_SOURCE_PATH", None),
        "data_path": getattr(module, "LOCAL_DATA_PATH", None),
    }

    sig = inspect.signature(cls_obj)
    kwargs = {}
    for p_name, p in sig.parameters.items():
        if p_name == "self" or p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        for logical, keys in aliases.items():
            if p_name in keys:
                val = values[logical]
                if val is not None and not (isinstance(val, str) and not val):
                    kwargs[p_name] = val
                break

    return cls_obj(**kwargs)


def build_candidates(module: Any, entrypoint: str, payload: dict):
    candidates: list[tuple[str, Callable[..., Any]]] = []
    instantiate_errors: list[str] = []

    if entrypoint and hasattr(module, entrypoint):
        obj = getattr(module, entrypoint)
        if callable(obj):
            candidates.append((f"utils.esm_wrapper.{entrypoint}", obj))

    for name in ["generate_variants", "generate_sequences", "generate", "run_generation", "design"]:
        if hasattr(module, name):
            obj = getattr(module, name)
            if callable(obj):
                candidates.append((f"utils.esm_wrapper.{name}", obj))

    for cls_name in ["ESMWrapper", "ESM3Wrapper", "ESM3Generator", "Generator", "Designer"]:
        if hasattr(module, cls_name):
            cls_obj = getattr(module, cls_name)
            if not callable(cls_obj):
                continue
            instance = None
            ctor_attempts = [
                ("flex",),
                (),
                (getattr(module, "ESM3_SNAPSHOT_DIR", None),),
                (getattr(module, "ESM_SOURCE_PATH", None),),
            ]
            for args in ctor_attempts:
                try:
                    if args == ("flex",):
                        instance = instantiate_with_flexible_kwargs(cls_obj, module, payload)
                    else:
                        args = tuple(a for a in args if a is not None)
                        instance = cls_obj(*args)
                    break
                except Exception as e:  # noqa: BLE001
                    instantiate_errors.append(f"{cls_name} ctor args={args}: {e}")
                    continue
            if instance is None:
                continue
            for method in ["generate_variants", "generate_sequences", "generate", "run_generation", "design", "__call__"]:
                if hasattr(instance, method):
                    fn = getattr(instance, method)
                    if callable(fn):
                        candidates.append((f"utils.esm_wrapper.{cls_name}().{method}", fn))

    # Auto-discover any class that exposes generation-like methods.
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        obj = getattr(module, attr_name)
        if not inspect.isclass(obj):
            continue
        if attr_name in {"ESMWrapper", "ESM3Wrapper", "ESM3Generator", "Generator", "Designer"}:
            continue
        method_names = [
            m
            for m in dir(obj)
            if ("generate" in m.lower() or m.lower() in {"design", "run"}) and not m.startswith("_")
        ]
        if not method_names:
            continue
        instance = None
        for args in [("flex",), (), (getattr(module, "ESM3_SNAPSHOT_DIR", None),)]:
            try:
                if args == ("flex",):
                    instance = instantiate_with_flexible_kwargs(obj, module, payload)
                else:
                    args = tuple(a for a in args if a is not None)
                    instance = obj(*args)
                break
            except Exception as e:  # noqa: BLE001
                instantiate_errors.append(f"{attr_name} ctor args={args}: {e}")
                continue
        if instance is None:
            continue
        for method in method_names:
            fn = getattr(instance, method, None)
            if callable(fn):
                candidates.append((f"utils.esm_wrapper.{attr_name}().{method}", fn))

    # de-dup by name preserving order
    seen = set()
    out = []
    for name, fn in candidates:
        if name in seen:
            continue
        seen.add(name)
        out.append((name, fn))
    return out, instantiate_errors


def main():
    payload = read_payload()
    seq = (payload.get("sequence") or "").strip().upper()
    if not seq:
        print(json.dumps({"error": "empty sequence"}))
        return

    script_dir = os.environ.get("ESM3_SCRIPT_DIR", "").strip()
    entrypoint = os.environ.get("ESM3_ENTRYPOINT", "").strip()
    if script_dir:
        sys.path.insert(0, script_dir)
        sys.path.insert(0, str(Path(script_dir) / "utils"))

    try:
        module = importlib.import_module("utils.esm_wrapper")
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"cannot import utils.esm_wrapper from script_dir: {e}"}))
        return

    candidates, instantiate_errors = build_candidates(module, entrypoint, payload)
    if not candidates:
        available = [x for x in dir(module) if not x.startswith("_")][:80]
        generation_related = [x for x in available if "generate" in x.lower() or "design" in x.lower() or "esm3" in x.lower()]
        print(
            json.dumps(
                {
                    "error": "no callable generation entry found in utils.esm_wrapper",
                    "available_symbols": available,
                    "generation_related_symbols": generation_related,
                    "instantiate_errors": instantiate_errors[:12],
                }
            )
        )
        return

    errors = []
    for name, fn in candidates:
        try:
            raw = call_with_flexible_kwargs(fn, payload)
            variants = normalize_variants(raw)
            if variants:
                print(json.dumps({"variants": variants, "entrypoint_used": name}))
                return
            errors.append(f"{name}: returned empty")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")

    print(json.dumps({"error": "all esm_wrapper entrypoints failed", "attempts": errors[:12]}))


if __name__ == "__main__":
    main()
