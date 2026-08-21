#!/usr/bin/env python3
"""Download and SHA-256 verify all official workbooks in the manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_data  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, action="append", help="download only this fiscal year; repeatable")
    args = parser.parse_args()
    manifest = json.loads(build_data.MANIFEST_PATH.read_text(encoding="utf-8"))
    years = args.year or list(range(int(manifest["period"]["start"]), int(manifest["period"]["end"]) + 1))
    for year in years:
        source = manifest["sources"][str(year)]
        for kind in ("receipts", "tax"):
            data = build_data.download_or_read(source, kind, no_download=False)
            print(f"{year} {kind}: {source[f'{kind}_file']} {build_data.sha256_bytes(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
