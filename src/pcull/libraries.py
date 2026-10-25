"""Recently opened photo libraries, persisted in ~/.pcull/libraries.json."""
from __future__ import annotations

import json
import time
from pathlib import Path

RECENT_FILE = Path.home() / ".pcull" / "libraries.json"
MAX_RECENT = 12


def load() -> list[dict]:
    try:
        data = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
        return [d for d in data if isinstance(d, dict) and d.get("path")]
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECENT_FILE.write_text(
        json.dumps(entries[:MAX_RECENT], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add(path: Path) -> list[dict]:
    key = str(Path(path).resolve())
    entries = [e for e in load() if e["path"] != key]
    name = Path(key).name or key
    entries.insert(0, {"path": key, "name": name, "last_used": time.time()})
    _save(entries)
    return entries[:MAX_RECENT]


def remove(path: str) -> list[dict]:
    key = str(Path(path).resolve())
    entries = [e for e in load() if e["path"] != key]
    _save(entries)
    return entries
