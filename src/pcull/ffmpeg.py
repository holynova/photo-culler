"""Locate ffmpeg/ffprobe: env override > PATH > known project locations."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

_KNOWN_ROOTS = [
    Path("G:/code/ai-video/tools/ffmpeg-master-latest-win64-gpl/bin"),
    Path(__file__).resolve().parents[2] / "tools" / "ffmpeg" / "bin",
]


def _find(name: str) -> Path | None:
    env = os.environ.get(f"PCULL_{name.upper()}")
    if env and Path(env).exists():
        return Path(env)
    which = shutil.which(name)
    if which:
        return Path(which)
    exe = f"{name}.exe" if os.name == "nt" else name
    for root in _KNOWN_ROOTS:
        cand = root / exe
        if cand.exists():
            return cand
    return None


def ffmpeg() -> Path | None:
    return _find("ffmpeg")


def ffprobe() -> Path | None:
    return _find("ffprobe")
