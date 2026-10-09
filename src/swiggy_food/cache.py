"""On-disk cache of raw responses, plus a log of past questions.

Two stores, both under `cache/` in the data directory (`DATA`):

    responses/   one gzipped file per (endpoint, params) -- the payload
    queries.jsonl   one line per question asked, with its headline answer

The cache exists for recall and for cost, not for truth. Restaurant data
moves: prices change with offers, ratings drift between calls, kitchens close.
So entries are kept for 90 days but every read reports its age, and anything
older than `STALE_AFTER` is called out loudly -- a cached answer is a starting
point to confirm with `--fresh`, never a quotable price.

Cache keys include the coordinate, rounded to ~10 m. A query from a different
address is a different query; reusing a payload across coordinates would
reintroduce exactly the wrong-origin failure `geo` exists to prevent.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

TTL = 90 * 24 * 3600           # keep for 90 days
STALE_AFTER = 3 * 24 * 3600    # past this, say so in every read

# Outside the package, so an installed copy (a plugin update replaces the code
# directory) keeps its saved places and cache.
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "swiggy-food"
ROOT = Path(os.environ.get("SWIGGY_FOOD_CACHE") or DATA / "cache")
RESPONSES = ROOT / "responses"
QUERY_LOG = ROOT / "queries.jsonl"


def _norm(params: dict) -> dict:
    """Canonical form of a request's parameters.

    Coordinates are rounded to 4 decimals (~11 m) so that trivially different
    origins -- a re-geocode of the same locality, say -- share a cache entry,
    while a genuinely different address does not.
    """
    out = {}
    for k, v in params.items():
        if k in ("lat", "lng") and v is not None:
            out[k] = round(float(v), 4)
        else:
            out[k] = str(v).strip().lower() if isinstance(v, str) else v
    return out


def key_for(kind: str, params: dict) -> str:
    blob = json.dumps({"kind": kind, **_norm(params)}, sort_keys=True)
    return f"{kind}-{hashlib.sha256(blob.encode()).hexdigest()[:20]}"


def _path(kind: str, params: dict) -> Path:
    return RESPONSES / f"{key_for(kind, params)}.json.gz"


def human_age(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172800:
        return f"{seconds / 3600:.0f}h"
    return f"{seconds / 86400:.0f}d"


def get(kind: str, params: dict, ttl: float = TTL) -> tuple[Any, float] | None:
    """Return `(payload, age_seconds)` for a live entry, or None."""
    p = _path(kind, params)
    if not p.exists():
        return None
    try:
        entry = json.loads(gzip.decompress(p.read_bytes()))
    except (OSError, ValueError, gzip.BadGzipFile):
        p.unlink(missing_ok=True)
        return None
    age = time.time() - entry.get("fetched_at", 0)
    if age > ttl:
        return None
    return entry["payload"], age


def put(kind: str, params: dict, payload: Any) -> None:
    RESPONSES.mkdir(parents=True, exist_ok=True)
    entry = {"kind": kind, "params": _norm(params), "fetched_at": time.time(),
             "payload": payload}
    tmp = _path(kind, params).with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(entry).encode()))
    tmp.replace(_path(kind, params))


def note_hit(kind: str, params: dict, age: float) -> None:
    """Tell the caller, on stderr, that this data is remembered and how old."""
    what = params.get("str") or params.get("restaurantId") or "nearby"
    line = f"  cache: {kind} {what!r} from {human_age(age)} ago"
    if age > STALE_AFTER:
        line += "  -- STALE: confirm prices/ratings with --fresh before quoting"
    print(line, file=sys.stderr)


def log_query(record: dict) -> None:
    """Append one answered question to the recall log."""
    ROOT.mkdir(parents=True, exist_ok=True)
    record = {"at": time.time(), **record}
    with QUERY_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")


def past_queries(limit: int | None = None, grep: str | None = None) -> list[dict]:
    """Logged questions, newest first, expired ones dropped."""
    if not QUERY_LOG.exists():
        return []
    now = time.time()
    rows = []
    for line in QUERY_LOG.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if now - r.get("at", 0) > TTL:
            continue
        if grep and grep.lower() not in json.dumps(r).lower():
            continue
        rows.append(r)
    rows.reverse()
    return rows[:limit] if limit else rows


def _stored() -> list[tuple[Path, float, int]]:
    """Every response file with its own recorded age, not the file's mtime.

    mtime shifts when a directory is copied or synced; `fetched_at` is when the
    data actually came off the wire, which is the only age worth reporting.
    """
    out = []
    now = time.time()
    for f in RESPONSES.glob("*.json.gz") if RESPONSES.exists() else []:
        try:
            fetched = json.loads(gzip.decompress(f.read_bytes())).get("fetched_at", 0)
        except (OSError, ValueError, gzip.BadGzipFile):
            fetched = f.stat().st_mtime
        out.append((f, now - fetched, f.stat().st_size))
    return out


def stats() -> dict:
    entries = _stored()
    return {
        "entries": len(entries),
        "bytes": sum(size for _, _, size in entries),
        "oldest": max((age for _, age, _ in entries), default=0),
        "newest": min((age for _, age, _ in entries), default=0),
        "queries": len(past_queries()),
    }


def purge(ttl: float = TTL) -> int:
    """Drop expired responses and log lines. Returns responses removed."""
    dropped = 0
    for f, age, _ in _stored():
        if age > ttl:
            f.unlink(missing_ok=True)
            dropped += 1
    if QUERY_LOG.exists():
        kept = [json.dumps(r) for r in reversed(past_queries())]
        QUERY_LOG.write_text("\n".join(kept) + ("\n" if kept else ""))
    return dropped


def clear() -> int:
    n = 0
    for f in RESPONSES.glob("*.json.gz") if RESPONSES.exists() else []:
        f.unlink(missing_ok=True)
        n += 1
    QUERY_LOG.unlink(missing_ok=True)
    return n
