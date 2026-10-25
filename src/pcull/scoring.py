"""Composite score + keep/review/delete recommendation from stored metrics."""
from __future__ import annotations

import json

# --- tunables ---------------------------------------------------------------
BLUR_HARD, BLUR_SOFT, BLUR_MILD = 12, 25, 40
BLUR_HARD_PENALTY, BLUR_SOFT_PENALTY, BLUR_MILD_PENALTY = 75, 55, 15
EXPO_BAD = 45
EYE_BLINK_PENALTY = 50
EYE_SQUINT_PENALTY, EYE_SQUINT_OPEN = 20, 0.35
DULL_PENALTY, DULL_FLOOR = 5, 12
DUP_GROUP_PENALTY = 10
NEAR_DUP_DISTANCE = 4  # phash distance at which a copy is "essentially identical"
# score bands
DELETE_BELOW, REVIEW_BELOW = 30, 55


def base_score(m: dict) -> tuple[float, list[str]]:
    """Quality-only score, independent of duplicate grouping."""
    if m.get("blur") is None:
        return 0.0, ["无法解码"]
    score = 100.0
    reasons: list[str] = []
    blur = m["blur"]
    if blur < BLUR_HARD:
        score -= BLUR_HARD_PENALTY
        reasons.append("严重模糊")
    elif blur < BLUR_SOFT:
        score -= BLUR_SOFT_PENALTY
        reasons.append("模糊")
    elif blur < BLUR_MILD:
        score -= BLUR_MILD_PENALTY
        reasons.append("欠锐")

    if m.get("exposure") is not None and m["exposure"] < EXPO_BAD:
        side = "过暗" if (m.get("under") or 0) >= (m.get("over") or 0) else "过曝"
        score -= 20
        reasons.append(f"曝光异常({side})")

    if m.get("closed_eye"):
        score -= EYE_BLINK_PENALTY
        reasons.append("闭眼")
    elif m.get("eye_open_min") is not None and m["eye_open_min"] < EYE_SQUINT_OPEN:
        score -= EYE_SQUINT_PENALTY
        reasons.append("眯眼")

    if m.get("colorfulness") is not None and m["colorfulness"] < DULL_FLOOR:
        score -= DULL_PENALTY
        reasons.append("画面平淡")

    return max(0.0, min(100.0, score)), reasons


def _recommend(score: float) -> str:
    if score < DELETE_BELOW:
        return "delete"
    if score < REVIEW_BELOW:
        return "review"
    return "keep"


def score_library(conn) -> dict:
    """Recompute score/recommendation/reasons for every analyzed photo."""
    photos = {
        r["photo_id"]: dict(r)
        for r in conn.execute("SELECT * FROM metrics")
    }
    sizes = {
        r["id"]: r["size"]
        for r in conn.execute("SELECT id, size FROM photos")
    }

    # pass 1: base scores
    for m in photos.values():
        m["_score"], m["_reasons"] = base_score(m)

    # pass 2: duplicate-group adjustments (keep the best member of each group)
    grouped: dict[int, list[int]] = {}
    for r in conn.execute("SELECT group_id, photo_id FROM groups"):
        grouped.setdefault(r["group_id"], []).append(r["photo_id"])
    for gid, members in grouped.items():
        ranked = sorted(members, key=lambda pid: (-(photos[pid]["_score"] if pid in photos else -1),
                                                  -(sizes.get(pid, 0))))
        for pid in ranked[1:]:
            if pid not in photos:
                continue
            dist_row = conn.execute(
                "SELECT distance FROM groups WHERE group_id=? AND photo_id=?", (gid, pid)
            ).fetchone()
            dist_val = dist_row["distance"] if dist_row else 99
            photos[pid]["_score"] = max(0.0, photos[pid]["_score"] - DUP_GROUP_PENALTY)
            if dist_val <= NEAR_DUP_DISTANCE:
                photos[pid]["_reasons"].append("近似重复")
            else:
                photos[pid]["_reasons"].append("连拍组非最佳")

    n = 0
    for pid, m in photos.items():
        reasons = m["_reasons"]
        score = m["_score"]
        rec = "review" if reasons == ["无法解码"] else _recommend(score)
        conn.execute(
            "UPDATE metrics SET score=?, recommendation=?, reasons=? WHERE photo_id=?",
            (score, rec, json.dumps(reasons, ensure_ascii=False), pid),
        )
        n += 1
    conn.commit()
    return {"scored": n, "groups": len(grouped)}
