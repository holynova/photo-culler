"""Phase 3: full pipeline → scores + recommendations."""
from __future__ import annotations

import json
from pathlib import Path

from pcull.db import connect
from pcull.pipeline import run_analysis
from pcull.scanner import scan_library


def analyze_lib(lib: Path, **kw):
    conn = connect(lib)
    scan_library(lib, conn)
    return conn, run_analysis(lib, conn, **kw)


def rec_of(conn, rel_path: str) -> dict:
    row = conn.execute(
        """SELECT m.*, p.rel_path FROM metrics m JOIN photos p ON p.id = m.photo_id
           WHERE p.rel_path = ?""",
        (rel_path,),
    ).fetchone()
    assert row is not None, f"no metrics for {rel_path}"
    d = dict(row)
    d["reasons"] = json.loads(d["reasons"] or "[]")
    return d


def test_blur_drives_delete_recommendation(lib: Path):
    conn, summary = analyze_lib(lib, faces=False, workers=2)
    very = rec_of(conn, "DCIM/very_blurry.jpg")
    blur = rec_of(conn, "DCIM/blurry.jpg")
    sharp = rec_of(conn, "DCIM/sharp_a.jpg")

    assert very["recommendation"] == "delete"
    assert "严重模糊" in very["reasons"]
    assert blur["recommendation"] in ("delete", "review")
    assert "模糊" in blur["reasons"]
    assert sharp["recommendation"] == "keep"
    assert sharp["reasons"] == []
    assert sharp["score"] >= 55


def test_exposure_reasons(lib: Path):
    conn, _ = analyze_lib(lib, faces=False, workers=2)
    assert "曝光异常(过暗)" in rec_of(conn, "DCIM/dark.jpg")["reasons"]
    assert "曝光异常(过曝)" in rec_of(conn, "DCIM/blown.jpg")["reasons"]


def test_duplicate_pair_grouped_and_penalized(lib: Path):
    conn, summary = analyze_lib(lib, faces=False, workers=2)
    assert summary["groups"] == 1
    b1 = rec_of(conn, "DCIM/burst_1.jpg")
    b2 = rec_of(conn, "DCIM/burst_2.jpg")
    penalized, kept = sorted([b1, b2], key=lambda r: r["score"])
    assert "近似重复" in penalized["reasons"]
    assert "近似重复" not in kept["reasons"]
    assert penalized["score"] < kept["score"]
    # different-content photo is in no group
    assert rec_of(conn, "DCIM/other.jpg")["photo_id"] not in {
        r["photo_id"] for r in conn.execute("SELECT photo_id FROM groups")
    }


def test_dull_image_flagged_but_kept(lib: Path):
    conn, _ = analyze_lib(lib, faces=False, workers=2)
    dull = rec_of(conn, "DCIM/dull.jpg")
    assert "画面平淡" in dull["reasons"]
    assert dull["recommendation"] == "keep"


def test_corrupt_file_flagged_for_review_not_delete(lib: Path):
    conn, _ = analyze_lib(lib, faces=False, workers=2)
    bad = rec_of(conn, "DCIM/corrupt.jpg")
    assert bad["recommendation"] == "review"
    assert bad["reasons"] == ["无法解码"]


def test_thumbnails_created_for_decodable_images(lib: Path):
    from pcull.analyzers.thumbs import thumb_path

    conn, _ = analyze_lib(lib, faces=False, workers=2)
    ok = 0
    for r in conn.execute("SELECT id FROM photos WHERE filename != 'corrupt.jpg'"):
        if thumb_path(lib, r["id"]).exists():
            ok += 1
    assert ok == 9
