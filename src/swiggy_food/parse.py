"""Parsing for Swiggy's search and menu payloads.

Everything here exists because a naive parse gets it wrong. Each function
documents the specific shape that breaks the obvious implementation.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterator

NUTRI = re.compile(
    r"Energy:\s*([\d.]+)\s*kcal.*?Protein:\s*([\d.]+)\s*g.*?"
    r"Carbohydrates:\s*([\d.]+)\s*g.*?Fat:\s*([\d.]+)\s*g",
    re.I | re.S,
)

IMG_BASE = "https://media-assets.swiggy.com/swiggy/image/upload/"
IMG_TRANSFORM = "fl_lossy,f_auto,q_auto,w_660/"


def rupees(v: Any) -> float | None:
    """Prices are always in paise. 62500 -> 625.0.

    Divide unconditionally. A "only divide if it looks big" guard silently
    turns a Rs 9 item into Rs 900.
    """
    try:
        return round(float(v) / 100, 2)
    except (TypeError, ValueError):
        return None


def count(v: Any) -> int | None:
    """Rating counts arrive in two incompatible shapes.

    'ratingCount' is a sentence: '1606 ratings'.
    'ratingCountV2' is abbreviated: '1.6K+'.

    Stripping only punctuation turns '1.6K+' into 16000 -- a 10x inflation --
    and makes int('1606 ratings') raise, which reads downstream as zero
    reviews and quietly disables review-count weighting entirely.
    """
    if v is None:
        return None
    m = re.match(r"\s*([\d.]+)\s*([Kk])?", str(v).replace("+", ""))
    if not m:
        return None
    n = float(m.group(1))
    return int(n * 1000) if m.group(2) else int(n)


def km(sla: Any) -> float | None:
    """Distance is a float on listing payloads, a string ('1.9 km') on search."""
    if not isinstance(sla, dict):
        return None
    v = sla.get("lastMileTravel")
    if isinstance(v, (int, float)):
        return round(float(v), 1)
    m = re.match(r"([\d.]+)", str(sla.get("lastMileTravelString") or ""))
    return float(m.group(1)) if m else None


def nutrition(desc: str | None) -> dict[str, float] | None:
    """Vendor nutrition is embedded in the description prose, never a field.

    Treat anything found here as vendor-published and anything else as an
    estimate -- the two must not be presented alike.
    """
    m = NUTRI.search(desc or "")
    if not m:
        return None
    return {
        "kcal": float(m.group(1)),
        "protein_g": float(m.group(2)),
        "carbs_g": float(m.group(3)),
        "fat_g": float(m.group(4)),
    }


def image_url(image_id: Any) -> str | None:
    """CDN URL for a dish's `imageId` or a restaurant's `cloudinaryImageId`.

    Ids arrive in three shapes and every one of them takes the *same* prefix,
    so there is nothing to branch on:

        FOOD_CATALOG/IMAGES/CMS/2026/1/29/2e9d...jpeg   path-style
        2bd6fc12225ff50e770c3dd665ac7ac9                bare cloudinary id
        FOOD_CATALOG/.../...dece.jpg_compressed         path + _compressed

    Code that sniffs the shape first is doing work the CDN already does.

    The transform segment is a size decision, not decoration: it took one real
    dish photo from 571 KB to 46 KB with no loss of legibility. Drop it only if
    you specifically want the original.

    Read the id off the item's own `info` dict and nowhere else. `imageBadges[]`
    and `imageBased.badgeObject[].attributes` carry an `imageId` too, but those
    are badge artwork -- 'Pure Veg', 'Best in Chinese' PNGs. Reimplementing this
    as a walk() for any 'imageId' key silently files that artwork as food
    photography.
    """
    if not image_id or not isinstance(image_id, str):
        return None
    return IMG_BASE + IMG_TRANSFORM + image_id


def rating(info: dict) -> tuple[float | None, int | None]:
    agg = (info.get("ratings") or {}).get("aggregatedRating") or {}
    try:
        r = float(agg.get("rating"))
    except (TypeError, ValueError):
        r = None
    return r, count(agg.get("ratingCount") or agg.get("ratingCountV2"))


def walk(node: Any) -> Iterator[dict]:
    """Yield every dict in the tree.

    Swiggy's card nesting changes between response shapes and over time, so
    match on structure rather than hardcoding paths like
    data/cards[1]/groupedCard/cardGroupMap/DISH/...
    """
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def search_results(doc: Any) -> tuple[list[dict], dict[int, dict]]:
    """Split a search payload into dishes and restaurants.

    The owning restaurant is a SIBLING of the dish array, one level above each
    dish -- {'restaurant': {...}, 'dishes': [...]}. Looking for 'restaurant' on
    the dish node itself finds nothing, which strips every dish of its shop
    name, rating and distance, and makes any distance filter silently inert.

    Both halves are returned because a term can produce a restaurant-shaped
    response carrying no dish data at all. Those restaurants are leads, not
    absences -- see orphans().
    """
    dishes: list[dict] = []
    restaurants: dict[int, dict] = {}

    for n in walk(doc):
        if isinstance(n.get("restaurant"), dict) and isinstance(n.get("dishes"), list):
            owner = n["restaurant"].get("info") or {}
            for d in n["dishes"]:
                i = d.get("info") or {}
                if not i.get("name"):
                    continue
                r, cnt = rating(i)
                desc = i.get("description") or ""
                dishes.append({
                    "dish": i.get("name"),
                    "price": rupees(i.get("price") or i.get("defaultPrice")),
                    "rating": r,
                    "n": cnt,
                    "veg": i.get("isVeg") == 1,
                    "restaurant": owner.get("name"),
                    "restaurant_id": owner.get("id"),
                    "shop_rating": owner.get("avgRating"),
                    "shop_n": count(owner.get("totalRatingsString")),
                    "km": km(owner.get("sla")),
                    "cuisines": owner.get("cuisines") or [],
                    "description": desc,
                    "nutrition": nutrition(desc),
                    "image_url": image_url(i.get("imageId")),
                })

        i = n.get("info")
        if isinstance(i, dict) and i.get("id") and i.get("name") and isinstance(i.get("sla"), dict):
            restaurants.setdefault(i["id"], {
                "name": i["name"],
                "id": i["id"],
                "rating": i.get("avgRating"),
                "n": count(i.get("totalRatingsString")),
                "km": km(i.get("sla")),
                "cuisines": i.get("cuisines") or [],
                "image_url": image_url(i.get("cloudinaryImageId")),
            })

    return dishes, restaurants


def orphans(dishes: list[dict], restaurants: dict[int, dict]) -> list[dict]:
    """Restaurants that matched the query but returned no dishes.

    The highest-value output of a search. A specialist several km out is
    routinely ranked out of the dish results while still appearing as a bare
    card -- indistinguishable from a restaurant that genuinely lacks the dish.
    Fetch each one's menu by id before ruling it out.
    """
    served = {d["restaurant_id"] for d in dishes}
    out = [r for r in restaurants.values() if r["id"] not in served]
    return sorted(out, key=lambda r: -(r["rating"] or 0))


def menu_items(doc: Any) -> tuple[dict, list[dict]]:
    """Split a menu payload into the shop and its items.

    Add-ons and variants are captured because they change what is orderable:
    a vegetarian pasta with a grilled-chicken add-on answers "is there a
    chicken version?" with yes. Reading only item names answers it with no.
    """
    shop: dict = {}
    items: dict[int, dict] = {}

    for n in walk(doc):
        i = n.get("info")
        if not isinstance(i, dict):
            continue

        if not shop and i.get("name") and i.get("avgRating") and "sla" in i:
            shop.update({
                "name": i["name"],
                "rating": i.get("avgRating"),
                "n": count(i.get("totalRatingsString")),
                "km": km(i.get("sla")),
                "image_url": image_url(i.get("cloudinaryImageId")),
            })

        if i.get("id") and i.get("name") and (i.get("price") or i.get("defaultPrice")):
            r, cnt = rating(i)
            desc = i.get("description") or ""
            items[i["id"]] = {
                "dish": i["name"],
                "price": rupees(i.get("price") or i.get("defaultPrice")),
                "rating": r,
                "n": cnt,
                "veg": i.get("isVeg") == 1,
                "description": desc,
                "nutrition": nutrition(desc),
                "image_url": image_url(i.get("imageId")),
                "addons": [
                    {"group": g.get("groupName"), "name": c.get("name"), "price": rupees(c.get("price"))}
                    for g in (i.get("addons") or [])
                    for c in (g.get("choices") or [])
                ],
                "variants": [
                    {"group": vg.get("name"), "name": v.get("name"), "price": rupees(v.get("price"))}
                    for vg in ((i.get("variantsV2") or {}).get("variantGroups") or [])
                    for v in (vg.get("variations") or [])
                ],
            }

    return shop, list(items.values())
