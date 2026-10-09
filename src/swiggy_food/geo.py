"""Resolving a question's location into a coordinate.

Ordering matters. A coordinate that is a few km off still returns a full,
plausible-looking result set -- wrong restaurants at believable distances --
so this module prefers sources that are exact and refuses to silently use
sources that are not.

    saved place   exact, confirmed once by a human        -- preferred
    locality      centroid of a named area, ~1km accurate -- fine for "in X"
    IP address    city-level, measured 14km off in test   -- never silent

Swiggy's own geocoding endpoints (dapi/misc/place-autocomplete and
address-recommend) return 404; there is no first-party option.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .cache import DATA

NOMINATIM = "https://nominatim.openstreetmap.org/search"
IP_LOOKUP = "http://ip-api.com/json/"

# Nominatim requires a genuine identifying User-Agent and one request/second.
UA = "swiggy-food (personal food research tool)"

PLACES_FILE = DATA / "places.json"


class LocationUnknown(RuntimeError):
    """No coordinate could be resolved, and guessing one is not acceptable."""


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line km. Road distance is longer; Swiggy reports its own."""
    r = math.radians
    a = (math.sin(r(lat2 - lat1) / 2) ** 2
         + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lng2 - lng1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


def geocode(query: str, limit: int = 5) -> list[dict]:
    """Look up a place name. Returns candidates, most relevant first.

    Deliberately returns several. Locality names repeat across cities and
    within them, and picking the top hit unseen is how you end up ranking
    restaurants around the wrong Koramangala. Include the city in the query
    when you know it.
    """
    q = urllib.parse.urlencode({"q": query, "format": "json", "limit": limit,
                                "addressdetails": 1})
    out = []
    for row in _get(f"{NOMINATIM}?{q}"):
        out.append({
            "label": row.get("display_name"),
            "name": row.get("name"),
            "lat": float(row["lat"]),
            "lng": float(row["lon"]),
            "kind": row.get("addresstype") or row.get("type"),
        })
    return out


def ip_fix() -> dict | None:
    """City-level guess from the IP address. Coarse -- always confirm it.

    Measured 14.1 km from the true address on a home connection: far enough
    that every distance, every ranking and every "is it deliverable" answer
    derived from it was wrong, while looking entirely reasonable. Present it
    as a question, never as the answer.
    """
    try:
        d = _get(IP_LOOKUP)
    except Exception:
        return None
    if d.get("status") != "success":
        return None
    return {
        "label": f"{d.get('city')}, {d.get('regionName')} (from IP -- city-level only)",
        "lat": d["lat"],
        "lng": d["lon"],
        "kind": "ip",
    }


def load_places() -> dict[str, dict]:
    if not PLACES_FILE.exists():
        return {}
    try:
        return json.loads(PLACES_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save_place(name: str, lat: float, lng: float, label: str = "") -> Path:
    """Persist a confirmed coordinate under a short name such as 'home'.

    Worth storing precisely because it does not go stale the way restaurant
    and menu data does -- an address is true until someone moves.
    """
    places = load_places()
    places[name] = {"lat": lat, "lng": lng, "label": label}
    PLACES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLACES_FILE.write_text(json.dumps(places, indent=2) + "\n")
    return PLACES_FILE


def resolve(place: str | None, lat: float | None, lng: float | None) -> tuple[float, float, str]:
    """Turn whatever the caller supplied into one coordinate.

    Explicit coordinates win. Then a saved place by name. Then a geocoded
    locality, but only when it is unambiguous -- several candidates means the
    caller has to choose, because picking silently is the failure this whole
    module exists to prevent.
    """
    if lat is not None and lng is not None:
        return lat, lng, "explicit coordinate"

    if not place:
        raise LocationUnknown(
            "No location given. Pass --lat/--lng, or --place with a saved name or a "
            "locality. Saved names: " + (", ".join(load_places()) or "none yet") + ". "
            "Do not guess -- resolve it with the user first."
        )

    saved = load_places().get(place)
    if saved:
        return saved["lat"], saved["lng"], f"saved place '{place}' ({saved.get('label') or ''})".strip()

    hits = geocode(place)
    if not hits:
        raise LocationUnknown(f"Could not geocode {place!r}. Add the city and try again.")
    if len(hits) > 1:
        far = [h for h in hits if haversine(hits[0]["lat"], hits[0]["lng"], h["lat"], h["lng"]) > 2]
        if far:
            opts = "\n".join(f"  {h['lat']:.4f},{h['lng']:.4f}  {h['label']}" for h in hits)
            raise LocationUnknown(
                f"{place!r} is ambiguous -- {len(hits)} candidates more than 2km apart:\n{opts}\n"
                "Re-run with the city included, or with --lat/--lng."
            )
    h = hits[0]
    return h["lat"], h["lng"], f"{h['label']} (locality centroid)"
