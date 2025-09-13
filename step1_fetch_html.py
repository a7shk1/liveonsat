#!/usr/bin/env python3
"""
Step 1: Fetch raw HTML from LiveOnSat (2day.php) so we can inspect structure.

Usage:
  python step1_fetch_html.py --url https://liveonsat.com/2day.php --out outputs

Notes:
- Uses a desktop User-Agent and robust retries/timeouts.
- Falls back to http:// if https is slow.
- Saves two files:
    outputs/raw_YYYYmmdd_HHMMSS.html
    outputs/raw_latest.html
- Prints a short summary (status, length, <title> if found).
"""
from __future__ import annotations
import argparse, sys, re
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_URL = "https://liveonsat.com/2day.php"
FALLBACK_URLS = ["http://liveonsat.com/2day.php"]

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

def build_session(retries_total: int = 5, backoff_factor: float = 1.2) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=retries_total,
        connect=retries_total,
        read=retries_total,
        status=retries_total,
        backoff_factor=backoff_factor,
        allowed_methods=frozenset(["GET", "HEAD"]),
        status_forcelist=(429, 500, 502, 503, 504),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def fetch_html(
    url: str,
    timeout_connect: int = 10,
    timeout_read: int = 60,
    ua: str = DEFAULT_UA,
    alt_urls: list[str] | None = None,
) -> str:
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8,ar;q=0.6",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
    }
    session = build_session()
    urls = [url] + list(alt_urls or [])
    last_exc = None
    for u in urls:
        try:
            r = session.get(u, headers=headers, timeout=(timeout_connect, timeout_read), allow_redirects=True)
            r.raise_for_status()
            return r.text
        except requests.exceptions.RequestException as e:
            last_exc = e
            continue
    raise last_exc if last_exc else RuntimeError("Failed to fetch HTML")

def main():
    ap = argparse.ArgumentParser(description="Fetch LiveOnSat HTML (step 1)")
    ap.add_argument("--url", default=DEFAULT_URL, help="page URL (default: LiveOnSat 2day.php)")
    ap.add_argument("--out", default="outputs", help="output directory to save HTML")
    ap.add_argument("--connect-timeout", type=int, default=10)
    ap.add_argument("--read-timeout", type=int, default=60)
    ap.add_argument("--ua", default=DEFAULT_UA)
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    html = fetch_html(
        args.url,
        timeout_connect=args.connect-timeout if hasattr(args, "connect-timeout") else args.connect_timeout,
        timeout_read=args.read-timeout if hasattr(args, "read-timeout") else args.read_timeout,
        ua=args.ua,
        alt_urls=FALLBACK_URLS,
    )

    # File names
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path_ts = outdir / f"raw_{ts}.html"
    path_latest = outdir / "raw_latest.html"
    path_ts.write_text(html, encoding="utf-8", errors="ignore")
    path_latest.write_text(html, encoding="utf-8", errors="ignore")

    # Small summary to stdout
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else "(no <title> found)"
    print(f"[OK] Saved: {path_ts.name} ({len(html):,} bytes)")
    print(f"    Latest: {path_latest.name}")
    print(f"    <title>: {title}")

if __name__ == "__main__":
    # argparse uses hyphen names; map to underscores for attribute access fallback
    # (Workaround for Windows PowerShell weirdness with hyphenated long options).
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)
        sys.exit(130)
