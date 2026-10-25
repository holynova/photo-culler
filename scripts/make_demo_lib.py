"""Generate a realistic demo library for end-to-end testing/UI QA.

Usage: python scripts/make_demo_lib.py [target_dir]   (default: ./demo-lib)
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import draw_scene, save_jpeg  # noqa: E402

import datetime as dt  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402


def main(target: Path) -> None:
    rng = random.Random(42)
    target.mkdir(parents=True, exist_ok=True)
    base = dt.datetime(2024, 6, 1, 9, 0)

    n = 0

    def add(img, name, exif_days=0):
        nonlocal n
        stamp = base + dt.timedelta(days=exif_days, minutes=n)
        save_jpeg(img, target / name,
                  exif_date=stamp.strftime("%Y:%m:%d %H:%M:%S"))
        n += 1

    # 24 decent photos across "days"
    for i in range(24):
        add(draw_scene(variant=f"day{i}"), f"DCIM/day{i:02d}.jpg", exif_days=i // 4)

    # blur spectrum
    for i, radius in enumerate((1.2, 1.8, 2.2, 3.0, 4.5, 7.0, 12.0, 20.0)):
        img = draw_scene(variant=f"blurscene{i}")
        add(img.filter(ImageFilter.GaussianBlur(radius)), f"DCIM/blur_{radius}.jpg")

    # exposure problems
    add(draw_scene(variant="dark"), "DCIM/dark1.jpg")
    add(draw_scene(variant="dark2"), "DCIM/dark2.jpg")
    add(draw_scene(variant="overexposed"), "DCIM/blown1.jpg")

    # dull
    add(draw_scene(variant="dull"), "DCIM/dull1.jpg")

    # duplicate groups: 3 pairs + 1 triple of bursts
    for g, seed in enumerate(("g1", "g2", "g3")):
        src = draw_scene(variant=seed)
        add(src, f"DCIM/burst{g}_a.jpg")
        add(src.resize((1400, 1050)), f"DCIM/burst{g}_b.jpg")
    src = draw_scene(variant="g4")
    add(src, "DCIM/triple_a.jpg")
    add(Image.eval(src, lambda v: int(v * 0.85)), "DCIM/triple_b.jpg")  # exposure flicker
    add(src.resize((1280, 960)), "DCIM/triple_c.jpg")

    print(f"generated {n} photos in {target}")


def make_videos(target: Path) -> None:
    import subprocess
    import sys as _sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from pcull.ffmpeg import ffmpeg

    exe = ffmpeg()
    if exe is None:
        print("ffmpeg not found — skipping demo videos")
        return

    def make(name: str, src: str, extra: list[str] | None = None):
        subprocess.run(
            [str(exe), "-v", "error", "-y", "-f", "lavfi", "-i",
             f"{src}=duration=3:size=640x480:rate=15", *(extra or []),
             "-pix_fmt", "yuv420p", str(target / "DCIM" / name)],
            check=True, capture_output=True, timeout=120,
        )

    make("vid_sharp.mp4", "testsrc2")
    make("vid_shaky_blur.mp4", "testsrc2", ["-vf", "boxblur=6:2"])
    make("vid_dark.mp4", "testsrc2", ["-vf", "eq=brightness=-0.4"])
    make("vid_dup_a.mp4", "testsrc")
    subprocess.run(
        [str(exe), "-v", "error", "-y", "-i", str(target / "DCIM" / "vid_dup_a.mp4"),
         "-b:v", "400k", str(target / "DCIM" / "vid_dup_b.mp4")],
        check=True, capture_output=True, timeout=120,
    )
    print("generated 5 demo videos")


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-lib").resolve()
    main(target)
    make_videos(target)
