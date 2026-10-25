"""Phase 6: video support — probe, frame sampling, scoring, dedup."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pcull.analyzers.thumbs import thumb_path
from pcull.analyzers.video import analyze_video, probe
from pcull.db import connect
from pcull.pipeline import run_analysis
from pcull.scanner import scan_library


def make_video(ffmpeg: Path, out: Path, src: str, extra: list[str] | None = None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(ffmpeg), "-v", "error", "-y",
           "-f", "lavfi", "-i", f"{src}=duration=2:size=512x384:rate=12",
           *(extra or []), "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)


@pytest.fixture(scope="module")
def video_lib(tmp_path_factory):
    ffmpeg = pytest.importorskip("pcull.ffmpeg").ffmpeg()
    if ffmpeg is None:
        pytest.skip("ffmpeg not available")
    root = tmp_path_factory.mktemp("vlib")
    make_video(ffmpeg, root / "vid_sharp.mp4", "testsrc2")
    make_video(ffmpeg, root / "vid_blur.mp4", "testsrc2",
               ["-vf", "boxblur=8:2"])
    make_video(ffmpeg, root / "vid_dark.mp4", "testsrc2",
               ["-vf", "eq=brightness=-0.45"])
    # near-duplicate: same content, half bitrate
    make_video(ffmpeg, root / "vid_dup_a.mp4", "testsrc")
    subprocess.run(
        [str(ffmpeg), "-v", "error", "-y", "-i", str(root / "vid_dup_a.mp4"),
         "-b:v", "300k", str(root / "vid_dup_b.mp4")],
        check=True, capture_output=True, timeout=120,
    )
    return root


def test_probe_metadata(video_lib: Path):
    meta = probe(video_lib / "vid_sharp.mp4")
    assert abs(meta["duration"] - 2.0) < 0.3
    assert (meta["width"], meta["height"]) == (512, 384)


def test_analyze_video_scores_and_thumb(video_lib: Path, tmp_path: Path):
    sharp = analyze_video(tmp_path, video_lib / "vid_sharp.mp4")
    blur = analyze_video(tmp_path, video_lib / "vid_blur.mp4")
    assert sharp and sharp["blur"] > 30
    assert blur["blur"] < sharp["blur"] - 15
    assert sharp["phash"] and blur["phash"]

    # duplicate videos hash close, different content far
    dup_a = analyze_video(tmp_path, video_lib / "vid_dup_a.mp4")
    dup_b = analyze_video(tmp_path, video_lib / "vid_dup_b.mp4")
    d_same = bin(int(dup_a["phash"], 16) ^ int(dup_b["phash"], 16)).count("1")
    d_diff = bin(int(sharp["phash"], 16) ^ int(dup_a["phash"], 16)).count("1")
    assert d_same <= 6
    assert d_diff > 10


def test_video_pipeline_end_to_end(video_lib: Path):
    conn = connect(video_lib)
    scan_library(video_lib, conn)
    videos = conn.execute("SELECT id, rel_path FROM photos WHERE is_video=1").fetchall()
    assert len(videos) == 5

    summary = run_analysis(video_lib, conn, faces=False, workers=2)
    assert summary["analyzed"] == 5
    assert summary["failed"] == 0

    rows = {r["rel_path"]: dict(r) for r in conn.execute(
        """SELECT p.rel_path, p.width, p.height, p.duration, m.blur, m.score,
                  m.recommendation, p.id
           FROM photos p JOIN metrics m ON m.photo_id=p.id""")}
    assert rows["vid_sharp.mp4"]["width"] == 512
    assert abs(rows["vid_sharp.mp4"]["duration"] - 2.0) < 0.3
    assert rows["vid_blur.mp4"]["blur"] < rows["vid_sharp.mp4"]["blur"]
    assert rows["vid_dark.mp4"]["recommendation"] in ("delete", "review")
    assert thumb_path(video_lib, rows["vid_sharp.mp4"]["id"]).exists()

    # duplicate video pair grouped
    dup_group = conn.execute(
        """SELECT g.group_id FROM groups g
           JOIN photos p ON p.id = g.photo_id
           WHERE p.rel_path IN ('vid_dup_a.mp4','vid_dup_b.mp4')
           GROUP BY g.group_id HAVING COUNT(*) = 2"""
    ).fetchone()
    assert dup_group is not None
