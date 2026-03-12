"""Storage helpers for active-learning artifacts."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable


ACTIVE_LEARNING_ROOT = Path("data") / "active_learning"
ACTIVE_LEARNING_SUBDIRS = ("runs", "batches", "wetlab", "datasets")


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return to_jsonable(value.item())
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        try:
            return to_jsonable(value.tolist())
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "__dict__"):
        return to_jsonable(vars(value))
    return str(value)


def write_json(payload: Any, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_jsonl(records: Iterable[dict[str, Any]], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(to_jsonable(record), ensure_ascii=False)
        for record in records
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object per line in {path}")
        records.append(payload)
    return records


def ensure_active_learning_layout(root: str | Path = ACTIVE_LEARNING_ROOT) -> dict[str, Path]:
    base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    layout = {"root": base}
    for name in ACTIVE_LEARNING_SUBDIRS:
        target = base / name
        target.mkdir(parents=True, exist_ok=True)
        layout[name] = target
    layout["active_model"] = base / "active_model.json"
    return layout


def slugify_filename(value: str | None, default: str = "protein_design", max_length: int = 48) -> str:
    text = (value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if not slug:
        return default
    return slug[:max_length].rstrip("_") or default


def timestamped_run_path(
    task: str | None = None,
    *,
    created_at: str | datetime | None = None,
    root: str | Path = ACTIVE_LEARNING_ROOT,
) -> Path:
    layout = ensure_active_learning_layout(root)
    moment = created_at
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    if moment is None:
        moment = datetime.now(timezone.utc)
    stamp = moment.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = slugify_filename(task)
    return layout["runs"] / f"{stamp}_{slug}.json"
