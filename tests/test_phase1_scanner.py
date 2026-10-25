"""Phase 1: scanner + SQLite index."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from pcull.db import connect
from pcull.scanner import scan_library, status


def rows(conn):
    return {r["rel_path"]: dict(r) for r in conn.execute("SELECT * FROM photos")}


def test_scan_indexes_everything_relevant(lib: Path):
    conn = connect(lib)
    counts = scan_library(lib, conn)
    assert counts["added"] == 10  # 9 good jpegs + 1 corrupt (txt/.pcull/trash ignored)
    assert counts["images"] == 10 and counts["videos"] == 0

    data = rows(conn)
    assert "DCIM/notes.txt" not in data
    assert ".pcull/cache_inside.jpg" not in data
    assert "_pcull_trash/trashed.jpg" not in data
    assert data["DCIM/sharp_a.jpg"]["width"] == 1600
    assert data["DCIM/sharp_a.jpg"]["height"] == 1200


def test_exif_taken_at_parsed_and_fallback(lib: Path):
    conn = connect(lib)
    scan_library(lib, conn)
    data = rows(conn)

    taken = data["DCIM/sharp_a.jpg"]["taken_at"]
    assert taken == dt.datetime(2024, 5, 1, 10, 0).timestamp()

    # dark.jpg has no EXIF -> falls back to file mtime
    assert data["DCIM/dark.jpg"]["taken_at"] is None  # stored as None, UI falls back to mtime


def test_rescan_idempotent_and_tracks_changes(lib: Path):
    conn = connect(lib)
    scan_library(lib, conn)
    counts2 = scan_library(lib, conn)
    assert counts2["added"] == 0 and counts2["updated"] == 0

    # modify a file -> it gets re-indexed and metrics invalidated
    from PIL import Image

    with Image.open(lib / "DCIM" / "sharp_a.jpg") as im:
        im.rotate(30).save(lib / "DCIM" / "sharp_a.jpg", quality=85)
    conn.execute("UPDATE photos SET analyzed_at = 123 WHERE rel_path='DCIM/sharp_a.jpg'")
    conn.commit()
    counts3 = scan_library(lib, conn)
    assert counts3["updated"] == 1
    assert conn.execute(
        "SELECT analyzed_at FROM photos WHERE rel_path='DCIM/sharp_a.jpg'"
    ).fetchone()[0] is None

    # delete a file -> row disappears
    (lib / "DCIM" / "other.jpg").unlink()
    counts4 = scan_library(lib, conn)
    assert counts4["removed"] == 1
    assert "DCIM/other.jpg" not in rows(conn)


def test_status_summary(lib: Path):
    conn = connect(lib)
    scan_library(lib, conn)
    st = status(conn)
    assert st["photos"] == 10
    assert st["analyzed"] == 0
    assert st["total_bytes"] > 0
