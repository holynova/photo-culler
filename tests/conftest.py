"""Synthetic photo library fixtures shared by all test phases."""
from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

FFMPEG_CANDIDATES = [
    Path("G:/code/ai-video/tools/ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe"),
]


def find_ffmpeg() -> Path | None:
    for cand in FFMPEG_CANDIDATES:
        if cand.exists():
            return cand
    return None


def draw_scene(size=(1600, 1200), variant="sharp") -> Image.Image:
    """A busy synthetic scene: shapes + text + noise = high-frequency detail."""
    import random

    rng = random.Random(variant)
    w, h = size
    if variant == "flat":  # smooth gradient: far phash from busy scenes
        return Image.linear_gradient("L").resize(size).convert("RGB")
    # background hue derived from the seed so different scenes look distinct
    seed_val = sum(ord(c) * (i + 1) for i, c in enumerate(variant))
    img = Image.new("RGB", size, (25 + seed_val % 90, 30 + seed_val % 150, 60 + seed_val % 180))
    d = ImageDraw.Draw(img)
    for _ in range(60):
        x, y = rng.randint(0, w - 1), rng.randint(0, h - 1)
        r = rng.randint(5, 120)
        color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        shape = rng.choice(["rect", "ellipse", "line"])
        if shape == "rect":
            d.rectangle([x, y, x + r, y + r // 2], fill=color)
        elif shape == "ellipse":
            d.ellipse([x, y, x + r, y + r], fill=color)
        else:
            d.line([x, y, x + r, y + r // 3], fill=color, width=3)
    for i in range(12):
        d.text((50 + i * 120, rng.randint(0, h - 40)), f"TEST{i}", fill=(255, 255, 255))
    # fine high-frequency detail so a "sharp" scene scores like a sharp real photo
    for _ in range(500):
        x, y = rng.randint(0, w - 5), rng.randint(0, h - 5)
        r = rng.randint(1, 3)
        d.ellipse([x, y, x + r, y + r], fill=(rng.randint(100, 255), rng.randint(100, 255), 0))
    for _ in range(200):
        x, y = rng.randint(0, w - 1), rng.randint(0, h - 1)
        d.line([x, y, x + rng.randint(-80, 80), y + rng.randint(-50, 50)],
               fill=(0, rng.randint(100, 255), rng.randint(100, 255)), width=1)
    # sensor-like noise: real photos always carry some, and it feeds the
    # laplacian-variance sharpness metric
    arr = np.asarray(img).astype(np.int16)
    noise = np.asarray(
        Image.effect_noise((w, h), 26).convert("L"), dtype=np.int16
    ) - 128
    for c in range(3):
        arr[..., c] = np.clip(arr[..., c] + (noise // 2), 0, 255)
    img = Image.fromarray(arr.astype(np.uint8))

    if variant == "blurry":
        img = img.filter(ImageFilter_GaussianBlur(2))
    elif variant == "very_blurry":
        img = img.filter(ImageFilter_GaussianBlur(18))
    elif variant == "dark":
        img = Image.eval(img, lambda v: v // 12)
    elif variant == "overexposed":
        img = Image.eval(img, lambda v: min(255, v * 2 + 180))
    elif variant == "dull":
        img = img.convert("L").convert("RGB")
    return img


def ImageFilter_GaussianBlur(radius):  # lazy import helper
    from PIL import ImageFilter

    return ImageFilter.GaussianBlur(radius)


def save_jpeg(img: Image.Image, path: Path, exif_date: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"quality": 92}
    if exif_date:
        exif = Image.Exif()
        exif[36867] = exif_date  # DateTimeOriginal
        kwargs["exif"] = exif
    img.save(path, **kwargs)


@pytest.fixture()
def lib(tmp_path: Path) -> Path:
    """A mini library covering every interesting case."""
    root = tmp_path / "lib"
    root.mkdir()

    sharp = draw_scene(variant="sharp")
    save_jpeg(sharp, root / "DCIM" / "sharp_a.jpg", exif_date="2024:05:01 10:00:00")
    save_jpeg(draw_scene(variant="blurry"), root / "DCIM" / "blurry.jpg",
              exif_date="2024:05:01 10:01:00")
    save_jpeg(draw_scene(variant="very_blurry"), root / "DCIM" / "very_blurry.jpg",
              exif_date="2024:05:01 10:02:00")
    save_jpeg(draw_scene(variant="dark"), root / "DCIM" / "dark.jpg")
    save_jpeg(draw_scene(variant="overexposed"), root / "DCIM" / "blown.jpg")
    save_jpeg(draw_scene(variant="dull"), root / "DCIM" / "dull.jpg")

    # near-duplicate pair: same scene recompressed + resized slightly
    # ('burst' is just a distinct RNG seed so content differs from sharp_a)
    dup = draw_scene(variant="burst")
    save_jpeg(dup, root / "DCIM" / "burst_1.jpg", exif_date="2024:05:02 09:00:00")
    save_jpeg(dup.resize((1500, 1125)), root / "DCIM" / "burst_2.jpg",
              exif_date="2024:05:02 09:00:01")
    # different content, must NOT group with burst (smooth gradient = far phash)
    save_jpeg(draw_scene(variant="flat"), root / "DCIM" / "other.jpg")

    # corrupt file: indexed, but analysis marks it unreadable
    (root / "DCIM" / "corrupt.jpg").write_bytes(b"this is not a jpeg")

    # a file that must be ignored
    (root / "DCIM" / "notes.txt").write_text("ignore me")

    # ignored folders
    (root / ".pcull").mkdir(exist_ok=True)
    save_jpeg(sharp, root / ".pcull" / "cache_inside.jpg")
    (root / "_pcull_trash").mkdir(exist_ok=True)
    save_jpeg(sharp, root / "_pcull_trash" / "trashed.jpg")

    return root


@pytest.fixture(scope="session")
def ffmpeg() -> Path | None:
    return find_ffmpeg()
