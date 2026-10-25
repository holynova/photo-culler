"""Thumbnail cache under <library>/.pcull/thumbs/."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

THUMB_MAX_SIDE = 480
THUMB_QUALITY = 78


def thumb_path(library: Path, photo_id: int) -> Path:
    d = Path(library) / ".pcull" / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{photo_id}.jpg"


def save_thumb(img_rgb: np.ndarray, library: Path, photo_id: int) -> None:
    bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, THUMB_QUALITY])
    if ok:
        thumb_path(library, photo_id).write_bytes(buf.tobytes())
