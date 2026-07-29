"""NovelOS CLI.

Goal 0 stub: only ``version`` is implemented — enough for the smoke test.
Full verb set (doctor/init/status/next/integrity-scan) lands with Goal 1.
"""

from __future__ import annotations

import argparse
import json
import sys

from novelos import __version__

PROTOCOL_VERSION = "1.0"
MIN_EXTENSION_VERSION = "0.1.0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="novelos")
    sub = parser.add_subparsers(dest="command")

    version_parser = sub.add_parser("version", help="Core 与协议版本")
    version_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "version":
        data = {
            "core_version": __version__,
            "protocol_version": PROTOCOL_VERSION,
            "min_extension_version": MIN_EXTENSION_VERSION,
        }
        if args.json:
            print(json.dumps({"ok": True, "data": data, "errors": []}, ensure_ascii=False))
        else:
            print(f"novelos {__version__} (protocol {PROTOCOL_VERSION})")
        return 0

    parser.print_usage(sys.stderr)
    return 4
