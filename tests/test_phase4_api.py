"""Phase 4: REST API + safe apply."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pcull.db import connect
from pcull.pipeline import run_analysis
from pcull.scanner import scan_library
from pcull.server import create_app


@pytest.fixture()
def client(lib: Path):
    conn = connect(lib)
    scan_library(lib, conn)
    run_analysis(lib, conn, faces=False, workers=2)
    return TestClient(create_app(lib)), lib


def test_stats_shape(client):
    c, _ = client
    r = c.get("/api/stats").json()
    assert r["photos"] == 10
    assert r["analyzed"] == 10
    assert set(r["recommendations"]) >= {"keep", "review", "delete"}
    assert r["reclaimable_bytes"] == 0


def test_photos_tabs_and_sort(client):
    c, _ = client
    all_items = c.get("/api/photos").json()
    assert all_items["total"] == 10
    first = all_items["items"][0]
    assert {"id", "rel_path", "score", "recommendation", "reasons",
            "decision", "group_id", "blur"} <= set(first)

    deletes = c.get("/api/photos", params={"tab": "delete"}).json()
    assert deletes["total"] >= 1
    assert all(i["recommendation"] == "delete" for i in deletes["items"])

    # default sort score_desc: scores descending
    scores = [i["score"] for i in all_items["items"]]
    assert scores == sorted(scores, reverse=True)

    r = c.get("/api/photos", params={"tab": "nope"})
    assert r.status_code == 400


def test_decisions_roundtrip_and_decided_tab(client):
    c, _ = client
    ids = [i["id"] for i in c.get("/api/photos", params={"tab": "delete"}).json()["items"]]
    assert c.post("/api/decisions", json={"ids": ids, "decision": "delete"}).status_code == 200

    decided = c.get("/api/photos", params={"tab": "decided_delete"}).json()
    assert decided["total"] == len(ids)
    assert c.get("/api/stats").json()["reclaimable_bytes"] > 0

    # clear one -> falls back out of the decided tab
    c.post("/api/decisions", json={"ids": ids[:1], "decision": None})
    assert c.get("/api/photos", params={"tab": "decided_delete"}).json()["total"] == len(ids) - 1


def test_groups_endpoint(client):
    c, _ = client
    data = c.get("/api/groups").json()["groups"]
    assert len(data) == 1
    assert data[0]["count"] == 2
    # best member first
    s = [i["score"] for i in data[0]["items"]]
    assert s == sorted(s, reverse=True)


def test_thumbnail_and_file_serving(client):
    c, lib = client
    any_item = c.get("/api/photos").json()["items"][0]
    r = c.get(f"/thumb/{any_item['id']}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/jpeg")
    assert c.get("/thumb/99999").status_code == 404
    r2 = c.get(f"/file/{any_item['id']}")
    assert r2.status_code == 200


def test_apply_dry_run_and_move(client):
    c, lib = client
    ids = [i["id"] for i in c.get("/api/photos", params={"tab": "delete"}).json()["items"]]
    c.post("/api/decisions", json={"ids": ids, "decision": "delete"})

    dry = c.post("/api/apply", params={"dry_run": True}).json()
    assert dry["moved"] == 0 and len(dry["planned"]) == len(ids)

    real = c.post("/api/apply").json()
    assert real["moved"] == len(ids)
    manifest = json.loads(Path(real["manifest"]).read_text(encoding="utf-8"))
    assert len(manifest["items"]) == len(ids)

    # originals gone from library, present in trash with same structure
    for item in manifest["items"]:
        assert not (lib / item["from"]).exists()
        assert Path(item["to"]).exists()

    # DB no longer lists them
    assert c.get("/api/stats").json()["photos"] == 10 - len(ids)
