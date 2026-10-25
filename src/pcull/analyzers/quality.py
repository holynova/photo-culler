"""Fast classical quality metrics: sharpness / exposure / colorfulness.

All operate on a downscaled RGB ndarray (see imaging.load_rgb) and return
normalized 0-100 values where higher is better, plus raw values for debugging.
"""
from __future__ import annotations

import cv2
import numpy as np

# Laplacian variance is mapped through log10: empirical anchors on 512px images
#   very blurry < 50 (log≈1.7) | typical sharp photo 300-3000 (log 2.5-3.5)
_BLUR_LOG_LO, _BLUR_LOG_HI = 1.3, 4.0


def sharpness(img_rgb: np.ndarray) -> tuple[float, float]:
    """Return (blur_100, laplacian_variance)."""
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    norm = (np.log10(1 + lap_var) - _BLUR_LOG_LO) / (_BLUR_LOG_HI - _BLUR_LOG_LO)
    return float(np.clip(norm * 100, 0, 100)), lap_var


def exposure(img_rgb: np.ndarray) -> tuple[float, float, float]:
    """Return (exposure_100, under_fraction, over_fraction)."""
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    total = gray.size
    under = float(np.count_nonzero(gray < 8)) / total
    over = float(np.count_nonzero(gray > 247)) / total
    penalty = min(100.0, (under + over) * 300)
    return 100.0 - penalty, under, over


def colorfulness(img_rgb: np.ndarray) -> float:
    """Hasler & Süsstrunk metric, clipped to 0-100."""
    r, g, b = img_rgb[..., 0].astype(np.float32), img_rgb[..., 1].astype(np.float32), img_rgb[..., 2].astype(np.float32)
    rg = r - g
    yb = 0.5 * (r + g) - b
    root = float(np.sqrt(np.std(rg) ** 2 + np.std(yb) ** 2)
                 + 0.3 * np.sqrt(np.mean(rg) ** 2 + np.mean(yb) ** 2))
    return float(np.clip(root, 0, 100))


def analyze(img_rgb: np.ndarray) -> dict:
    blur_100, lap_var = sharpness(img_rgb)
    expo, under, over = exposure(img_rgb)
    return {
        "blur": blur_100,
        "blur_raw": lap_var,
        "exposure": expo,
        "under": under,
        "over": over,
        "colorfulness": colorfulness(img_rgb),
    }
