#!/usr/bin/env python3
"""Scrape Fitbod's public exercise directory from Internet Archive snapshots.

fitbod.me sits behind a Cloudflare bot wall, but the Wayback Machine has the
SEO exercise pages archived. Each page is a Next.js App Router document whose
React flight stream (self.__next_f.push) embeds the full structured exercise
entity (name, slug, muscles, equipment, instructions, level, media URLs,
popularity/efficacy rankings, related/most-replaced exercises).

Stages (resumable; re-run safe):
  python3 scrape_fitbod.py fetch   # download latest archived snapshot per slug
  python3 scrape_fitbod.py parse   # decode cached HTML -> fitbod_exercises.json

Inputs:  ~/.cache/fitbod-scrape/slugs.txt       (from the Wayback CDX API)
Cache:   ~/.cache/fitbod-scrape/raw/<slug>.html (raw snapshot bytes, id_ flag)
Output:  ./fitbod_exercises.json                (full detail records)
         ./fitbod_summaries.json                (summary-only sightings)
         ~/.cache/fitbod-scrape/fetch_log.jsonl / parse_failures.json
"""

from __future__ import annotations

import gzip
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

CACHE = Path.home() / ".cache" / "fitbod-scrape"
RAW = CACHE / "raw"
OUT_DIR = Path(__file__).resolve().parent
SLUGS_FILE = CACHE / "slugs.txt"
TARGETS_FILE = CACHE / "targets.json"  # slug -> {ts, url} from bulk CDX
FETCH_LOG = CACHE / "fetch_log.jsonl"

# Direct capture URL (exact timestamp from CDX) — avoids the 302 nearest-
# capture lookup, halving connections; keep-alive sessions avoid per-request
# TLS handshakes (archive.org rate-limits at the connection level).
WAYBACK_FMT = "https://web.archive.org/web/{ts}id_/{url}"
USER_AGENT = "health-dashboard-exercise-research/0.1 (personal project; +https://viktorbarzin.me)"

CONCURRENCY = 5
MIN_INTERVAL_S = 0.25  # global politeness floor between request starts
RETRIES = 5
TIMEOUT_S = 60
MIN_VALID_BYTES = 5000  # a real snapshot is ~200 KB; tiny bodies are error pages

_rate_lock = threading.Lock()
_last_start = [0.0]
_tls = threading.local()


def _pace() -> None:
    """Global min-interval between request starts (token-bucket-lite)."""
    with _rate_lock:
        wait = _last_start[0] + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_start[0] = time.monotonic()


def _session() -> requests.Session:
    if not hasattr(_tls, "session"):
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        _tls.session = s
    return _tls.session


def fetch_one(item: tuple[str, dict]) -> dict:
    slug, target = item
    dest = RAW / f"{slug}.html"
    if dest.exists() and dest.stat().st_size >= MIN_VALID_BYTES:
        return {"slug": slug, "status": "cached", "bytes": dest.stat().st_size}
    url = WAYBACK_FMT.format(ts=target["ts"], url=target["url"])
    last_err = ""
    for attempt in range(RETRIES):
        _pace()
        try:
            resp = _session().get(url, timeout=TIMEOUT_S)
            if resp.status_code == 404:
                return {"slug": slug, "status": "no_capture_404"}
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
            else:
                body = resp.content  # requests decodes Content-Encoding
                if body[:2] == b"\x1f\x8b":  # double-compressed safety net
                    body = gzip.decompress(body)
                if len(body) < MIN_VALID_BYTES:
                    last_err = f"short body {len(body)}B"
                else:
                    dest.write_bytes(body)
                    return {
                        "slug": slug,
                        "status": "fetched",
                        "bytes": len(body),
                        "final_url": resp.url,
                    }
        except Exception as e:  # ConnectionError, timeout, ...
            last_err = f"{type(e).__name__}: {e}"
        # backoff: 2, 4, 8, 16s (+jitter); 429/5xx and refusals land here
        time.sleep(2 ** (attempt + 1) + random.random())
    return {"slug": slug, "status": "failed", "error": last_err}


def cmd_fetch() -> None:
    targets = json.loads(TARGETS_FILE.read_text())
    items = sorted(targets.items())
    RAW.mkdir(parents=True, exist_ok=True)
    done = 0
    counts: dict[str, int] = {}
    with FETCH_LOG.open("a") as log, ThreadPoolExecutor(CONCURRENCY) as pool:
        for res in pool.map(fetch_one, items):
            done += 1
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            log.write(json.dumps(res) + "\n")
            log.flush()
            if done % 25 == 0 or done == len(items):
                print(f"[{done}/{len(items)}] {counts}", flush=True)
    print("fetch complete:", counts, flush=True)


# --------------------------------------------------------------------------
# parse stage
# --------------------------------------------------------------------------

_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_ROW_RE = re.compile(r"^([0-9a-f]*):(.*)$", re.S)


def flight_rows(html: str):
    """Decode the React flight stream and yield JSON payloads per row.

    Flight rows are `<id>:<typed payload>` — payloads may be bare JSON
    (`{...}`, `[...]`, `"..."`), typed refs (`I[...]`, `HL[...]`), or raw
    text (`T<hexlen>,...`). We decode the first JSON literal in each row;
    rows whose payload isn't JSON are skipped.
    """
    stream = "".join(json.loads(m.group(1)) for m in _PUSH_RE.finditer(html))
    dec = json.JSONDecoder()
    for line in stream.split("\n"):
        m = _ROW_RE.match(line)
        if not m:
            continue
        payload = m.group(2)
        for i, ch in enumerate(payload):
            if ch in '[{"':
                try:
                    obj, _ = dec.raw_decode(payload[i:])
                    yield obj
                except json.JSONDecodeError:
                    pass
                break


def walk(obj):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def is_detail(d) -> bool:
    return (
        isinstance(d, dict)
        and isinstance(d.get("exercise"), dict)
        and "slug" in d["exercise"]
        and "instructions" in d["exercise"]
    )


def is_summary(d) -> bool:
    return (
        isinstance(d, dict)
        and isinstance(d.get("slug"), str)
        and isinstance(d.get("name"), str)
        and "primaryMuscleGroups" in d
    )


def next_data_fallback(html: str):
    """Older captures may be pages-router: <script id="__NEXT_DATA__">."""
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S
    )
    if m:
        try:
            yield json.loads(m.group(1))
        except json.JSONDecodeError:
            return


def parse_one(path: Path):
    html = path.read_text(errors="replace")
    detail = None
    summaries = {}
    sources = [flight_rows(html)]
    if "__next_f" not in html:
        sources = [next_data_fallback(html)]
    for rows in sources:
        for row in rows:
            for node in walk(row):
                if detail is None and is_detail(node):
                    detail = node
                elif is_summary(node):
                    summaries[node["slug"]] = {
                        "slug": node["slug"],
                        "name": node["name"],
                        "primaryMuscleGroups": node.get("primaryMuscleGroups"),
                        "level": node.get("level"),
                        "equipment": [
                            e.get("name") for e in node.get("equipment") or []
                        ],
                    }
    return detail, summaries


def cmd_parse() -> None:
    exercises: dict[str, dict] = {}
    summaries: dict[str, dict] = {}
    index_pages: list[str] = []
    failures: list[str] = []
    files = sorted(RAW.glob("*.html"))
    for i, path in enumerate(files, 1):
        slug = path.stem
        try:
            detail, summ = parse_one(path)
        except Exception as e:
            failures.append(f"{slug}: {type(e).__name__}: {e}")
            continue
        for s, v in summ.items():
            summaries.setdefault(s, v)
        if detail:
            ex = detail["exercise"]
            record = dict(ex)
            record["_page_title"] = detail.get("title")
            record["_source_url"] = f"https://fitbod.me/exercises/{slug}"
            record["_related_exercises"] = [
                {
                    "slug": r["exercise"].get("slug"),
                    "name": r["exercise"].get("name"),
                    "strategy": (r.get("metadata") or {}).get("strategy"),
                    "frequency": (r.get("metadata") or {}).get("frequency"),
                }
                for r in detail.get("relatedExercises") or []
                if isinstance(r, dict) and isinstance(r.get("exercise"), dict)
            ]
            if ex.get("slug") != slug:
                record["_fetched_as"] = slug
            exercises[ex.get("slug") or slug] = record
        else:
            index_pages.append(slug)  # muscle-group/browse page or unparsable
        if i % 100 == 0:
            print(f"parsed {i}/{len(files)}", flush=True)

    detail_slugs = set(exercises)
    summary_only = {
        s: v for s, v in summaries.items() if s not in detail_slugs
    }
    meta = {
        "source": "fitbod.me/exercises/<slug> via web.archive.org snapshots",
        "method": "Next.js flight-stream (self.__next_f) JSON extraction",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "detail_records": len(exercises),
        "summary_only_records": len(summary_only),
        "non_detail_pages": sorted(index_pages),
        "parse_failures": failures,
    }
    out = {"_meta": meta, "exercises": dict(sorted(exercises.items()))}
    (OUT_DIR / "fitbod_exercises.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False)
    )
    (OUT_DIR / "fitbod_summaries.json").write_text(
        json.dumps(dict(sorted(summary_only.items())), indent=1, ensure_ascii=False)
    )
    (CACHE / "parse_failures.json").write_text(json.dumps(failures, indent=1))
    print(
        f"parse complete: {len(exercises)} detail records, "
        f"{len(summary_only)} summary-only, {len(index_pages)} non-detail pages, "
        f"{len(failures)} failures"
    )


if __name__ == "__main__":
    {"fetch": cmd_fetch, "parse": cmd_parse}[sys.argv[1]]()
