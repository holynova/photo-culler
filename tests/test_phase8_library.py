"""Library picker: browse / open / recent persistence / no-library guards."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parents[0]))
from conftest import draw_scene, save_jpeg  # noqa: E402

from pcull import libraries
from pcull.server import create_app


@pytest.fixture()
def bare_client():
    return TestClient(create_app(None))


def test_no_library_rejects_data_endpoints(bare_client):
    assert bare_client.get("/api/photos").status_code == 400
    assert bare_client.get("/api/stats").status_code == 400
    # home page + browse still available
    r = bare_client.get("/")
    assert r.status_code == 200 and "pcull" in r.text
    assert bare_client.get("/api/library/current").json()["library"] is None


def test_browse_lists_drives_and_dirs(bare_client, tmp_path):
    root = bare_client.get("/api/browse").json()
    assert root["is_drive_list"] and root["entries"]

    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x")
    data = bare_client.get("/api/browse", params={"path": str(tmp_path)}).json()
    names = [e["name"] for e in data["entries"]]
    assert names == ["alpha", "beta"]
    assert data["parent"] == str(tmp_path.parent)

    assert bare_client.get("/api/browse", params={"path": "Z:/nope"}).status_code == 400


@pytest.fixture()
def small_lib(tmp_path: Path) -> Path:
    root = tmp_path / "pics"
    for i in range(3):
        save_jpeg(draw_scene(variant=f"lib{i}"), root / f"p{i}.jpg")
    return root


def test_open_library_flow(bare_client, small_lib, monkeypatch):
    monkeypatch.setattr(libraries, "RECENT_FILE",
                        small_lib.parent / "recent.json")
    r = bare_client.post("/api/library/open",
                         json={"path": str(small_lib)})
    assert r.status_code == 200 and r.json()["library"] == str(small_lib)

    # wait for background scan+analyze to finish
    deadline = time.time() + 60
    while time.time() < deadline:
        s = bare_client.get("/api/analyze/status").json()
        if not s["running"]:
            break
        time.sleep(0.3)
    assert not s["running"], "analysis did not finish in time"
    assert s["error"] is None

    assert bare_client.get("/api/library/current").json()["library"] == str(small_lib)
    photos = bare_client.get("/api/photos").json()
    assert photos["total"] == 3
    recents = bare_client.get("/api/library/recent").json()["libraries"]
    assert recents and recents[0]["path"] == str(small_lib)


def test_open_invalid_path(bare_client):
    assert bare_client.post("/api/library/open",
                            json={"path": "Z:/definitely/not/here"}).status_code == 400


def test_recent_drop_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(libraries, "RECENT_FILE", tmp_path / "recent.json")
    entries = libraries.add(Path(tmp_path) / "a")
    assert [e["path"] for e in entries] == [str(tmp_path / "a")]
    libraries.add(Path(tmp_path) / "b")
    entries = libraries.remove(str(tmp_path / "a"))
    assert [e["path"] for e in entries] == [str(tmp_path / "b")]
    # persisted file reflects the change
    assert libraries.load()[0]["path"] == str(tmp_path / "b")
