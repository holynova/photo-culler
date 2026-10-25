"""Phase 2: quality analyzers, phash dedup, thumbs, faces (best effort)."""
from __future__ import annotations

from pathlib import Path

import pytest

from pcull.analyzers import dedup, quality, thumbs
from pcull.imaging import load_rgb

METRICS = {}


def metric(lib: Path, name: str) -> dict:
    if name not in METRICS:
        img = load_rgb(lib / "DCIM" / name)
        METRICS[name] = quality.analyze(img)
    return METRICS[name]


def test_blur_scores_separate_sharp_from_blurry(lib: Path):
    sharp = metric(lib, "sharp_a.jpg")
    blurry = metric(lib, "blurry.jpg")
    very = metric(lib, "very_blurry.jpg")
    assert sharp["blur"] > 40  # above the "欠锐" band -> a clean sharp photo
    assert blurry["blur"] < sharp["blur"] - 20
    assert very["blur"] < 10


def test_exposure_detects_dark_and_blown(lib: Path):
    sharp = metric(lib, "sharp_a.jpg")
    dark = metric(lib, "dark.jpg")
    blown = metric(lib, "blown.jpg")
    assert sharp["exposure"] > 70
    assert dark["exposure"] < 45 and dark["under"] > 0.3
    assert blown["exposure"] < 45 and blown["over"] > 0.3


def test_colorfulness_detects_dull_image(lib: Path):
    sharp = metric(lib, "sharp_a.jpg")
    dull = metric(lib, "dull.jpg")
    assert dull["colorfulness"] < 15
    assert sharp["colorfulness"] > 25


def test_phash_matches_duplicates_and_rejects_different(lib: Path):
    import imagehash
    from PIL import Image

    def h(name):
        return imagehash.phash(Image.open(lib / "DCIM" / name), hash_size=8)

    dup_dist = h("burst_1.jpg") - h("burst_2.jpg")
    far_dist = h("burst_1.jpg") - h("other.jpg")
    assert dup_dist <= 4, f"expected near-duplicate, got distance {dup_dist}"
    assert far_dist > dedup.HAMMING_THRESHOLD


def test_build_groups_clusters_only_duplicates(lib: Path):
    hashes = [
        str(dedup.phash_hex(load_rgb(lib / "DCIM" / n)))
        for n in ("burst_1.jpg", "burst_2.jpg", "other.jpg", "sharp_a.jpg")
    ]
    groups = dedup.build_groups(hashes)
    assert len(groups) == 1
    members = {i for i, _ in groups[0]}
    assert members == {0, 1}  # only the burst pair


def test_thumb_written(lib: Path):
    img = load_rgb(lib / "DCIM" / "sharp_a.jpg")
    thumbs.save_thumb(img, lib, 123)
    p = thumbs.thumb_path(lib, 123)
    assert p.exists() and p.stat().st_size > 500


def test_face_analyzer_runs_or_reports_disabled(lib: Path):
    from pcull.analyzers.faces import EyeAnalyzer

    eye = EyeAnalyzer()
    if not eye.enabled:
        pytest.skip(f"face model unavailable: {eye.error}")
    img = load_rgb(lib / "DCIM" / "sharp_a.jpg")
    out = eye.analyze(img)
    assert out["faces"] == 0  # synthetic scene has no faces
    assert out["closed_eye"] == 0


def _cat(name, score):
    from types import SimpleNamespace

    return SimpleNamespace(category_name=name, score=score)


def test_eyes_parser_handles_mediapipe_1x_flat_lists():
    """Regression: mediapipe 1.x faces are flat Category lists, no .categories."""
    from pcull.analyzers.faces import eyes_from_blendshapes

    # two faces: one open (blink 0.05), one clearly blinking (0.9)
    blend = [
        [_cat("eyeBlinkLeft", 0.05), _cat("eyeBlinkRight", 0.02)],
        [_cat("eyeBlinkLeft", 0.9), _cat("eyeBlinkRight", 0.1)],
    ]
    out = eyes_from_blendshapes(blend)
    assert out["faces"] == 2
    assert out["closed_eye"] == 1
    assert abs(out["eye_open_min"] - 0.1) < 1e-6  # 1 - max(0.9, 0.1)

    # legacy shape: face object exposing .categories
    class LegacyFace:
        categories = [_cat("eyeBlinkLeft", 0.0), _cat("eyeBlinkRight", 0.0)]
    out2 = eyes_from_blendshapes([LegacyFace()])
    assert out2 == {"faces": 1, "eye_open_min": 1.0, "closed_eye": 0}

    assert eyes_from_blendshapes([]) == {"faces": 0, "eye_open_min": None, "closed_eye": 0}
