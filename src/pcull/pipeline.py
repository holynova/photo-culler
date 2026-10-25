"""Analysis pipeline: thumbnails → quality/eyes/phash per file → groups → scores."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pcull.analyzers import dedup, quality, thumbs
from pcull.analyzers.faces import EyeAnalyzer
from pcull.imaging import load_rgb
from pcull.scoring import score_library

_local = threading.local()


def _get_eye_analyzer(enabled: bool) -> EyeAnalyzer | None:
    if not enabled:
        return None
    analyzer = getattr(_local, "eye_analyzer", None)
    if analyzer is None:
        analyzer = EyeAnalyzer()
        _local.eye_analyzer = analyzer
    return analyzer if analyzer.enabled else None


def analyze_one(library: Path, photo: dict, faces: bool) -> dict:
    """Analyze a single photo. Returns metric dict (values may be None)."""
    result = {
        "blur": None, "blur_raw": None, "exposure": None, "under": None,
        "over": None, "colorfulness": None,
        "faces": None, "eye_open_min": None, "closed_eye": None,
        "phash": None,
    }
    path = Path(library) / photo["rel_path"]
    if photo["is_video"]:
        from pcull.analyzers.video import analyze_video

        metrics = analyze_video(library, path)
        if metrics:
            frame = metrics.pop("_middle_frame", None)
            if frame is not None:
                thumbs.save_thumb(frame, library, photo["id"])
            result.update({k: v for k, v in metrics.items() if k in result})
            for k in ("width", "height", "duration"):
                if metrics.get(k) is not None:
                    result[k] = metrics[k]
        return result

    img = load_rgb(path)
    if img is None:
        return result
    result.update(quality.analyze(img))
    result["phash"] = dedup.phash_hex(img)
    thumbs.save_thumb(img, library, photo["id"])

    eye = _get_eye_analyzer(faces)
    if eye is not None:
        result.update(eye.analyze(img))
    return result


def run_analysis(library: Path, conn, faces: bool = True, workers: int = 4,
                 progress=None) -> dict:
    """Analyze every photo not yet processed, then regroup + rescore all."""
    library = Path(library).resolve()
    todo = [dict(r) for r in conn.execute(
        "SELECT * FROM photos WHERE analyzed_at IS NULL ORDER BY rel_path")]

    summary = {"analyzed": 0, "failed": 0, "thumbs": 0, "duration": 0.0}
    t0 = time.time()
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(analyze_one, library, p, faces): p for p in todo}
            for fut in as_completed(futures):
                photo = futures[fut]
                try:
                    m = fut.result()
                except Exception as e:
                    summary["failed"] += 1
                    print(f"[warn] analyze failed {photo['rel_path']}: {e}")
                    m = None
                now = time.time()
                conn.execute(
                    """INSERT INTO metrics (photo_id, blur, blur_raw, exposure, under, over,
                       colorfulness, faces, eye_open_min, closed_eye)
                       VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(photo_id) DO UPDATE SET
                         blur=excluded.blur, blur_raw=excluded.blur_raw,
                         exposure=excluded.exposure, under=excluded.under, over=excluded.over,
                         colorfulness=excluded.colorfulness, faces=excluded.faces,
                         eye_open_min=excluded.eye_open_min, closed_eye=excluded.closed_eye""",
                    (photo["id"], m and m["blur"], m and m["blur_raw"], m and m["exposure"],
                     m and m["under"], m and m["over"], m and m["colorfulness"],
                     m and m["faces"], m and m["eye_open_min"], m and m["closed_eye"]),
                )
                if m and m["phash"]:
                    conn.execute("UPDATE photos SET phash=? WHERE id=?",
                                 (m["phash"], photo["id"]))
                if photo["is_video"] and m:
                    conn.execute(
                        "UPDATE photos SET width=COALESCE(?, width), "
                        "height=COALESCE(?, height), duration=COALESCE(?, duration) "
                        "WHERE id=?",
                        (m.get("width"), m.get("height"), m.get("duration"), photo["id"]),
                    )
                conn.execute("UPDATE photos SET analyzed_at=? WHERE id=?",
                             (now, photo["id"]))
                summary["analyzed"] += 1
                if progress:
                    progress(summary["analyzed"], len(todo), photo["rel_path"])
        conn.commit()

    # rebuild duplicate/burst groups across the whole library, then rescore.
    # Very blurry photos are excluded: their near-uniform phash clusters into
    # false "duplicate" groups, and they're delete candidates anyway.
    conn.execute("DELETE FROM groups")
    hashed = [(r["id"], r["phash"]) for r in conn.execute(
        """SELECT p.id, p.phash FROM photos p
           LEFT JOIN metrics m ON m.photo_id = p.id
           WHERE p.phash IS NOT NULL AND (m.blur IS NULL OR m.blur >= 12)""")]
    if len(hashed) >= 2:
        ids = [h[0] for h in hashed]
        groups = dedup.build_groups([h[1] for h in hashed])
        for gid, group in enumerate(groups, start=1):
            conn.executemany(
                "INSERT OR REPLACE INTO groups (group_id, photo_id, distance) VALUES (?,?,?)",
                [(gid, ids[m], d) for m, d in group],
            )
        conn.commit()
    score_result = score_library(conn)
    summary["duration"] = round(time.time() - t0, 1)
    summary.update(score_result)
    return summary
