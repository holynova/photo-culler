"""Video analysis: ffprobe metadata + even frame sampling → photo metrics.

The worst sampled frame drives the sharpness score (one blurry moment
sinks the video), averages drive exposure/colorfulness, and the middle
frame's phash enables video-to-video duplicate grouping.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from pcull import ffmpeg as ff
from pcull.analyzers import dedup, quality

FRAME_SAMPLES = 6
FRAME_MAX_SIDE = 512


def probe(path: Path) -> dict:
    exe = ff.ffprobe()
    if exe is None:
        return {}
    try:
        out = subprocess.run(
            [str(exe), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
        data = json.loads(out)
    except Exception:
        return {}
    duration = None
    if data.get("format", {}).get("duration"):
        duration = float(data["format"]["duration"])
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            return {
                "duration": duration,
                "width": stream.get("width"),
                "height": stream.get("height"),
            }
    return {}


def _grab_frame(ffmpeg_exe: Path, path: Path, t: float) -> np.ndarray | None:
    try:
        proc = subprocess.run(
            [str(ffmpeg_exe), "-v", "error", "-ss", f"{t:.2f}", "-i", str(path),
             "-frames:v", "1", "-vf", f"scale={FRAME_MAX_SIDE}:-2",
             "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "pipe:1"],
            capture_output=True, timeout=60, check=True,
        )
        img = cv2.imdecode(np.frombuffer(proc.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    except Exception:
        return None


def analyze_video(library: Path, path: Path) -> dict | None:
    """Return metric dict (photo-metric compatible) or None if tools missing."""
    ffmpeg_exe = ff.ffmpeg()
    if ffmpeg_exe is None:
        return None
    meta = probe(path)
    duration = meta.get("duration") or 0.0
    if duration <= 0:
        return None

    timestamps = [duration * (i + 0.5) / FRAME_SAMPLES for i in range(FRAME_SAMPLES)]
    frames = [f for f in (_grab_frame(ffmpeg_exe, path, t) for t in timestamps) if f is not None]
    if not frames:
        return None

    per_frame = [quality.analyze(f) for f in frames]
    result = {
        # worst frame decides sharpness — a video is only as sharp as its blurriest moment
        "blur": min(m["blur"] for m in per_frame),
        "blur_raw": None,
        "exposure": float(np.mean([m["exposure"] for m in per_frame])),
        "under": float(np.mean([m["under"] for m in per_frame])),
        "over": float(np.mean([m["over"] for m in per_frame])),
        "colorfulness": float(np.mean([m["colorfulness"] for m in per_frame])),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "duration": duration,
        "phash": None,
    }
    middle = frames[len(frames) // 2]
    result["phash"] = dedup.phash_hex(middle)
    # the pipeline saves the thumbnail (it knows the photo id)
    result["_middle_frame"] = middle
    return result
