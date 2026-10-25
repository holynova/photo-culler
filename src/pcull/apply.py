"""Apply delete decisions by MOVING files into a trash folder. Never unlink."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from pcull.db import TRASH_DIRNAME


def apply_decisions(library: Path, conn, dry_run: bool = False) -> dict:
    """Move every photo marked decision='delete' into <library>/../_pcull_trash/<ts>/.

    Returns a summary plus the manifest path. Originals are never destroyed.
    """
    library = Path(library).resolve()
    rows = conn.execute(
        """SELECT p.id, p.rel_path, p.size FROM photos p
           JOIN decisions d ON d.photo_id = p.id
           WHERE d.decision = 'delete' ORDER BY p.rel_path"""
    ).fetchall()

    planned = [dict(r) for r in rows]
    if dry_run or not planned:
        total = sum(r["size"] or 0 for r in planned)
        return {"summary": f"dry-run: {len(planned)} files, {total/1e6:.1f} MB",
                "manifest": None, "moved": 0, "planned": planned}

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    trash_root = library.parent / TRASH_DIRNAME / stamp
    manifest = {"moved_at": dt.datetime.now().isoformat(),
                "library": str(library), "items": []}
    moved = 0
    for r in planned:
        src = library / r["rel_path"]
        if not src.exists():
            continue
        dst = trash_root / r["rel_path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        manifest["items"].append({"from": r["rel_path"], "to": str(dst),
                                  "size": r["size"]})
        conn.execute("DELETE FROM photos WHERE id = ?", (r["id"],))
        moved += 1
    conn.commit()

    manifest_path = trash_root / "manifest.json"
    trash_root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    total = sum(i["size"] or 0 for i in manifest["items"])
    return {
        "summary": f"moved {moved} files ({total/1e6:.1f} MB) -> {trash_root}",
        "manifest": str(manifest_path),
        "moved": moved,
        "planned": planned,
    }
