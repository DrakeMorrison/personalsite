#!/usr/bin/env python3
"""Archive every external link in posts/ and pages/ with the Wayback Machine.

Writes archive.json: {url: {"status": "ok"|"failed", "archived": wayback_url,
"timestamp": "YYYYMMDDhhmmss", "checked": "YYYY-MM-DD", "error": "..."}}.
build.py reads it to add a small "a" archive mark after each external link.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "archive.json"
OWN_HOSTS = {"drakemorrison.net", "www.drakemorrison.net"}
UA = "drakemorrison.net link archiver (drake.morrison@hey.com)"
LINK_RE = re.compile(r"\]\((https?://[^)\s]+)|<(https?://[^>\s]+)>|(?<![\](])(?<!\w)(https?://[^\s)<>\"']+)")


def collect_urls() -> list[str]:
    urls: set[str] = set()
    for md in list((ROOT / "posts").glob("*.md")) + list((ROOT / "pages").glob("*.md")):
        for m in LINK_RE.finditer(md.read_text(encoding="utf-8")):
            url = next(g for g in m.groups() if g)
            url = url.rstrip(".,;:!?")
            url = urllib.parse.urldefrag(url).url
            host = urllib.parse.urlparse(url).hostname or ""
            if host in OWN_HOSTS or host.endswith("archive.org"):
                continue
            urls.add(url)
    return sorted(urls)


def get(url: str, timeout: int = 90) -> tuple[int, dict, bytes, str]:
    """GET following redirects; returns (status, headers, body, final_url)."""
    req = urllib.request.Request(url, headers={"user-agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), b"", e.geturl() or url


def available(url: str) -> tuple[str, str] | None:
    q = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe="")
    status, _, body, _ = get(q, timeout=30)
    if status != 200:
        return None
    snap = json.loads(body).get("archived_snapshots", {}).get("closest")
    if not snap or not snap.get("available"):
        return None
    ts = snap["timestamp"]
    return f"https://web.archive.org/web/{ts}/{url}", ts


def save(url: str) -> tuple[str, str] | None:
    status, headers, _, final = get("https://web.archive.org/save/" + url)
    if status in (429, 502, 503, 504):
        raise RuntimeError(f"save returned {status}")
    # the save endpoint 302s to /web/<timestamp>/<url>; urlopen follows it, so read the final URL
    loc = " ".join([final, headers.get("Content-Location", ""), headers.get("Location", "")])
    m = re.search(r"/web/(\d{14})/", loc)
    if m:
        return f"https://web.archive.org/web/{m.group(1)}/{url}", m.group(1)
    time.sleep(10)
    return available(url)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-check every URL")
    ap.add_argument("--delay", type=float, default=6, help="seconds between save requests")
    ap.add_argument("--retry-days", type=int, default=7, help="retry failed entries older than this")
    a = ap.parse_args()

    data: dict = json.loads(ARCHIVE.read_text()) if ARCHIVE.exists() else {}
    today = dt.date.today().isoformat()
    urls = collect_urls()
    todo = []
    for u in urls:
        e = data.get(u)
        if a.force or e is None:
            todo.append(u)
        elif e.get("status") != "ok":
            checked = dt.date.fromisoformat(e.get("checked", "1970-01-01"))
            if (dt.date.today() - checked).days >= a.retry_days:
                todo.append(u)
    print(f"{len(urls)} external urls, {len(todo)} to check")
    if a.dry_run:
        for u in todo:
            print("  ", u)
        return
    for u in todo:
        entry = {"status": "failed", "checked": today}
        try:
            found = available(u)
            if not found:
                print(f"saving   {u}")
                found = save(u)
                time.sleep(a.delay)
            if found:
                entry = {"status": "ok", "archived": found[0], "timestamp": found[1], "checked": today}
                print(f"ok       {u} -> {found[0]}")
            else:
                entry["error"] = "no snapshot after save"
                print(f"pending  {u}")
        except Exception as ex:  # noqa: BLE001
            entry["error"] = str(ex)[:200]
            print(f"failed   {u}: {ex}")
        data[u] = entry
        ARCHIVE.write_text(json.dumps(dict(sorted(data.items())), indent=2, ensure_ascii=False) + "\n")
    # drop entries whose URL no longer appears anywhere
    stale = [u for u in data if u not in urls]
    for u in stale:
        del data[u]
    ARCHIVE.write_text(json.dumps(dict(sorted(data.items())), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote archive.json ({len(data)} entries, {len(stale)} stale removed)")


if __name__ == "__main__":
    main()
