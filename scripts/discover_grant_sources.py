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


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "furusato-grant-source-discovery/1.0"})
    with urlopen(req, timeout=60) as response:
        raw = response.read()
    for encoding in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def clean(fragment: str) -> str:
    fragment = re.sub(r"<script[\s\S]*?</script>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<style[\s\S]*?</style>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def main() -> None:
    last_error = None
    for page_url in URLS:
        try:
            page = fetch(page_url)
            break
        except Exception as exc:  # diagnostic command: report every fallback failure
            last_error = exc
    else:
        raise SystemExit(f"failed to fetch MIC grant page: {last_error}")

    anchors = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', page, flags=re.I):
        href, body = match.groups()
        start = max(0, match.start() - 260)
        end = min(len(page), match.end() + 120)
        context = clean(page[start:end])
        label = clean(body)
        if not any(token in context for token in ("普通交付税", "市町村別", "交付決定額", "変更決定額")):
            continue
        if not re.search(r"令和[３４５６７８]年度", context):
            continue
        anchors.append({
            "label": label,
            "context": context,
            "url": urljoin(page_url, html.unescape(href)),
        })
    print(json.dumps(anchors, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
