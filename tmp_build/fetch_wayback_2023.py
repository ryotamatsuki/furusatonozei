from __future__ import annotations

import json
from pathlib import Path

import requests

TARGET = "https://www.soumu.go.jp/main_content/000960672.xlsx"
CDX = "https://web.archive.org/cdx/search/cdx"


def main():
    out = Path("tmp_build/wayback_output")
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 data-recovery"})
    params = {
        "url": TARGET,
        "output": "json",
        "filter": "statuscode:200",
        "fl": "timestamp,original,statuscode,mimetype,digest,length",
        "collapse": "digest",
    }
    response = session.get(CDX, params=params, timeout=120)
    response.raise_for_status()
    captures = response.json()
    (out / "captures.json").write_text(json.dumps(captures, ensure_ascii=False, indent=2), encoding="utf-8")
    if len(captures) < 2:
        raise RuntimeError(f"No archived capture found: {captures!r}")
    errors = []
    for row in reversed(captures[1:]):
        timestamp = row[0]
        urls = [
            f"https://web.archive.org/web/{timestamp}id_/{TARGET}",
            f"https://web.archive.org/web/{timestamp}/{TARGET}",
        ]
        for url in urls:
            try:
                archived = session.get(url, timeout=240)
                if archived.status_code == 200 and archived.content[:2] == b"PK":
                    path = out / "000960672.xlsx"
                    path.write_bytes(archived.content)
                    (out / "source.json").write_text(json.dumps({"timestamp": timestamp, "url": url, "size": len(archived.content)}, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"downloaded {len(archived.content)} bytes from {url}")
                    return
                errors.append({"url": url, "status": archived.status_code, "size": len(archived.content), "prefix": archived.content[:80].decode("utf-8", errors="replace")})
            except Exception as exc:
                errors.append({"url": url, "error": repr(exc)})
    (out / "errors.json").write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
    raise RuntimeError("Archived workbook could not be downloaded")


if __name__ == "__main__":
    main()
