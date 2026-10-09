"""HTTP access to Swiggy's public web endpoints.

Stdlib only -- three GETs do not justify a dependency.

Host paths are not interchangeable. Restaurant data lives under `dapi`;
menus only work under `mapi`. `dapi/menu/pl` answers HTTP 202 with a
zero-byte body: it looks like a network or geo failure and is neither. The
identical query string succeeds under `mapi`. Retrying dapi with more
headers, cookies or params does not help -- that has been tested.

Every response passes through `cache`, keyed on endpoint and parameters
including the coordinate. `fresh=True` bypasses the cache and refetches;
empty responses are never cached.
"""

from __future__ import annotations

import gzip
import json
import urllib.parse
import urllib.request
from typing import Any

from . import cache

SEARCH = "https://www.swiggy.com/dapi/restaurants/search/v3"
LIST = "https://www.swiggy.com/dapi/restaurants/list/v5"
MENU = "https://www.swiggy.com/mapi/menu/pl"  # mapi. Not dapi. See module docstring.

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.swiggy.com/",
    "Accept-Encoding": "gzip",
}


class EmptyResponse(RuntimeError):
    """A 2xx with no body -- the signature of querying the wrong host path."""


#: True when the most recent fetch was served from cache. The CLI reads it to
#: skip the politeness sleep between calls that never touched the network.
last_was_cached = False


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        if not body:
            raise EmptyResponse(
                f"HTTP {r.status} with an empty body from {urllib.parse.urlsplit(url).path}. "
                "Menus require the mapi host path; dapi returns 202 and nothing else."
            )
        return json.loads(body)


def _fetch(kind: str, base: str, q: dict, fresh: bool) -> Any:
    """Cached GET. A hit announces its age on stderr; a miss stores the result."""
    global last_was_cached
    if not fresh:
        hit = cache.get(kind, q)
        if hit is not None:
            payload, age = hit
            cache.note_hit(kind, q, age)
            last_was_cached = True
            return payload
    payload = _get(f"{base}?{urllib.parse.urlencode(q)}")
    cache.put(kind, q, payload)
    last_was_cached = False
    return payload


def search(term: str, lat: float, lng: float, fresh: bool = False) -> Any:
    q = {
        "lat": lat,
        "lng": lng,
        "str": term,
        "trackingId": "null",
        "submitAction": "ENTER",
    }
    return _fetch("search", SEARCH, q, fresh)


def menu(restaurant_id: str | int, lat: float, lng: float, fresh: bool = False) -> Any:
    q = {
        "page-type": "REGULAR_MENU",
        "complete-menu": "true",
        "lat": lat,
        "lng": lng,
        "restaurantId": restaurant_id,
    }
    return _fetch("menu", MENU, q, fresh)


def nearby(lat: float, lng: float, fresh: bool = False) -> Any:
    """First page only.

    This endpoint paginates at 25 results and in a dense area reaches barely
    4 km, so anything further out is absent rather than unavailable. Never
    treat its output as the set of restaurants that deliver to a coordinate.
    """
    q = {"lat": lat, "lng": lng, "page_type": "DESKTOP_WEB_LISTING"}
    return _fetch("near", LIST, q, fresh)
