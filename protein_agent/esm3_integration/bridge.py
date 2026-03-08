#!/usr/bin/env python3
"""Flexible bridge for locally deployed ESM3 environments."""
from __future__ import annotations

import importlib
import importlib.util
import io
import inspect
import json
import os
import random
import sys
from pathlib import Path
from typing import Any, Callable


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    return json.loads(raw)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str))


def configure_paths() -> None:
    root_text = os.environ.get("PROTEIN_AGENT_ESM3_ROOT", "").strip()
    project_text = os.environ.get("PROTEIN_AGENT_ESM3_PROJECT_DIR", "").strip()
    root = Path(root_text) if root_text else None
    project = Path(project_text) if project_text else None
    extra = os.environ.get("PROTEIN_AGENT_ESM3_EXTRA_PYTHONPATH", "").strip()

    candidates: list[Path] = []
    if root is not None:
        candidates.extend([root, root / "esm", root / "projects"])
    if project is not None:
        candidates.extend([project, project / "scripts", project.parent])
    if extra:
        for item in extra.split(os.pathsep):
            if item.strip():
                candidates.append(Path(item.strip()))

    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate)
        if not text or text in seen or not candidate.exists():
            continue
        seen.add(text)
        sys.path.insert(0, text)


def normalize_sequences(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        seq = raw.strip().upper()
        return [seq] if seq else []
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            out.extend(normalize_sequences(item))
        return out
    if isinstance(raw, tuple):
        return normalize_sequences(list(raw))
    if isinstance(raw, dict):
        for key in ("variants", "sequences", "data", "items", "results"):
            if key in raw:
                return normalize_sequences(raw[key])
        if "sequence" in raw:
            return normalize_sequences(raw["sequence"])
    if hasattr(raw, "sequence"):
        return normalize_sequences(getattr(raw, "sequence"))
    return []


def first_non_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        item = value.item() if hasattr(value, "item") else value
        return float(item)
    except Exception:  # noqa: BLE001
        return default


def serialize_structure(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    if hasattr(value, "shape"):
        shape = getattr(value, "shape", None)
        try:
            shape = list(shape) if shape is not None else None
        except Exception:  # noqa: BLE001
            shape = str(shape)
        return {
            "type": value.__class__.__name__,
            "shape": shape,
        }
    return str(value)


def normalize_structure(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        structure = raw.get("structure", raw)
        confidence = to_float(first_non_none(raw.get("confidence"), raw.get("plddt")), 0.0)
        return {"structure": serialize_structure(structure), "confidence": confidence}
    structure = getattr(raw, "structure", None)
    confidence = to_float(first_non_none(getattr(raw, "confidence", None), getattr(raw, "plddt", None)), 0.0)
    return {"structure": serialize_structure(structure), "confidence": confidence}


def build_values(payload: dict[str, Any]) -> dict[str, Any]:
    model_name = (
        payload.get("model")
        or os.environ.get("PROTEIN_AGENT_ESM3_MODEL_NAME", "").strip()
        or "esm3-open"
    )
    source_path = os.environ.get("PROTEIN_AGENT_ESM3_ROOT", "").strip() or None
    weights_dir = os.environ.get("PROTEIN_AGENT_ESM3_WEIGHTS_DIR", "").strip() or None
    data_dir = os.environ.get("PROTEIN_AGENT_ESM3_DATA_DIR", "").strip() or None
    if not weights_dir and source_path:
        candidate = Path(source_path) / "weights"
        if candidate.exists():
            weights_dir = str(candidate)
    if not data_dir and source_path:
        candidate = Path(source_path) / "data"
        if candidate.exists():
            data_dir = str(candidate)
    return {
        "prompt": payload.get("prompt") or payload.get("task") or payload.get("sequence") or "",
        "task": payload.get("task") or payload.get("prompt") or "",
        "sequence": (payload.get("sequence") or payload.get("prompt") or "").strip().upper(),
        "sequence_length": int(payload.get("sequence_length") or 0),
        "num_candidates": max(1, int(payload.get("num_candidates") or 4)),
        "temperature": float(payload.get("temperature") or 0.8),
        "num_mutations": max(1, int(payload.get("num_mutations") or 3)),
        "track": payload.get("track") or "structure",
        "num_steps": int(payload.get("num_steps") or 1),
        "pdb_path": (payload.get("pdb_path") or "").strip(),
        "pdb_text": payload.get("pdb_text") or "",
        "function_annotations": payload.get("function_annotations") or [],
        "function_keywords": payload.get("function_keywords") or [],
        "model": model_name,
        "model_name": model_name,
        "name": model_name,
        "device": os.environ.get("PROTEIN_AGENT_ESM3_DEVICE", "").strip() or None,
        "weights_dir": weights_dir,
        "snapshot_dir": weights_dir,
        "checkpoint_dir": weights_dir,
        "data_dir": data_dir,
        "data_path": data_dir,
        "source_path": source_path,
        "project_dir": os.environ.get("PROTEIN_AGENT_ESM3_PROJECT_DIR", "").strip() or None,
    }


def canonical_model_name(model_name: str) -> str:
    raw = (model_name or "").strip()
    if not raw:
        return "esm3_sm_open_v1"

    try:
        constants = importlib.import_module("esm.utils.constants.models")
        normalize = getattr(constants, "normalize_model_name", None)
        if callable(normalize):
            return str(normalize(raw))
    except Exception:  # noqa: BLE001
        pass

    lowered = raw.lower().replace("-", "_")
    aliases = {
        "esm3_open": "esm3_sm_open_v1",
        "esm3_open_small": "esm3_sm_open_v1",
        "esm3_sm_open": "esm3_sm_open_v1",
        "esm3_sm_open_v1": "esm3_sm_open_v1",
    }
    return aliases.get(lowered, raw)


ALIASES = {
    "prompt": {"prompt", "task", "instruction", "text", "query"},
    "sequence": {"sequence", "seq", "base_sequence", "seed_sequence", "input_sequence"},
    "num_candidates": {"num_candidates", "n", "count", "batch_size", "num_samples", "samples"},
    "temperature": {"temperature", "temp"},
    "num_mutations": {"num_mutations", "mutations", "mutation_count", "k"},
    "track": {"track"},
    "num_steps": {"num_steps", "steps", "iterations"},
    "model": {"model", "model_name", "name"},
    "device": {"device", "torch_device"},
    "weights_dir": {"weights_dir", "snapshot_dir", "checkpoint_dir", "checkpoint_path"},
    "data_dir": {"data_dir", "data_path", "local_data_path"},
    "source_path": {"source_path", "repo_path", "root_path"},
    "project_dir": {"project_dir", "script_dir", "workdir"},
}


def kwarg_value(param_name: str, values: dict[str, Any]) -> tuple[bool, Any]:
    if param_name in values:
        value = values[param_name]
        if value is not None and value != "":
            return True, value
    lower = param_name.lower()
    for logical, aliases in ALIASES.items():
        if lower in aliases:
            value = values.get(logical)
            if value is not None and value != "":
                return True, value
    return False, None


def invoke_flex(fn: Callable[..., Any], values: dict[str, Any], operation: str) -> Any:
    sig = inspect.signature(fn)
    kwargs: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name in {"self", "cls"}:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        found, value = kwarg_value(name, values)
        if found:
            kwargs[name] = value

    attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    if kwargs:
        attempts.append(((), kwargs))
    if operation == "load_model":
        attempts.extend([((values["model"],), {}), ((), {})])
    elif operation == "generate":
        attempts.extend(
            [
                ((values["prompt"], values["num_candidates"], values["temperature"]), {}),
                ((values["sequence"], values["num_candidates"], values["temperature"]), {}),
                ((values["prompt"],), {}),
                ((values["sequence"],), {}),
            ]
        )
    elif operation == "mutate":
        attempts.extend(
            [
                ((values["sequence"], values["num_mutations"], values["num_candidates"]), {}),
                ((values["sequence"], values["num_mutations"]), {}),
                ((values["sequence"],), {}),
            ]
        )
    elif operation == "predict_structure":
        attempts.extend(
            [
                ((values["sequence"],), {}),
                ((), {"sequence": values["sequence"], "track": "structure", "num_steps": 1}),
            ]
        )

    seen: set[tuple[tuple[Any, ...], tuple[tuple[str, Any], ...]]] = set()
    errors: list[str] = []
    for args, extra_kwargs in attempts:
        key = (args, tuple(sorted(extra_kwargs.items())))
        if key in seen:
            continue
        seen.add(key)
        try:
            return fn(*args, **extra_kwargs)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue

    detail = " | ".join(errors[:6]) if errors else "no invocation strategy matched"
    raise RuntimeError(f"unable to invoke callable for {operation}: {detail}")


def load_module_from_spec(spec: str) -> Any:
    if ":" in spec and spec.split(":", 1)[0].endswith(".py"):
        path_text, _ = spec.split(":", 1)
    else:
        path_text = spec
    path = Path(path_text)
    if not path.exists():
        raise FileNotFoundError(path)
    module_name = path.stem + "_runtime"
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def operation_names(operation: str) -> list[str]:
    mapping = {
        "generate": [
            "generate_variants",
            "generate_sequences",
            "generate_sequence",
            "generate",
            "run_generation",
            "design",
            "sample",
            "propose",
        ],
        "mutate": [
            "mutate_sequence",
            "mutate",
            "generate_mutations",
            "propose_mutations",
            "refine",
            "design",
        ],
        "predict_structure": [
            "predict_structure",
            "infer_structure",
            "fold",
            "predict",
            "generate",
        ],
    }
    return mapping.get(operation, [])


def resolve_callable(spec: str, operation: str) -> Callable[..., Any]:
    if not spec:
        raise RuntimeError("empty entrypoint spec")
    if spec.endswith(".py") or ".py:" in spec:
        module = load_module_from_spec(spec)
        attr = spec.split(":", 1)[1] if ":" in spec else ""
        if attr:
            obj = getattr(module, attr)
            if callable(obj):
                return obj
            raise RuntimeError(f"attribute '{attr}' is not callable")
        for name in operation_names(operation):
            obj = getattr(module, name, None)
            if callable(obj):
                return obj
        raise RuntimeError(f"no callable entrypoint found in {spec}")

    if ":" in spec:
        module_name, attr = spec.split(":", 1)
        module = importlib.import_module(module_name)
        obj = getattr(module, attr)
        if callable(obj):
            return obj
        raise RuntimeError(f"attribute '{attr}' is not callable")

    module = importlib.import_module(spec)
    for name in operation_names(operation):
        obj = getattr(module, name, None)
        if callable(obj):
            return obj
    raise RuntimeError(f"no callable entrypoint found in module '{spec}'")


def collect_module_callables(module: Any, operation: str) -> list[tuple[str, Callable[..., Any]]]:
    names = operation_names(operation)
    candidates: list[tuple[str, Callable[..., Any]]] = []
    for name in names:
        obj = getattr(module, name, None)
        if callable(obj):
            candidates.append((f"{module.__name__}.{name}", obj))
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        obj = getattr(module, attr_name)
        if not inspect.isclass(obj):
            continue
        instance = None
        for args in [(), (build_values({})["model"],)]:
            try:
                instance = obj(*args)
                break
            except Exception:  # noqa: BLE001
                continue
        if instance is None:
            continue
        for name in names:
            fn = getattr(instance, name, None)
            if callable(fn):
                candidates.append((f"{module.__name__}.{attr_name}().{name}", fn))
    return candidates


def try_wrapper_modules(operation: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    modules = ["utils.esm_wrapper", "esm_wrapper"]
    errors: list[str] = []
    values = build_values(payload)
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{module_name}: {exc}")
            continue
        for name, fn in collect_module_callables(module, operation):
            try:
                raw = invoke_flex(fn, values, operation)
                if operation == "predict_structure":
                    return {**normalize_structure(raw), "entrypoint_used": name}
                sequences = normalize_sequences(raw)
                if sequences:
                    return {"sequences": sequences, "entrypoint_used": name}
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
                continue
    if errors:
        return {"error": "all wrapper-module entrypoints failed", "attempts": errors[:12]}
    return None


def finalize_model(model: Any, values: dict[str, Any]) -> Any:
    device = values.get("device")
    if device and hasattr(model, "to"):
        try:
            model = model.to(device)
        except Exception:  # noqa: BLE001
            pass
    if hasattr(model, "eval"):
        try:
            model.eval()
        except Exception:  # noqa: BLE001
            pass
    return model


def local_weight_files(values: dict[str, Any]) -> dict[str, Path]:
    weights_dir_text = values.get("weights_dir") or ""
    if not weights_dir_text:
        return {}
    weights_dir = Path(weights_dir_text)
    files = {
        "model": weights_dir / "esm3_sm_open_v1.pth",
        "structure_encoder": weights_dir / "esm3_structure_encoder_v0.pth",
        "structure_decoder": weights_dir / "esm3_structure_decoder_v0.pth",
        "function_decoder": weights_dir / "esm3_function_decoder_v0.pth",
    }
    return files


def build_local_open_small_model(values: dict[str, Any]) -> Any:
    canonical = canonical_model_name(str(values.get("model") or ""))
    if canonical != "esm3_sm_open_v1":
        raise RuntimeError(f"manual local loader only supports esm3_sm_open_v1, got {canonical}")

    files = local_weight_files(values)
    if not files:
        raise RuntimeError("weights_dir is not configured")
    missing = [str(path) for path in files.values() if not path.exists()]
    if missing:
        raise RuntimeError("missing local weight files: " + ", ".join(missing))

    try:
        import torch
        from esm.models.esm3 import ESM3
        from esm.models.function_decoder import FunctionTokenDecoder
        from esm.models.vqvae import StructureTokenDecoder, StructureTokenEncoder
        from esm.tokenization import get_esm3_model_tokenizers
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"failed to import local ESM3 components: {exc}") from exc

    source_root = Path(values.get("source_path") or "") if values.get("source_path") else None
    weights_dir = values.get("weights_dir") or ""
    data_dir = values.get("data_dir") or ""
    previous_provider = os.environ.get("INFRA_PROVIDER")
    previous_source = os.environ.get("ESM_SOURCE_PATH")
    previous_snapshot = os.environ.get("ESM3_SNAPSHOT_DIR")
    previous_data = os.environ.get("LOCAL_DATA_PATH")
    try:
        if source_root is not None and source_root.exists():
            os.chdir(source_root)
        os.environ["INFRA_PROVIDER"] = previous_provider or "local"
        if source_root is not None and source_root.exists():
            os.environ["ESM_SOURCE_PATH"] = str(source_root)
        if weights_dir:
            os.environ["ESM3_SNAPSHOT_DIR"] = str(weights_dir)
        if data_dir:
            os.environ["LOCAL_DATA_PATH"] = str(data_dir)
        tokenizers = get_esm3_model_tokenizers(canonical)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"failed to load tokenizers from local repo/data: {exc}") from exc
    finally:
        if previous_provider is None:
            os.environ.pop("INFRA_PROVIDER", None)
        else:
            os.environ["INFRA_PROVIDER"] = previous_provider
        if previous_source is None:
            os.environ.pop("ESM_SOURCE_PATH", None)
        else:
            os.environ["ESM_SOURCE_PATH"] = previous_source
        if previous_snapshot is None:
            os.environ.pop("ESM3_SNAPSHOT_DIR", None)
        else:
            os.environ["ESM3_SNAPSHOT_DIR"] = previous_snapshot
        if previous_data is None:
            os.environ.pop("LOCAL_DATA_PATH", None)
        else:
            os.environ["LOCAL_DATA_PATH"] = previous_data

    if source_root is not None and source_root.exists():
        os.chdir(source_root)
        os.environ["ESM_SOURCE_PATH"] = str(source_root)
    if weights_dir:
        os.environ["ESM3_SNAPSHOT_DIR"] = str(weights_dir)
    if data_dir:
        os.environ["LOCAL_DATA_PATH"] = str(data_dir)
    os.environ.setdefault("INFRA_PROVIDER", "local")

    def structure_encoder_fn(device: Any) -> Any:
        model = StructureTokenEncoder(
            d_model=1024,
            n_heads=1,
            v_heads=128,
            n_layers=2,
            d_out=128,
            n_codes=4096,
        )
        model.load_state_dict(torch.load(files["structure_encoder"], map_location="cpu"))
        model = model.to(device)
        model.eval()
        return model

    def structure_decoder_fn(device: Any) -> Any:
        model = StructureTokenDecoder(d_model=1280, n_heads=20, n_layers=30)
        model.load_state_dict(torch.load(files["structure_decoder"], map_location="cpu"))
        model = model.to(device)
        model.eval()
        return model

    def function_decoder_fn(device: Any) -> Any:
        model = FunctionTokenDecoder()
        model.load_state_dict(torch.load(files["function_decoder"], map_location="cpu"))
        model = model.to(device)
        model.eval()
        return model

    model = ESM3(
        d_model=1536,
        n_heads=24,
        v_heads=256,
        n_layers=48,
        structure_encoder_fn=structure_encoder_fn,
        structure_decoder_fn=structure_decoder_fn,
        function_decoder_fn=function_decoder_fn,
        tokenizers=tokenizers,
    ).eval()
    model.load_state_dict(torch.load(files["model"], map_location="cpu"))
    return finalize_model(model, {**values, "model": canonical, "model_name": canonical, "name": canonical})


def load_direct_model(payload: dict[str, Any]) -> Any:
    values = build_values(payload)
    values = {**values, "model": canonical_model_name(str(values.get("model") or "")), "model_name": canonical_model_name(str(values.get("model") or "")), "name": canonical_model_name(str(values.get("model") or ""))}
    errors: list[str] = []
    try:
        module = importlib.import_module("esm.models.esm3")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"cannot import esm.models.esm3: {exc}") from exc

    esm3_cls = getattr(module, "ESM3", None)
    if esm3_cls is None:
        raise RuntimeError("esm.models.esm3 does not export ESM3")

    try:
        return build_local_open_small_model(values)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"manual local loader: {exc}")

    factories: list[tuple[str, Callable[..., Any], str]] = []

    try:
        pretrained_module = importlib.import_module("esm.pretrained")
    except Exception:  # noqa: BLE001
        pretrained_module = None
    if pretrained_module is not None:
        load_local_model = getattr(pretrained_module, "load_local_model", None)
        if callable(load_local_model):
            factories.append(("esm.pretrained.load_local_model", load_local_model, "load_model"))

    from_pretrained = getattr(esm3_cls, "from_pretrained", None)
    if callable(from_pretrained):
        factories.append(("ESM3.from_pretrained", from_pretrained, "load_model"))

    for name, factory, operation in factories:
        try:
            model = invoke_flex(factory, values, operation)
            return finalize_model(model, values)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            continue
    raise RuntimeError(" | ".join(errors[:12]) if errors else "no model factory available")


def mask_sequence(sequence: str, count: int) -> str:
    seq = list((sequence or "").strip().upper())
    if not seq:
        return ""
    indices = [i for i, aa in enumerate(seq) if aa.isalpha()]
    if not indices:
        return "".join(seq)
    count = max(1, min(count, len(indices)))
    for idx in random.sample(indices, count):
        seq[idx] = "_"
    return "".join(seq)


def sdk_generate_sequence(model: Any, prompt_sequence: str, temperature: float, num_steps: int) -> str:
    from esm.sdk.api import ESMProtein, GenerationConfig

    protein = ESMProtein(sequence=prompt_sequence)
    config = GenerationConfig(
        track="sequence",
        num_steps=max(1, num_steps),
        temperature=float(temperature),
    )
    result = model.generate(protein, config)
    sequence = getattr(result, "sequence", None)
    if not sequence:
        raise RuntimeError("sdk generate returned empty sequence")
    return str(sequence).strip().upper()


def build_function_annotations(values: dict[str, Any]) -> list[Any]:
    from esm.sdk.api import FunctionAnnotation

    annotations: list[Any] = []
    sequence_length = int(values.get("sequence_length") or 0)
    base_sequence = values.get("sequence") or ""
    if sequence_length <= 0:
        sequence_length = len(base_sequence) if base_sequence else 128

    for item in values.get("function_annotations") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()
        if not label:
            continue
        start = int(item.get("start") or 1)
        end = int(item.get("end") or sequence_length)
        annotations.append(FunctionAnnotation(label=label, start=min(start, end), end=max(start, end)))

    for keyword in values.get("function_keywords") or []:
        label = str(keyword).strip()
        if not label:
            continue
        annotations.append(FunctionAnnotation(label=label, start=1, end=sequence_length))
    return annotations


def base_sequence_for_function(values: dict[str, Any]) -> str:
    sequence = (values.get("sequence") or "").strip().upper()
    if sequence:
        if "_" in sequence:
            return sequence
        return mask_sequence(sequence, max(1, len(sequence) // 5))

    sequence_length = int(values.get("sequence_length") or 0)
    if sequence_length <= 0:
        sequence_length = 128
    return "_" * sequence_length


def sdk_generate_with_function(model: Any, values: dict[str, Any]) -> list[str]:
    from esm.sdk.api import ESMProtein, GenerationConfig

    annotations = build_function_annotations(values)
    if not annotations:
        raise RuntimeError("function-conditioned generation requires function_annotations or function_keywords")

    prompt_sequence = base_sequence_for_function(values)
    sequences: list[str] = []
    for _ in range(values["num_candidates"]):
        protein = ESMProtein(sequence=prompt_sequence, function_annotations=annotations)
        config = GenerationConfig(
            track="sequence",
            num_steps=max(values["num_steps"], prompt_sequence.count("_"), 1),
            temperature=float(values["temperature"]),
        )
        result = model.generate(protein, config)
        sequence = getattr(result, "sequence", None)
        if not sequence:
            raise RuntimeError("function-conditioned generation returned empty sequence")
        sequences.append(str(sequence).strip().upper())
    return sequences


def sdk_inverse_fold(model: Any, values: dict[str, Any]) -> list[str]:
    from esm.sdk.api import ESMProtein, GenerationConfig

    pdb_path = values.get("pdb_path") or ""
    pdb_text = values.get("pdb_text") or ""

    if pdb_path:
        protein = ESMProtein.from_pdb(pdb_path)
    elif pdb_text:
        protein = ESMProtein.from_pdb(io.StringIO(pdb_text))
    else:
        raise RuntimeError("inverse folding requires pdb_path or pdb_text")

    protein.sequence = None
    sequences: list[str] = []
    for _ in range(values["num_candidates"]):
        config = GenerationConfig(
            track="sequence",
            num_steps=max(values["num_steps"], 1),
            temperature=float(values["temperature"]),
        )
        result = model.generate(protein, config)
        sequence = getattr(result, "sequence", None)
        if not sequence:
            raise RuntimeError("inverse folding returned empty sequence")
        sequences.append(str(sequence).strip().upper())
    return sequences


def sdk_predict_structure(model: Any, sequence: str, num_steps: int) -> dict[str, Any]:
    from esm.sdk.api import ESMProtein, GenerationConfig

    protein = ESMProtein(sequence=sequence)
    config = GenerationConfig(track="structure", num_steps=max(1, num_steps))
    result = model.generate(protein, config)
    structure = first_non_none(getattr(result, "coordinates", None), getattr(result, "structure", None))
    confidence = first_non_none(getattr(result, "ptm", None), getattr(result, "confidence", None))
    return {
        "structure": serialize_structure(structure),
        "confidence": to_float(confidence, 0.0),
    }


def generate_with_model(model: Any, payload: dict[str, Any]) -> dict[str, Any]:
    values = build_values(payload)
    try:
        sequences: list[str] = []
        base = values["sequence"] or values["prompt"]
        if not base:
            raise RuntimeError("empty prompt sequence")
        for _ in range(values["num_candidates"]):
            prompt_sequence = base if "_" in base else mask_sequence(base, max(1, len(base) // 20))
            sequence = sdk_generate_sequence(
                model,
                prompt_sequence=prompt_sequence,
                temperature=values["temperature"],
                num_steps=max(values["num_steps"], prompt_sequence.count("_")),
            )
            sequences.append(sequence)
        if sequences:
            return {"sequences": sequences, "entrypoint_used": "esm_sdk.generate(sequence)"}
    except Exception as exc:  # noqa: BLE001
        errors: list[str] = [f"esm_sdk.generate: {exc}"]
    else:
        errors = []

    for method_name in ["generate_sequences", "generate_sequence", "generate", "sample", "design", "predict"]:
        fn = getattr(model, method_name, None)
        if not callable(fn):
            continue
        try:
            raw = invoke_flex(fn, values, "generate")
            sequences = normalize_sequences(raw)
            if sequences:
                return {"sequences": sequences, "entrypoint_used": f"model.{method_name}"}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{method_name}: {exc}")
            continue
    raise RuntimeError(" | ".join(errors[:12]) if errors else "model exposes no generation method")


def mutate_with_model(model: Any, payload: dict[str, Any]) -> dict[str, Any]:
    values = build_values(payload)
    sequence = values["sequence"]
    if sequence:
        try:
            generated: list[str] = []
            for _ in range(values["num_candidates"]):
                prompt_sequence = mask_sequence(sequence, values["num_mutations"])
                generated.append(
                    sdk_generate_sequence(
                        model,
                        prompt_sequence=prompt_sequence,
                        temperature=max(values["temperature"], 0.9),
                        num_steps=max(values["num_steps"], values["num_mutations"]),
                    )
                )
            if generated:
                return {"sequences": generated, "entrypoint_used": "esm_sdk.masked_mutation"}
        except Exception as exc:  # noqa: BLE001
            errors: list[str] = [f"esm_sdk.masked_mutation: {exc}"]
    else:
        errors = []

    for method_name in ["mutate_sequence", "mutate", "generate_mutations", "design"]:
        fn = getattr(model, method_name, None)
        if not callable(fn):
            continue
        try:
            raw = invoke_flex(fn, values, "mutate")
            sequences = normalize_sequences(raw)
            if sequences:
                return {"sequences": sequences, "entrypoint_used": f"model.{method_name}"}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{method_name}: {exc}")
            continue

    sequence = values["sequence"]
    if not sequence:
        raise RuntimeError("sequence is empty")
    amino_acids = "ACDEFGHIKLMNPQRSTVWY"
    generated: list[str] = []
    for _ in range(values["num_candidates"]):
        mutated = list(sequence)
        for _ in range(values["num_mutations"]):
            idx = random.randrange(len(mutated))
            mutated[idx] = random.choice(amino_acids)
        prompt = "".join(mutated)
        out = generate_with_model(model, {**payload, "prompt": prompt, "sequence": prompt, "num_candidates": 1})
        generated.extend(out.get("sequences", []))
    if generated:
        return {"sequences": generated[: values["num_candidates"]], "entrypoint_used": "model.random_mutation_then_generate"}
    raise RuntimeError("mutation fallback produced no sequences; attempts=" + " | ".join(errors[:12]))


def structure_with_model(model: Any, payload: dict[str, Any]) -> dict[str, Any]:
    values = build_values(payload)
    try:
        return {**sdk_predict_structure(model, values["sequence"], max(values["num_steps"], 1)), "entrypoint_used": "esm_sdk.generate(structure)"}
    except Exception as exc:  # noqa: BLE001
        errors: list[str] = [f"esm_sdk.generate(structure): {exc}"]

    for method_name in ["predict_structure", "infer_structure", "fold", "predict"]:
        fn = getattr(model, method_name, None)
        if not callable(fn):
            continue
        try:
            raw = invoke_flex(fn, values, "predict_structure")
            return {**normalize_structure(raw), "entrypoint_used": f"model.{method_name}"}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{method_name}: {exc}")
            continue

    generate = getattr(model, "generate", None)
    if callable(generate):
        try:
            raw = generate(values["sequence"], track="structure", num_steps=1)
            return {**normalize_structure(raw), "entrypoint_used": "model.generate(track=structure)"}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"generate(track=structure): {exc}")

    raise RuntimeError(" | ".join(errors[:12]) if errors else "model exposes no structure method")


def inverse_fold_with_model(model: Any, payload: dict[str, Any]) -> dict[str, Any]:
    values = build_values(payload)
    try:
        return {"sequences": sdk_inverse_fold(model, values), "entrypoint_used": "esm_sdk.inverse_fold"}
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"esm_sdk.inverse_fold: {exc}") from exc


def function_conditioned_generate_with_model(model: Any, payload: dict[str, Any]) -> dict[str, Any]:
    values = build_values(payload)
    try:
        return {
            "sequences": sdk_generate_with_function(model, values),
            "function_annotations": values.get("function_annotations") or values.get("function_keywords") or [],
            "entrypoint_used": "esm_sdk.function_conditioned_generate",
        }
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"esm_sdk.function_conditioned_generate: {exc}") from exc


def env_entrypoint(operation: str) -> str:
    mapping = {
        "generate": "PROTEIN_AGENT_ESM3_GENERATE_ENTRYPOINT",
        "mutate": "PROTEIN_AGENT_ESM3_MUTATE_ENTRYPOINT",
        "predict_structure": "PROTEIN_AGENT_ESM3_STRUCTURE_ENTRYPOINT",
        "inverse_fold": "PROTEIN_AGENT_ESM3_INVERSE_FOLD_ENTRYPOINT",
        "generate_with_function": "PROTEIN_AGENT_ESM3_FUNCTION_GENERATE_ENTRYPOINT",
    }
    return os.environ.get(mapping[operation], "").strip()


def main() -> None:
    configure_paths()
    payload = read_payload()
    operation = (payload.get("operation") or "").strip()
    if operation not in {"generate", "mutate", "predict_structure", "inverse_fold", "generate_with_function"}:
        emit({"error": f"unsupported operation: {operation}"})
        return

    entrypoint = env_entrypoint(operation)
    values = build_values(payload)

    if operation in {"mutate", "predict_structure"} and not values["sequence"]:
        emit({"error": "sequence is required"})
        return
    if operation == "generate" and not (values["prompt"] or values["sequence"]):
        emit({"error": "prompt or sequence is required"})
        return
    if operation == "inverse_fold" and not (values["pdb_path"] or values["pdb_text"]):
        emit({"error": "inverse folding requires pdb_path or pdb_text"})
        return
    if operation == "generate_with_function" and not (values["function_annotations"] or values["function_keywords"]):
        emit({"error": "function-conditioned generation requires function_annotations or function_keywords"})
        return

    if entrypoint:
        try:
            fn = resolve_callable(entrypoint, operation)
            raw = invoke_flex(fn, values, operation)
            if operation == "predict_structure":
                emit({**normalize_structure(raw), "entrypoint_used": entrypoint})
            else:
                emit({"sequences": normalize_sequences(raw), "entrypoint_used": entrypoint})
            return
        except Exception as exc:  # noqa: BLE001
            emit({"error": f"custom entrypoint failed: {exc}"})
            return

    wrapper_result = try_wrapper_modules(operation, payload)
    if wrapper_result and not wrapper_result.get("error"):
        emit(wrapper_result)
        return

    try:
        model = load_direct_model(payload)
    except Exception as exc:  # noqa: BLE001
        detail = {"error": f"failed to load local ESM3 model: {exc}"}
        if wrapper_result and wrapper_result.get("error"):
            detail["wrapper_error"] = wrapper_result["error"]
            if wrapper_result.get("attempts"):
                detail["wrapper_attempts"] = wrapper_result["attempts"]
        emit(detail)
        return

    try:
        if operation == "generate":
            emit(generate_with_model(model, payload))
        elif operation == "mutate":
            emit(mutate_with_model(model, payload))
        elif operation == "inverse_fold":
            emit(inverse_fold_with_model(model, payload))
        elif operation == "generate_with_function":
            emit(function_conditioned_generate_with_model(model, payload))
        else:
            emit(structure_with_model(model, payload))
    except Exception as exc:  # noqa: BLE001
        emit({"error": f"local ESM3 {operation} failed: {exc}"})


if __name__ == "__main__":
    main()
