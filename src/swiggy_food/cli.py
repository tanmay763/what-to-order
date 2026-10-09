"""Command line interface.

    uv run swiggy-food locate "Koramangala, Bengaluru"
    uv run swiggy-food locate "<your address>" --save home
    uv run swiggy-food search "butter chicken" --place home --max-km 7
    uv run swiggy-food search "butter chicken" --place "Indiranagar, Bengaluru"
    uv run swiggy-food menu 934504 --place home --grep alfredo
    uv run swiggy-food menu 934504 --place home --grep noodles --photos
    uv run swiggy-food near --lat 12.93 --lng 77.62
    uv run swiggy-food recall --grep biryani     # questions asked before, and the answer
    uv run swiggy-food cache --stats

Every command needs a location: --place (a saved name or a locality) or --lat/--lng.

Responses and answers are cached for 90 days so a repeat question comes back
instantly. Cached reads print their age; pass --fresh to bypass the cache.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

from . import cache, client, geo, parse

LOW_N = 35  # below this a rating is a hint, not evidence


def _flag(n: int | None) -> str:
    return " !" if (n or 0) < LOW_N else "  "


def _dump(path: str, payload: dict) -> None:
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nwrote {path}", file=sys.stderr)


def _where(a: argparse.Namespace) -> tuple[float, float]:
    lat, lng, how = geo.resolve(a.place, a.lat, a.lng)
    print(f"location: {lat:.4f},{lng:.4f}  via {how}", file=sys.stderr)
    return lat, lng


def cmd_search(a: argparse.Namespace) -> None:
    a.lat, a.lng = _where(a)
    dishes: dict[tuple, dict] = {}
    restaurants: dict[int, dict] = {}

    for term in a.terms:
        try:
            d, r = parse.search_results(client.search(term, a.lat, a.lng, a.fresh))
        except Exception as e:
            print(f"  ! {term}: {e}", file=sys.stderr)
            continue
        print(f"  {term}: {len(d)} dishes, {len(r)} restaurants", file=sys.stderr)
        for x in d:
            dishes[(x["restaurant_id"], x["dish"])] = x
        restaurants.update(r)
        if not client.last_was_cached:
            time.sleep(a.sleep)

    rows = list(dishes.values())
    if a.cuisine:
        want = a.cuisine.lower()
        rows = [x for x in rows if any(want in c.lower() for c in x["cuisines"])]
    if a.max_km is not None:
        rows = [x for x in rows if x["km"] is not None and x["km"] <= a.max_km]
    rows = [x for x in rows if (x["n"] or 0) >= a.min_n]
    rows.sort(key=lambda x: (-(x["rating"] or 0), -(x["n"] or 0)))

    print(f"\n{'RATING':>7} {'N':>7}   {'RS':>6} {'KM':>5}  DISH - RESTAURANT (shop)")
    for x in rows[: a.limit]:
        print(
            f"{x['rating'] or 0:>7.1f} {x['n'] or 0:>7}{_flag(x['n'])} {x['price'] or 0:>6.0f} "
            f"{x['km'] if x['km'] is not None else 0:>5.1f}  {x['dish']} - {x['restaurant']} "
            f"({x['shop_rating']}/{x['shop_n']})"
        )
        if a.cuisine:
            print(f"{'':>23}{', '.join(x['cuisines'])}")
        if x["nutrition"]:
            n = x["nutrition"]
            print(f"{'':>23}vendor: {n['kcal']}kcal, fat {n['fat_g']}g, protein {n['protein_g']}g")
        if a.photos and x["image_url"]:
            print(f"{'':>23}photo: {x['image_url']}")

    leads = parse.orphans(list(dishes.values()), restaurants)
    if a.max_km is not None:
        leads = [r for r in leads if r["km"] is not None and r["km"] <= a.max_km]
    if leads:
        print(f"\nNO DISH DATA - {len(leads)} restaurants matched but returned no dishes.")
        print("These are leads, not absences. Fetch each menu by id before ruling it out:")
        for r in leads[: a.limit]:
            print(f"   {r['rating']} ({r['n']})  {r['km']}km  {r['name']}  ->  menu {r['id']}")
            if a.photos and r["image_url"]:
                print(f"      photo: {r['image_url']}")

    top = rows[0] if rows else None
    cache.log_query({
        "cmd": "search",
        "terms": a.terms,
        "place": a.place,
        "lat": a.lat, "lng": a.lng,
        "filters": {"cuisine": a.cuisine, "max_km": a.max_km, "min_n": a.min_n},
        "hits": len(rows),
        "leads": len(leads),
        "top": (f"{top['rating']} ({top['n']}) Rs{top['price'] or 0:.0f}  "
                f"{top['dish']} - {top['restaurant']}") if top else "no dishes",
    })

    if a.json:
        _dump(a.json, {"dishes": rows, "leads": leads})


def cmd_menu(a: argparse.Namespace) -> None:
    a.lat, a.lng = _where(a)
    shop, items = parse.menu_items(client.menu(a.restaurant_id, a.lat, a.lng, a.fresh))
    print(
        f"{shop.get('name')} | {shop.get('rating')} ({shop.get('n')}) | "
        f"{shop.get('km')}km | {len(items)} items",
        file=sys.stderr,
    )

    if a.grep:
        rx = re.compile(a.grep, re.I)
        items = [i for i in items if rx.search(i["dish"]) or rx.search(i["description"])]
    items.sort(key=lambda x: (-(x["rating"] or 0), -(x["n"] or 0)))

    for i in items[: a.limit]:
        veg = "veg" if i["veg"] else "non-veg"
        print(
            f"\n{i['rating'] or 0:>5.1f} {i['n'] or 0:>6}{_flag(i['n'])} "
            f"Rs{i['price'] or 0:>5.0f}  {i['dish']}  [{veg}]"
        )
        if i["description"]:
            print(f"        {i['description'][:150]}")
        if i["nutrition"]:
            n = i["nutrition"]
            print(f"        vendor: {n['kcal']}kcal, fat {n['fat_g']}g")
        if a.photos and i["image_url"]:
            print(f"        photo: {i['image_url']}")
        for v in i["variants"]:
            print(f"        variant [{v['group']}]: {v['name']} +Rs{v['price'] or 0:.0f}")
        for ad in i["addons"]:
            print(f"        addon [{ad['group']}]: {ad['name']} +Rs{ad['price'] or 0:.0f}")

    cache.log_query({
        "cmd": "menu",
        "restaurant_id": a.restaurant_id,
        "place": a.place,
        "lat": a.lat, "lng": a.lng,
        "grep": a.grep,
        "hits": len(items),
        "top": f"{shop.get('name')} - {len(items)} items matched",
    })

    if a.json:
        _dump(a.json, {"shop": shop, "items": items})


def cmd_near(a: argparse.Namespace) -> None:
    a.lat, a.lng = _where(a)
    _, restaurants = parse.search_results(client.nearby(a.lat, a.lng, a.fresh))
    rows = sorted(restaurants.values(), key=lambda r: r["km"] if r["km"] is not None else 99)
    print(
        f"{len(rows)} restaurants -- page 1 only. This endpoint paginates at 25 and may "
        f"not reach past ~4km, so absence here means nothing.",
        file=sys.stderr,
    )
    for r in rows:
        d = r["km"] if r["km"] is not None else 0
        print(f"{d:>5.1f}km  {r['rating']} ({r['n']})  {r['name']}  id={r['id']}")
        if a.photos and r["image_url"]:
            print(f"         photo: {r['image_url']}")

    cache.log_query({
        "cmd": "near", "place": a.place, "lat": a.lat, "lng": a.lng,
        "hits": len(rows),
        "top": ", ".join(f"{r['name']}#{r['id']}" for r in rows[:3]),
    })


def cmd_locate(a: argparse.Namespace) -> None:
    hits = geo.geocode(a.query)
    if not hits:
        print(f"no match for {a.query!r} -- add the city and retry", file=sys.stderr)
        raise SystemExit(1)
    for i, h in enumerate(hits):
        d = "" if i == 0 else f"  ({geo.haversine(hits[0]['lat'], hits[0]['lng'], h['lat'], h['lng']):.1f}km from first)"
        print(f"{h['lat']:.4f},{h['lng']:.4f}  [{h['kind']}]  {h['label']}{d}")

    if a.save:
        if len(hits) > 1 and geo.haversine(hits[0]["lat"], hits[0]["lng"], hits[1]["lat"], hits[1]["lng"]) > 2:
            print("\nrefusing to save: candidates disagree by more than 2km. "
                  "Narrow the query, then save.", file=sys.stderr)
            raise SystemExit(1)
        h = hits[0]
        path = geo.save_place(a.save, h["lat"], h["lng"], h["label"])
        print(f"\nsaved {a.save!r} -> {h['lat']:.4f},{h['lng']:.4f} in {path}", file=sys.stderr)


def cmd_places(a: argparse.Namespace) -> None:
    places = geo.load_places()
    if not places:
        print("no saved places. Save one:  swiggy-food locate \"<address>\" --save home",
              file=sys.stderr)
        return
    for name, v in places.items():
        print(f"{name:<12} {v['lat']:.4f},{v['lng']:.4f}  {v.get('label','')}")


def cmd_whereami(a: argparse.Namespace) -> None:
    fix = geo.ip_fix()
    if not fix:
        print("no IP fix available", file=sys.stderr)
        raise SystemExit(1)
    print(f"{fix['lat']:.4f},{fix['lng']:.4f}  {fix['label']}")
    print("\nThis is a city-level guess and was measured 14km from a real home address.\n"
          "Confirm it with the user before ranking anything on it, then save the real\n"
          "address with:  swiggy-food locate \"<address>\" --save home", file=sys.stderr)


def cmd_recall(a: argparse.Namespace) -> None:
    """What was asked before, and what came back -- without refetching anything."""
    rows = cache.past_queries(limit=a.limit, grep=a.grep)
    if not rows:
        print("nothing recalled. The log keeps 90 days of answered questions.",
              file=sys.stderr)
        return
    now = time.time()
    for r in rows:
        age = cache.human_age(now - r["at"])
        what = " ".join(r.get("terms") or []) or str(r.get("restaurant_id") or "")
        where = r.get("place") or f"{r.get('lat')},{r.get('lng')}"
        print(f"{age:>5} ago  {r['cmd']:<6} {what!r} @ {where}")
        print(f"{'':>11}{r.get('hits', 0)} hits -> {r.get('top', '')}")
    print("\nThese are remembered answers, not fresh ones. Re-run the query with "
          "--fresh before quoting a price or claiming a place is open.", file=sys.stderr)


def cmd_cache(a: argparse.Namespace) -> None:
    if a.clear:
        print(f"cleared {cache.clear()} cached responses and the query log", file=sys.stderr)
        return
    if a.purge:
        print(f"dropped {cache.purge()} expired responses", file=sys.stderr)
        return
    st = cache.stats()
    print(f"{st['entries']} responses, {st['bytes'] / 1e6:.1f} MB, "
          f"{st['queries']} logged questions")
    if st["entries"]:
        print(f"newest {cache.human_age(st['newest'])} old, "
              f"oldest {cache.human_age(st['oldest'])} old  "
              f"(kept for {cache.TTL // 86400} days)")
    print(f"at {cache.ROOT}")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--place", help="saved place name (see 'places') or a locality, "
                                       "e.g. 'home' or 'Koramangala, Bengaluru'")
    common.add_argument("--lat", type=float, help="origin latitude (with --lng)")
    common.add_argument("--lng", type=float, help="origin longitude (with --lat)")
    common.add_argument("--limit", type=int, default=30)
    common.add_argument("--fresh", action="store_true",
                        help="bypass the 90-day cache and refetch from Swiggy")
    common.add_argument("--photos", action="store_true",
                        help="print the dish or restaurant photo URL under each row")
    common.add_argument("--json", help="also write full results to this path")

    p = argparse.ArgumentParser(prog="swiggy-food", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", parents=[common], help="sweep terms for dishes and restaurants")
    s.add_argument("terms", nargs="+", help="sweep spellings: rasgulla rosogolla rasagulla")
    s.add_argument("--max-km", type=float, default=None)
    s.add_argument("--min-n", type=int, default=0, help="hide dishes under N reviews")
    s.add_argument("--cuisine", help="keep only restaurants tagged with this cuisine, "
                                     "e.g. 'north indian', 'bengali', 'italian'")
    s.add_argument("--sleep", type=float, default=1.0)
    s.set_defaults(fn=cmd_search)

    m = sub.add_parser("menu", parents=[common], help="full menu for one restaurant id")
    m.add_argument("restaurant_id")
    m.add_argument("--grep", help="filter items by regex over name and description")
    m.set_defaults(fn=cmd_menu)

    n = sub.add_parser("near", parents=[common], help="restaurants near the coordinate (page 1 only)")
    n.set_defaults(fn=cmd_near)

    l = sub.add_parser("locate", help="geocode an address or locality to a coordinate")
    l.add_argument("query", help="'Koramangala, Bengaluru' or a full street address")
    l.add_argument("--save", metavar="NAME", help="save the top hit under this name, e.g. home")
    l.set_defaults(fn=cmd_locate)

    pl = sub.add_parser("places", help="list saved places")
    pl.set_defaults(fn=cmd_places)

    w = sub.add_parser("whereami", help="coarse city-level guess from IP -- must be confirmed")
    w.set_defaults(fn=cmd_whereami)

    r = sub.add_parser("recall", help="past questions and their answers (90 days)")
    r.add_argument("--grep", help="filter by dish, restaurant or place")
    r.add_argument("--limit", type=int, default=20)
    r.set_defaults(fn=cmd_recall)

    c = sub.add_parser("cache", help="cache size, age, and cleanup")
    c.add_argument("--stats", action="store_true", help="size and age (the default)")
    c.add_argument("--purge", action="store_true", help="drop entries past 90 days")
    c.add_argument("--clear", action="store_true", help="delete everything cached")
    c.set_defaults(fn=cmd_cache)
    return p


def main() -> None:
    a = build_parser().parse_args()
    try:
        a.fn(a)
    except geo.LocationUnknown as e:
        print(f"\n{e}", file=sys.stderr)
        raise SystemExit(2)
    except client.EmptyResponse as e:
        print(f"\n{e}", file=sys.stderr)
        raise SystemExit(3)
