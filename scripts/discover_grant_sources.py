#!/usr/bin/env python3
"""Discover MIC ordinary local allocation tax municipality source links.

Diagnostic only. Production builds must use pinned official URLs and SHA-256
values from the manifest rather than scraping this page dynamically.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

URLS = [
    "https://www.soumu.go.jp/main_sosiki/c-zaisei/kouhu.html",
    "https://200.180.31.150.static.iijgio.jp/main_sosiki/c-zaisei/kouhu.html",
]
OUTPUT = Path("/tmp/grant-source-candidates.json")


def fetch(url: str) -> tuple[str, bytes, str]:
    req = Request(url, headers={"User-Agent": "furusato-grant-source-discovery/1.2"})
    with urlopen(req, timeout=60) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
    declared = re.search(r"charset=([\w-]+)", content_type, flags=re.I)
    encodings = [declared.group(1)] if declared else []
    encodings += ["utf-8", "cp932", "shift_jis"]
    for encoding in encodings:
        try:
            return raw.decode(encoding), raw, encoding
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", errors="replace"), raw, "utf-8-replace"


def clean(fragment: str) -> str:
    fragment = re.sub(r"<script[\s\S]*?</script>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<style[\s\S]*?</style>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def main() -> None:
    errors: list[str] = []
    for page_url in URLS:
        try:
            page, raw, encoding = fetch(page_url)
            break
        except Exception as exc:
            errors.append(f"{page_url}: {exc!r}")
    else:
        raise SystemExit("failed to fetch MIC grant page: " + "; ".join(errors))

    all_anchors = []
    candidates = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', page, flags=re.I):
        href, body = match.groups()
        start = max(0, match.start() - 1600)
        end = min(len(page), match.end() + 500)
        context = clean(page[start:end])
        label = clean(body)
        absolute = urljoin(page_url, html.unescape(href))
        item = {
            "label": label,
            "url": absolute,
            "context": context[-1000:],
        }
        all_anchors.append(item)
        combined = f"{label} {context} {href}"
        if any(token in combined for token in (
            "市町村別", "交付決定額", "変更決定額", "再算定", "普通交付税",
            "令和8年度", "令和7年度", "令和6年度", "令和5年度", "令和4年度", "令和3年度",
        )):
            candidates.append(item)

    payload = {
        "page_url": page_url,
        "encoding": encoding,
        "bytes": len(raw),
        "errors": errors,
        "page_text": clean(page),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "all_anchor_count": len(all_anchors),
        "all_anchors": all_anchors,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FETCHED {page_url} bytes={len(raw)} encoding={encoding} candidates={len(candidates)} all={len(all_anchors)}")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
