from __future__ import annotations

import json
import tarfile
from pathlib import Path

import requests

URL = "https://raw.githubusercontent.com/passaglia/japandata-sources/main/furusatonouzei/furusatonouzeidata.tar.gz"


def main():
    out = Path("tmp_build/archive_output")
    out.mkdir(parents=True, exist_ok=True)
    archive = out / "furusatonouzeidata.tar.gz"
    response = requests.get(URL, timeout=240, headers={"User-Agent": "Mozilla/5.0 archive-builder"})
    response.raise_for_status()
    archive.write_bytes(response.content)
    extracted = out / "extracted"
    extracted.mkdir(exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(extracted, filter="data")
    files = []
    for path in sorted(extracted.rglob("*")):
        if path.is_file():
            files.append({"path": str(path.relative_to(extracted)), "size": path.stat().st_size})
    (out / "manifest.json").write_text(json.dumps(files, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(files[:100], ensure_ascii=False, indent=2))
    print(f"files={len(files)} size={len(response.content)}")


if __name__ == "__main__":
    main()
