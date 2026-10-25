"""Walk a library folder and upsert file records into SQLite."""
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

from PIL import Image

try:  # HEIC/HEIF from iPhones / some Android cameras
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".bmp", ".tif", ".tiff", ".dng"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".3gp", ".mkv", ".avi", ".webm"}
SKIP_DIRS = {".pcull", "_pcull_trash", ".git", "node_modules", ".thumbs"}

_EXIF_DATETIME_TAGS = (36867, 306, 36868)  # DateTimeOriginal, DateTime, Digitized


def _exif_taken_at(path: Path) -> float | None:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            raw = None
            for tag in _EXIF_DATETIME_TAGS:
                raw = exif.get(tag)
                if raw:
                    break
            if not raw:
                return None
            parsed = dt.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
            return parsed.timestamp()
    except Exception:
        return None


def _dimensions(path: Path, is_video: bool) -> tuple[int | None, int | None]:
    if is_video:
        return None, None  # filled by the video analyzer via ffprobe
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def scan_library(library: Path, conn) -> dict:
    """Index all supported files. Idempotent; removes rows for vanished files."""
    library = Path(library).resolve()
    seen: set[str] = set()
    counts = {"added": 0, "updated": 0, "removed": 0, "images": 0, "videos": 0}

    for root, dirs, files in os.walk(library):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
                continue
            full = Path(root) / name
            rel = full.relative_to(library).as_posix()
            seen.add(rel)
            st = full.stat()
            is_video = int(ext in VIDEO_EXTS)

            row = conn.execute(
                "SELECT id, size, mtime FROM photos WHERE rel_path = ?", (rel,)
            ).fetchone()
            if row and row["size"] == st.st_size and row["mtime"] == st.st_mtime:
                continue

            width, height = _dimensions(full, is_video)
            taken_at = None if is_video else _exif_taken_at(full)
            if row:
                conn.execute(
                    """UPDATE photos SET filename=?, ext=?, size=?, mtime=?, width=?, height=?,
                       taken_at=COALESCE(?, taken_at), is_video=?, analyzed_at=NULL
                       WHERE id=?""",
                    (name, ext, st.st_size, st.st_mtime, width, height, taken_at, is_video, row["id"]),
                )
                conn.execute("DELETE FROM metrics WHERE photo_id = ?", (row["id"],))
                counts["updated"] += 1
            else:
                conn.execute(
                    """INSERT INTO photos
                       (rel_path, filename, ext, size, mtime, width, height, taken_at, is_video)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (rel, name, ext, st.st_size, st.st_mtime, width, height, taken_at, is_video),
                )
                counts["added"] += 1
            counts["videos" if is_video else "images"] += 1

    vanished = [r["id"] for r in conn.execute("SELECT id, rel_path FROM photos")
                if r["rel_path"] not in seen]
    for pid in vanished:
        conn.execute("DELETE FROM photos WHERE id = ?", (pid,))
        counts["removed"] += 1
    conn.commit()
    return counts


def status(conn) -> dict:
    photos = conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
    analyzed = conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE analyzed_at IS NOT NULL"
    ).fetchone()["c"]
    by_rec = {r["recommendation"]: r["c"] for r in conn.execute(
        "SELECT recommendation, COUNT(*) c FROM metrics GROUP BY recommendation")}
    decided = conn.execute("SELECT COUNT(*) c FROM decisions").fetchone()["c"]
    groups = conn.execute("SELECT COUNT(DISTINCT group_id) c FROM groups").fetchone()["c"]
    total_bytes = conn.execute("SELECT COALESCE(SUM(size),0) s FROM photos").fetchone()["s"]
    return {
        "photos": photos,
        "analyzed": analyzed,
        "recommendations": by_rec,
        "decided": decided,
        "groups": groups,
        "total_bytes": total_bytes,
    }
