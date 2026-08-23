#!/usr/bin/env python3
"""Discover MIC ordinary local allocation tax municipality source links.

This utility is intentionally separate from the production parser. It is used
when pinning official source URLs into the manifest; production builds should
consume only already-pinned URLs and hashes.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen

URLS = [
    "https://www.soumu.go.jp/main_sosiki/c-zaisei/kouhu.html",
    "https://200.180.31.150.static.iijgio.jp/main_sosiki/c-zaisei/kouhu.html",
]


def fetch(url: str) -> tuple[str, bytes]:
    req = Request(url, headers={"User-Agent": "furusato-grant-source-discovery/1.1"})
    with urlopen(req, timeout=60) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
    declared = re.search(r"charset=([\w-]+)", content_type, flags=re.I)
    encodings = [declared.group(1)] if declared else []
    encodings += ["utf-8", "cp932", "shift_jis"]
    for encoding in encodings:
        try:
            return raw.decode(encoding), raw
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", errors="replace"), raw


def clean(fragment: str) -> str:
    fragment = re.sub(r"<script[\s\S]*?</script>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<style[\s\S]*?</style>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def main() -> None:
    last_error = None
    for page_url in URLS:
        try:
            page, raw = fetch(page_url)
            break
        except Exception as exc:
            last_error = exc
    else:
        raise SystemExit(f"failed to fetch MIC grant page: {last_error}")

    anchors = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', page, flags=re.I):
        href, body = match.groups()
        start = max(0, match.start() - 1400)
        end = min(len(page), match.end() + 300)
        context = clean(page[start:end])
        label = clean(body)
        combined = f"{label} {context} {href}"
        if not any(token in combined for token in ("市町村別", "交付決定額", "変更決定額", "普通交付税")):
            continue
        anchors.append({
            "label": label,
            "context": context[-700:],
            "url": urljoin(page_url, html.unescape(href)),
        })
    print(f"FETCHED {page_url} bytes={len(raw)} anchors={len(anchors)}")
    print(json.dumps(anchors, ensure_ascii=False, indent=2))
    if not anchors:
        print("PAGE_TEXT_SAMPLE")
        print(clean(page)[:8000])


if __name__ == "__main__":
    main()
