# what-to-order

Live queries against Swiggy's public web endpoints, backing the `food-research` skill.
The repository is a Claude Code plugin and its own marketplace.

```text
/plugin marketplace add tanmay763/what-to-order
/plugin install what-to-order@what-to-order
```

The plugin puts `swiggy-food` on the Bash `PATH` and needs [`uv`](https://docs.astral.sh/uv/).
To try local changes without installing, run `claude --plugin-dir .`.

Responses and answered questions are cached for 90 days, so a repeat
question returns instantly and `recall` can show what was asked before. Restaurant
listings, prices and menus change constantly, so the cache is for recall, not truth:
every cached read prints its age, anything past 3 days is marked STALE, and `--fresh`
refetches. The other value kept here is the parsing, which encodes the shapes that make
a naive query wrong.

```bash
uv run swiggy-food locate "Koramangala, Bengaluru"
uv run swiggy-food locate "<your address>" --save home
uv run swiggy-food search "butter chicken" "murgh makhani" --place home --max-km 5
uv run swiggy-food search "butter chicken" --place "Indiranagar, Bengaluru" --cuisine "north indian"
uv run swiggy-food menu 934504 --place home --grep alfredo
uv run swiggy-food menu 934504 --place home --grep noodles --photos
uv run swiggy-food near --place home
uv run swiggy-food recall --grep biryani            # past questions and their answers
uv run swiggy-food search "biryani" --place home --fresh
uv run swiggy-food cache --stats                    # size and age;  --purge  --clear
```

Saved places (`places.json`, which holds a home address) and the cache (`cache/`) live in
`~/.local/share/swiggy-food/`, outside the code, so plugin updates keep them.
`XDG_DATA_HOME` moves both; `SWIGGY_FOOD_CACHE` moves only the cache.

Stdlib only, no dependencies.

## Layout

    src/swiggy_food/cache.py    90-day response cache and the query log
    src/swiggy_food/client.py   endpoints and HTTP
    src/swiggy_food/geo.py      address/locality -> coordinate, and saved places
    src/swiggy_food/parse.py    payload shapes and their traps
    src/swiggy_food/cli.py      command line
    skills/food-research/SKILL.md   how to use the data well
    bin/swiggy-food                 wrapper the plugin puts on PATH
    .claude-plugin/                 plugin and marketplace manifests

## Notes

Geocoding uses OpenStreetMap Nominatim; Swiggy's own place-autocomplete endpoints are
404. IP geolocation is available but city-level — it measured 14 km off a real home
address, so it is never used without confirmation.

Restaurant data comes from `dapi`; menus only work under `mapi`. `dapi/menu/pl` answers
HTTP 202 with an empty body, which looks like a network failure and is not — the same
query succeeds under `mapi`.

Photos ride along in payloads you already fetched: dishes carry `imageId`, restaurants
`cloudinaryImageId`, and all three id shapes resolve against one CDN prefix (see
`parse.image_url`). `--photos` prints them. Treat a dish photo as marketing — one
restaurant's is watermarked `AI GENERATED`.

This uses Swiggy's unofficial web API, which is against their terms and can break without
notice. Fine for personal use; do not build anything durable on it. The sanctioned route
is the Swiggy Builders Club MCP at `mcp.swiggy.com/food`, which needs no approval for
local development.

## License

MIT. See `LICENSE`.
