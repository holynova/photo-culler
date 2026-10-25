"""pcull command line: scan / analyze / serve / apply / status."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="pcull", description="照片库评分清理工具 (score → review → safely trash)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_lib(p, help_text="photo library folder"):
        p.add_argument("library", type=Path, help=help_text)

    add_lib(sub.add_parser("scan", help="索引照片库 (文件/EXIF/尺寸)"))
    p_an = sub.add_parser("analyze", help="运行分析管线 (缩略图/质量/闭眼/去重)")
    add_lib(p_an)
    p_an.add_argument("--no-faces", action="store_true", help="跳过闭眼检测")
    p_an.add_argument("--workers", type=int, default=4)

    p_sv = sub.add_parser("serve", help="启动审片 Web UI（不带路径则从启动页选择）")
    p_sv.add_argument("library", type=Path, nargs="?", default=None,
                      help="photo library folder (optional)")
    p_sv.add_argument("--host", default="127.0.0.1")
    p_sv.add_argument("--port", type=int, default=8787)

    p_ap = sub.add_parser("apply", help="把标记为删除的文件移入回收站目录 (不直接删除)")
    add_lib(p_ap)
    p_ap.add_argument("--dry-run", action="store_true")

    p_st = sub.add_parser("status", help="打印库状态统计")
    add_lib(p_st)

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn
        from pcull.server import create_app

        uvicorn.run(create_app(args.library), host=args.host, port=args.port)
        return 0

    from pcull.db import connect

    conn = connect(args.library)

    if args.cmd == "scan":
        from pcull.scanner import scan_library
        counts = scan_library(args.library, conn)
        print(f"scan done: +{counts['added']} new, ~{counts['updated']} changed, "
              f"-{counts['removed']} removed "
              f"({counts['images']} images, {counts['videos']} videos seen)")
    elif args.cmd == "analyze":
        from pcull.pipeline import run_analysis
        run = run_analysis(args.library, conn, faces=not args.no_faces, workers=args.workers)
        print(run)
    elif args.cmd == "serve":
        import uvicorn
        from pcull.server import create_app
        uvicorn.run(create_app(args.library), host=args.host, port=args.port)
    elif args.cmd == "apply":
        from pcull.apply import apply_decisions
        result = apply_decisions(args.library, conn, dry_run=args.dry_run)
        print(result["summary"])
        if result["manifest"]:
            print(f"manifest: {result['manifest']}")
    elif args.cmd == "status":
        from pcull.scanner import status
        import json
        print(json.dumps(status(conn), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
