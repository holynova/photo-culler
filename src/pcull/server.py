"""FastAPI app: JSON API + static review UI."""
from __future__ import annotations

import json
import os
import string
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pcull import libraries
from pcull.apply import apply_decisions
from pcull.db import connect

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

_SKIP_BROWSE_DIRS = {"$recycle.bin", "system volume information", "node_modules",
                     ".git", "__pycache__", ".pcull", "_pcull_trash"}


class DecisionIn(BaseModel):
    ids: list[int]
    decision: str | None = None  # 'keep' | 'delete' | None=clear


class LibraryIn(BaseModel):
    path: str

_SORTS = {
    "score_asc": "m.score ASC",
    "score_desc": "m.score DESC",
    "date_desc": "p.taken_at DESC, p.mtime DESC",
    "date_asc": "p.taken_at ASC, p.mtime ASC",
    "size_desc": "p.size DESC",
    "blur_asc": "m.blur ASC",
}

_TAB_WHERE = {
    "all": "",
    "delete": "WHERE m.recommendation = 'delete' AND d.decision IS NULL",
    "review": "WHERE m.recommendation = 'review' AND d.decision IS NULL",
    "keep": "WHERE m.recommendation = 'keep' AND d.decision IS NULL",
    "todo": "WHERE d.decision IS NULL AND m.recommendation != 'keep'",
    "decided_delete": "WHERE d.decision = 'delete'",
    "decided_keep": "WHERE d.decision = 'keep'",
    "videos": "WHERE p.is_video = 1",
}


def _photo_card(row) -> dict:
    d = dict(row)
    d["reasons"] = json.loads(d["reasons"] or "[]")
    d["taken_at"] = d["taken_at"] or d["mtime"]
    return d


_CARD_SQL = """
SELECT p.id, p.rel_path, p.filename, p.size, p.mtime, p.taken_at, p.is_video,
       p.duration, p.width, p.height,
       m.blur, m.exposure, m.colorfulness, m.faces, m.eye_open_min,
       m.closed_eye, m.score, m.recommendation, m.reasons,
       d.decision, g.group_id
FROM photos p
LEFT JOIN metrics m ON m.photo_id = p.id
LEFT JOIN decisions d ON d.photo_id = p.id
LEFT JOIN groups g ON g.photo_id = p.id
"""


def create_app(library: Path | None) -> FastAPI:
    app = FastAPI(title="pcull")
    app.state.library = Path(library).resolve() if library else None
    app.state.analyze_state = {"running": False, "done": 0, "total": 0, "last": "",
                               "error": None, "phase": "idle",
                               "library": str(app.state.library) if library else None}

    def require_library() -> Path:
        lib = app.state.library
        if lib is None:
            raise HTTPException(400, "no library open")
        return lib

    def conn():
        return connect(require_library())

    @app.get("/api/stats")
    def stats():
        with conn() as db:
            total = db.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
            analyzed = db.execute(
                "SELECT COUNT(*) c FROM photos WHERE analyzed_at IS NOT NULL").fetchone()["c"]
            by_rec = {r["recommendation"]: r["c"] for r in db.execute(
                "SELECT recommendation, COUNT(*) c FROM metrics GROUP BY recommendation")}
            decided = {r["decision"]: r["c"] for r in db.execute(
                "SELECT decision, COUNT(*) c FROM decisions GROUP BY decision")}
            reclaim = db.execute(
                """SELECT COALESCE(SUM(p.size),0) s FROM photos p
                   JOIN decisions d ON d.photo_id=p.id WHERE d.decision='delete'"""
            ).fetchone()["s"]
            total_bytes = db.execute("SELECT COALESCE(SUM(size),0) s FROM photos").fetchone()["s"]
            groups = db.execute(
                "SELECT COUNT(DISTINCT group_id) c FROM groups").fetchone()["c"]
        return {"photos": total, "analyzed": analyzed,
                "recommendations": by_rec, "decided": decided,
                "reclaimable_bytes": reclaim, "total_bytes": total_bytes,
                "groups": groups}

    @app.get("/api/photos")
    def photos(tab: str = "all", sort: str = "score_desc",
               limit: int = 60, offset: int = 0, group_id: int | None = None):
        where = _TAB_WHERE.get(tab)
        if where is None:
            raise HTTPException(400, f"unknown tab {tab}")
        order = _SORTS.get(sort)
        if order is None:
            raise HTTPException(400, f"unknown sort {sort}")
        extra = ""
        params: list = []
        if group_id is not None:
            extra = (" AND " if where else " WHERE ") + "g.group_id = ?"
            params.append(group_id)
        with conn() as db:
            total = db.execute(
                f"SELECT COUNT(*) c FROM photos p "
                f"LEFT JOIN metrics m ON m.photo_id=p.id "
                f"LEFT JOIN decisions d ON d.photo_id=p.id "
                f"LEFT JOIN groups g ON g.photo_id=p.id {where}{extra}", params
            ).fetchone()["c"]
            rows = db.execute(
                f"{_CARD_SQL} {where}{extra} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return {"total": total, "items": [_photo_card(r) for r in rows]}

    @app.get("/api/photo/{photo_id}")
    def photo_detail(photo_id: int):
        with conn() as db:
            row = db.execute(
                _CARD_SQL + " WHERE p.id = ?", (photo_id,)
            ).fetchone()
        if not row:
            raise HTTPException(404)
        return _photo_card(row)

    @app.get("/api/groups")
    def groups():
        with conn() as db:
            rows = db.execute(
                f"{_CARD_SQL} WHERE g.group_id IS NOT NULL "
                f"ORDER BY g.group_id, m.score DESC"
            ).fetchall()
        by_group: dict[int, list] = {}
        for r in rows:
            by_group.setdefault(r["group_id"], []).append(_photo_card(r))
        return {"groups": [
            {"group_id": gid, "count": len(items), "items": items}
            for gid, items in sorted(by_group.items())
        ]}

    @app.get("/thumb/{photo_id}")
    def thumb(photo_id: int):
        p = require_library() / ".pcull" / "thumbs" / f"{photo_id}.jpg"
        if not p.exists():
            raise HTTPException(404, "no thumbnail (analyzed yet?)")
        return FileResponse(p, media_type="image/jpeg")

    @app.get("/file/{photo_id}")
    def file(photo_id: int):
        with conn() as db:
            row = db.execute("SELECT rel_path FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        return FileResponse(require_library() / row["rel_path"])

    class DecisionIn(BaseModel):
        ids: list[int]
        decision: str | None = None  # 'keep' | 'delete' | None=clear

    @app.post("/api/decisions")
    def set_decisions(body: DecisionIn):
        if body.decision not in ("keep", "delete", None):
            raise HTTPException(400, "decision must be keep/delete/null")

        with conn() as db:
            for pid in body.ids:
                if body.decision is None:
                    db.execute("DELETE FROM decisions WHERE photo_id=?", (pid,))
                else:
                    db.execute(
                        """INSERT INTO decisions (photo_id, decision, decided_at)
                           VALUES (?,?,?)
                           ON CONFLICT(photo_id) DO UPDATE SET
                             decision=excluded.decision, decided_at=excluded.decided_at""",
                        (pid, body.decision, time.time()),
                    )
        return {"ok": True, "count": len(body.ids)}

    @app.post("/api/analyze")
    def start_analyze():
        state = app.state.analyze_state
        if state["running"]:
            return {"ok": True, "already_running": True}
        lib = require_library()

        def run():
            from pcull.pipeline import run_analysis
            from pcull.scanner import scan_library

            try:
                with conn() as db:
                    # scan first so newly added/changed files are picked up
                    scan_library(lib, db)
                    state.update(phase="analyzing", done=0)
                    run_analysis(lib, db, faces=True,
                                 progress=lambda done, total, last: state.update(
                                     done=done, total=total, last=last))
            except Exception as e:  # surface to the status endpoint
                state["error"] = str(e)
            finally:
                state["running"] = False
                state["phase"] = "idle"

        state.update(running=True, done=0, total=0, error=None, phase="analyzing")
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    @app.get("/api/analyze/status")
    def analyze_status():
        return app.state.analyze_state

    # ---- library management -------------------------------------------------

    @app.get("/api/library/current")
    def library_current():
        lib = app.state.library
        return {"library": str(lib) if lib else None,
                "running": app.state.analyze_state["running"]}

    @app.get("/api/library/recent")
    def library_recent():
        entries = libraries.load()
        existing = [e for e in entries if Path(e["path"]).exists()]
        return {"libraries": existing}

    @app.post("/api/library/recent/drop")
    def library_recent_drop(body: LibraryIn):
        return {"libraries": libraries.remove(body.path)}

    @app.post("/api/library/open")
    def library_open(body: LibraryIn):
        state = app.state.analyze_state
        if state["running"]:
            raise HTTPException(409, "analysis in progress")
        p = Path(body.path)
        if not p.is_dir():
            raise HTTPException(400, f"not a directory: {body.path}")
        p = p.resolve()
        app.state.library = p
        libraries.add(p)
        state.update(running=True, done=0, total=0, last="", error=None,
                     phase="scanning", library=str(p))

        def run():
            from pcull.pipeline import run_analysis
            from pcull.scanner import scan_library

            try:
                with connect(p) as db:
                    scan_library(p, db)
                    state.update(phase="analyzing", done=0)
                    run_analysis(p, db, faces=True,
                                 progress=lambda done, total, last: state.update(
                                     done=done, total=total, last=last))
            except Exception as e:
                state["error"] = str(e)
            finally:
                state["running"] = False
                state["phase"] = "idle"

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "library": str(p)}

    @app.get("/api/browse")
    def browse(path: str = ""):
        """List subfolders of `path`; empty path lists drives (Windows)."""
        if not path:
            entries = []
            if os.name == "nt":
                for c in string.ascii_uppercase:
                    if Path(f"{c}:/").exists():
                        entries.append({"name": f"{c}:", "path": f"{c}:\\"})
            else:
                entries.append({"name": "/", "path": "/"})
            return {"path": "", "parent": None, "entries": entries, "is_drive_list": True}
        p = Path(path)
        if not p.is_dir():
            raise HTTPException(400, f"not a directory: {path}")
        entries = []
        try:
            for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
                if not child.is_dir():
                    continue
                if child.name.lower() in _SKIP_BROWSE_DIRS or child.name.startswith("."):
                    continue
                entries.append({"name": child.name, "path": str(child)})
        except PermissionError:
            raise HTTPException(400, f"permission denied: {path}")
        parent = str(p.parent) if p.parent != p else None
        return {"path": str(p), "parent": parent, "entries": entries,
                "is_drive_list": False}

    @app.post("/api/apply")
    def apply(dry_run: bool = False):
        lib = require_library()
        with conn() as db:
            return apply_decisions(lib, db, dry_run=dry_run)

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")
    return app
