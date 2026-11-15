#!/usr/bin/env python3
"""Smoke-check a deployed Vexo Match origin without using any secrets.

Usage:
    python scripts/smoke.py https://vexo-match.onrender.com
    VEXO_URL=https://vexo-match.onrender.com python scripts/smoke.py

Checks /healthz, /readyz, the unauthenticated API guard, and the phone page.
Free services sleep, so the first request may take about a minute to wake.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def get(base: str, path: str, timeout: float) -> tuple[int | None, str]:
    request = urllib.request.Request(base + path, headers={"User-Agent": "vexo-smoke/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(8192).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2048).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - report the class, never a DSN or traceback
        return None, type(exc).__name__


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default=os.environ.get("VEXO_URL"))
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    if not args.url:
        parser.error("pass the deployed URL or set VEXO_URL")
    base = args.url.rstrip("/")

    failures = 0
    for path, expected in (("/healthz", {200}), ("/readyz", {200}), ("/api/me", {401})):
        status, body = get(base, path, args.timeout)
        ok = status in expected
        failures += 0 if ok else 1
        extra = ""
        if path == "/readyz" and body:
            try:
                detail = json.loads(body)
                extra = f" schema_version={detail.get('schema_version')} database={detail.get('database')}"
            except json.JSONDecodeError:
                extra = f" body={body[:120]!r}"
        print(f"{'PASS' if ok else 'FAIL'} {path} -> {status}{extra}")

    status, _ = get(base, "/", args.timeout)
    if status == 200:
        print("PASS / -> 200 (phone page)")
    elif status == 404:
        print("WARN / -> 404 (ui/phone.html is not deployed yet)")
    else:
        print(f"WARN / -> {status}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
