"""Image loading that survives Windows non-ASCII paths and HEIC files."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass


def load_rgb(path: Path, max_side: int = 512) -> np.ndarray | None:
    """Return an RGB ndarray downscaled to max_side, or None if unreadable.

    cv2.imdecode is used first (fast, handles non-ASCII paths via fromfile);
    PIL is the fallback for HEIC/TIFF and anything cv2 can't decode.
    """
    path = Path(path)
    img = None
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size:
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        img = None
    if img is None:
        try:
            with Image.open(path) as pil:
                pil = pil.convert("RGB")
                img = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def to_pil(img_rgb: np.ndarray) -> Image.Image:
    return Image.fromarray(img_rgb)
