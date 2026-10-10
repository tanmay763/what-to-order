---
name: food-research
description: >
  Find and rank the best restaurants or menu items for a delivery address — a specific dish,
  a cuisine, or a category — using live Swiggy data. Ranks by rating with review count treated
  as a confidence interval, and guards against the failure modes that silently hide the best
  result. Use when asked to find the best <dish> nearby, compare places to order from, pick
  somewhere to eat, or check what a dish costs or contains. Also covers filtering a whole
  delivery area against a hard dietary constraint (fat/protein/calorie limits, medical
  diets) and building an exhaustive restaurant registry when ranked search is too narrow.
---

# Food research

Every response and every answered question is kept for 90 days, so a repeat question
comes back in milliseconds instead of a fresh sweep. That is a recall aid, not a source
of truth: restaurant data goes stale within days, so the cache tells you what you found
last time, and `--fresh` tells you what is true now. What is durable is the method below
and the parsing in `swiggy_food`, which encodes the traps that make a naive query return
a confidently wrong answer.

## The tool

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" locate "Koramangala, Bengaluru"          # address/locality -> coordinate
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" locate "<full address>" --save home      # remember it under a name
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" places                                   # what is already saved

"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" search "butter chicken" "murgh makhani" --place home --max-km 5
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" search "butter chicken" --place "Koramangala, Bengaluru" --cuisine "north indian"
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" menu 934504 --place home --grep alfredo
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" menu 934504 --place home --grep noodles --photos   # dish photo URLs
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" near --place home

"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" recall --grep biryani                    # what was asked before, and the answer
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" search "biryani" --place home --fresh    # ignore the cache, refetch
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" cache                                    # size, age, location
```

Run the tool as `"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food"`, quoted as shown. The rest of
this skill writes `swiggy-food <command>` for short; always run it with the full path. It
needs `uv`, which fetches Python 3.13 on first run. If the script fails to start, run
`uv run --project "${CLAUDE_PLUGIN_ROOT}" swiggy-food` in its place.

Every data command takes `--place` (a saved name, or a locality to geocode) or explicit
`--lat/--lng`. Other flags: `--cuisine` filters by restaurant cuisine tag, `--max-km`,
`--min-n`, `--limit`, `--photos` prints dish photo URLs (section 9), and `--json out.json`
for the full structured result. Prices print in rupees; the paise conversion is handled.

## The cache: 90 days of queries and results

Responses are stored per endpoint **and per coordinate**, rounded to ~10 m — a query from
a different address is a different entry, because reusing one across coordinates would
reintroduce the wrong-origin failure that section 1 exists to prevent. Alongside them,
every answered question is logged with its headline result, which is what `recall` reads.

**Open with `recall`.** Before sweeping, check whether this question — or a near one — was
already answered. It costs nothing, and it tells you which spellings were already tried
and which restaurants were already ruled out, so the sweep starts where the last one
ended rather than repeating it.

**Then decide how fresh the answer has to be.** The cache is happy to serve a 60-day-old
menu, and every cached read prints its age (`cache: search 'biryani' from 12d ago`);
past 3 days it also prints `STALE`. Age is not a detail to skim past:

| what is being asked | what to do |
|---|---|
| "what did we find last time", exploring, narrowing a shortlist | cached is fine at any age |
| a **price**, a rating, "is it open", "do they still have X" | `--fresh`, always |
| the final ranked answer you are about to hand over | `--fresh` on the top few, cached for the long tail |

Prices move with offers, ratings drift, and kitchens close permanently — none of which the
cache can notice. **Never quote a cached price or claim a place is open without refetching.**
A cached answer that is stated as cached is useful; one presented as live is the same
confidently-wrong failure this skill exists to avoid.

`cache --purge` drops entries past 90 days; `cache --clear` empties it. Clearing is safe —
it costs a refetch, nothing else. Saved places live in `places.json` and are not touched
by either. Both sit in `~/.local/share/swiggy-food/`, so they survive plugin updates.

## 1. Resolve the location before anything else

A ranked list built on the wrong coordinate looks authoritative and is wrong in every row,
so this step is never skipped and never guessed.

**"near me" / "nearby" / no location stated.** Run `places`. If a saved place exists, use
it and say which one. If not, **ask the user for their address** — a street address or a
building name, not just the city. Then save it with `locate "<address>" --save home` so
the question is asked once, not every session. Saved coordinates are the one thing worth
persisting here: an address stays true, unlike menus and prices.

**A named locality** ("in Koramangala", "around Indiranagar"). Pass it straight through as
`--place "Koramangala, Bengaluru"`. Always include the city — bare `Indiranagar` matches
villages 900 km away in Maharashtra, and `locate` will refuse to guess between candidates
more than 2 km apart. A locality resolves to its **centroid**, so treat distances as
"from the middle of the area", and say so if the answer turns on a 1 km difference.

**Never use the IP address silently.** `whereami` exists for the case where you have
nothing else, but it is a city-level guess that measured **14.1 km** from a real home
address in this city — far enough that every distance, every ranking and every "does it
deliver here" was wrong while looking entirely reasonable. Offer it as a question to
confirm, never as the answer.

**Verifying a coordinate: use restaurant ids, not distances.** Swiggy resolves the
*nearest outlet of a brand* to whatever coordinate you send, so a wrong origin still
returns plausible distances for familiar names — a coordinate several km off returned
2.2 km and 2.3 km for two landmarks whose true distances were 1.9 km and 2.6 km. Nothing
about that output looks wrong. Run `near`, note the ids of two close well-known
restaurants, and check the same ids come back later. A different id for the same brand
name means the coordinate moved.

State the coordinate you used in your answer so it can be corrected in one line.

## 2. Sweep spellings and names, always

Different spellings return **different restaurants**, not the same ones reordered — a shop
that spells everything "Rosogolla" will not surface for `rasgulla`. Run the variants in one
command: `rasgulla rosogolla rasagulla`, `jamun jamoon`, `biryani biriyani`, `paneer panir`.

The same applies to a dish with two names. `butter chicken murgh makhani` surfaces menu
entries the first term alone ranks differently — kitchens that write "Murgh Tikke Ki
Makhani" are answering the butter chicken question under another name.

For a **cuisine** question ("north indian places doing butter chicken"), search the dish
and filter with `--cuisine "north indian"` rather than searching the cuisine name. Cuisine
tags come from the restaurant, so this narrows real dish hits instead of returning
restaurants you then have to check one by one.

## 3. Chase every restaurant that returned no dishes

The single biggest source of missed results, and the reason `search` prints a
`NO DISH DATA` block. Two independent causes put a good restaurant in there:

- Some queries return a **restaurant-shaped** response carrying no dish data whatsoever.
- Dish results are **proximity-biased** — a strong specialist 6 km out is ranked below
  mediocre neighbours and may never appear with its dishes.

Either way the shop appears as a bare card, indistinguishable from one that genuinely
lacks the dish. **A restaurant with a good shop-level rating and no dish data is a lead,
not an absence.** Run `menu <id>` on it before ruling it out. The best rosogolla shop in
range was missed across ten queries exactly this way — it did appear, as a card, and got
dismissed for having no dishes attached.

Note also that `near` returns **one page of 25**, which in a dense area reaches barely
4 km. Absence from `near` means nothing at all.

**Never infer "does not deliver here" from absence in a dish result.** This is the same
trap wearing a different hat, and it is the one that produces the most confident wrong
sentence you can write: *"those places don't deliver to you."* Dish ranking drops distant
restaurants to bare cards or omits them outright, so a shop 7–10 km out that delivers
perfectly well can be invisible across a dozen dish queries. Six restaurants were
declared undeliverable this way in one session; all six delivered.

To test deliverability, ask the endpoint about the restaurant directly:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" search "Once Upon A Flame" --place home --max-km 25   # by name
"${CLAUDE_PLUGIN_ROOT}/scripts/swiggy-food" menu 9927 --place home                               # or straight to the menu
```

If it comes back with a distance from the user's coordinate, it serves that address.
If the user says a restaurant delivers to them, **believe them and re-check by name** —
they are reading the app you are approximating.

## 4. Read the add-ons before answering "is there a version with X"

`menu` prints add-ons and variants because they change what is orderable. A vegetarian
pasta with a grilled-chicken add-on answers "is there a chicken version?" with **yes, at
+Rs 95** — reading only item names answers it with a confident no. Check the add-on groups
before reporting that something does not exist.

## 5. Rank by rating, weight by review count

Review count is a confidence interval, not a tiebreaker:

| n | interpretation |
|---|---|
| < 35 | a hint. Flagged `!` in output. Never lead with it. |
| 70–90 | roughly ±0.12 |
| ~500 | roughly ±0.05 — tight enough to trust a 0.1 gap |

So 4.9 on 12 votes **loses** to 4.6 on 500. When two dish ratings tie within their error
bars, break the tie on **shop-level rating**, which measures how often an order arrives in
bad shape — the thing dish ratings never capture.

Watch for one cloud kitchen selling the same dish under several brands; identical
descriptions at an identical distance are the tell. The same food scoring 4.8, 4.7 and 3.5
across three brand names is a free demonstration of how noisy small samples are.

Ratings also drift between calls (4.2/699 → 4.1/701). Do not read meaning into small deltas.

## 6. Do not claim what the data does not contain

- **Never promise free delivery.** The fee fields come back empty; it depends on membership
  and per-order offers and resolves only at checkout. If asked to filter on it, say it
  cannot be done rather than quietly dropping the filter.
- **Nutrition is vendor-published only when it appears in the description string**, which
  the tool extracts and labels `vendor:`. Anything else is your estimate — say so. Vendor
  figures are sometimes internally inconsistent (one item implying triple the fat per 100 g
  of a similar item from the same kitchen); flag that rather than passing it through.
- **Opening hours matter.** A closed restaurant is still returned by search.

## 7. Exhaustive sweeps: build a registry, then read every menu

For "find me everything that fits" — a standing dietary constraint, a full survey of an
area — ranked dish search is the wrong instrument. It returns 50 restaurants per term and
ranks by relevance, so it will never enumerate a city. Build a registry instead:

1. **Harvest ids from many terms.** Both `dishes[].restaurant_id` and `leads[].id` in
   `--json` output carry ids. Run 40+ batches of 3-4 diverse terms — dish names, cuisines,
   *and* common restaurant-name tokens (`kitchen`, `hotel`, `cafe`, `express`, `corner`,
   `darbar`, `tiffin`) — and union the ids. Name tokens matter: they reach shops no dish
   term will surface. 45 batches from one Bangalore address yielded **2,721 unique
   restaurants**, against ~1,600 the Swiggy app offered to "explore".
2. **Fetch every menu** with `menu <id> --place <origin> --json`, at **no more than 3-4
   workers with a short delay between calls** (see the rate-limit warning below), skipping
   ids already on disk so the sweep is resumable.
3. **Parse the menus offline.** Never page thousands of menus through your own context —
   write the JSON to disk, then filter with a script and read only what survives.

Pass `--sleep 0` on `search` during a bulk sweep; the default pause makes a 45-batch run
take an hour instead of two minutes.

Two shell traps, both silent: `read -r -a` is bash-only and fails under zsh (`read: bad
option: -a`), and `--json` still writes a well-formed but empty file when the command
errors. **Check that output files are non-trivial in size before trusting a sweep** — two
waves "succeeded" and produced 33-byte files.

### Swiggy will rate-limit you, and the block outlasts the session

Eight parallel `menu` workers got this address **`HTTP 403: Forbidden` on every endpoint**
partway through a 2,700-menu fetch — not on the ids being requested, but globally: a
`--fresh` refetch of an already-cached restaurant failed too, and the block was still in
place many minutes later. A sweep that dies this way leaves you with a partial corpus and
no way to finish it on demand.

So treat request budget as the scarce resource, not wall-clock time:

- **Assume you cannot pace your way out of it.** It behaves like a rolling *quota*, not a
  rate limit. Measured on one address: 8 workers ran ~1,455 menus before the first block;
  after that, a burst at ~130 req/min got 82 more, and slowing right down to ~11 req/min
  got 132 — a 12x slowdown bought only 60% more requests before tripping again. Gentler
  pacing helps at the margin and is still worth doing (1-2 workers), but it does not
  prevent the block, and a plan that depends on not being blocked will fail.
- **Design the runner for interruption instead.** Resumable (skip ids already on disk),
  self-backing-off (~10 min, then re-probe), and relevance-ordered. Net throughput across
  the block/back-off cycle settles near **6 menus/min**, so budget roughly an hour per 350
  restaurants and let it grind in the background rather than blocking the conversation on
  it.
- **Probe with `--fresh`.** A block check that reads the cache reports "recovered" while
  the API is still refusing every request — a cached hit is not evidence about live state.
- **Fetch in waves and check for 403 between them**, rather than queueing thousands of
  calls that will all fail once the block trips.
- **Order the queue by likely relevance** — the kitchens matching the ask first, the long
  tail afterwards — so that if you are cut off, you were cut off after the part that
  mattered.
- The disk cache is what protects you. Never re-fetch what is already on disk, and never
  pass `--fresh` during a bulk sweep — save it for the handful of results you are about
  to quote.

When it does trip, **say so and quantify the gap** ("1,266 of 2,721 menus unread") rather
than presenting the partial sweep as complete. Waiting it out is the only fix; there is no
back-off header to read.

## 8. Hard nutritional constraints are a different question

"Under 10 g of fat" is not "healthy" — it is a filter, and usually a medical one. Ranking
by rating and hoping the top result is lean will fail.

**Only vendor-published numbers count.** Filter to items that actually carry macros in the
description or `nutrition` field. Across 2,721 menus and ~8,400 chicken items, only ~770
published a fat figure at all — under 10%. Your own estimate of a dish's fat is not
evidence, and a constraint like this is exactly where saying "roughly 8-11 g, my estimate"
is the honest answer rather than a number in a table.

**Health branding anti-correlates with low fat.** "Keto" is high-fat *by definition*.
Salads run 15-29 g once dressing, seeds, olives and nuts are counted. The lowest-fat
chicken in a 2,721-restaurant sweep came from kitchens whose selling point was *weight* —
boiled, steamed, air-fried, plain breast — not from anything labelled healthy.

**Cooking method is the structural signal, and it beats the label.** Steamed and boiled
carry no cooking oil at all; air-fried and tandoori/grilled are next; sautéed hides oil in
"diced and sautéed veg"; fried is out. When a vendor publishes no fat, method is the
only honest thing to reason from — and say that you are reasoning from it.

**Sanity-check every vendor figure before quoting it.** Published macros are frequently
wrong in ways that are easy to catch mechanically:

- *Calorie math.* `4·protein + 4·carbs + 9·fat` should land near the stated kcal. One
  kitchen claimed 55 g protein, 3.2 g carbs, 7 g fat and 400 kcal — the macros imply 296.
- *Per-100g pasted onto a bigger serving.* "220 g serving … Protein 31 g, 165 kcal,
  Fat 3.6 g" is the USDA per-100g line for chicken breast. The real portion is ~68 g
  protein and ~8 g fat. A stated kcal under 200 on a 180 g+ serving is the tell.
- *Numbers that contradict the dish.* Chicken pakoda at 8.7 g fat, "crispy fried tenders"
  at 7.5 g. Deep-fried food is not low-fat; the figure is wrong, not the fryer.

Flag these rather than passing them through, and prefer a dish whose claimed number is
consistent with how it is cooked.

**Collapse cloud-kitchen clones before ranking.** Identical dish name, identical price and
identical macros across several brand names is one kitchen. In this sweep a single
Schezwan chicken bowl (Rs 331, "3 g fat") appeared under five brands at two distances.
Treat it as one option, keep the best-rated storefront, and note that its "3 g fat" for an
oil-based Schezwan sauce fails the sanity check anyway.

## 9. Photos answer what no field encodes — and sometimes lie about it

`--photos` prints a dish or restaurant photo URL under each row, on `search`, `menu`
and `near`. Every dish, item and restaurant dict already carries `image_url`, so it is
in `--json` output whether or not the flag was passed. No extra request is spent
getting the URL; it rides along in the payload you already fetched.

**Pull one only when the ask turns on something visible that no field records.** Noodle
gauge — thin vs thick — is the case this exists for: "authentic Hakka noodles, thin
noodles" is unanswerable from names, descriptions and ratings, and obvious in one
glance at the picture. Same for real portion size, how much gravy a dish comes in, and
whether a "salad" means leaves or a bowl of dressing. It is not a default; most
questions are answered by rating, count and price alone.

**A dish photo is vendor marketing, not documentation of your order.** One kitchen in a
Bangalore sweep — Golden China, 4.6 on 3,400 shop reviews — serves a "Chicken Hakka
Noodles" photo that is *watermarked `AI GENERATED`* and shows thick, heavy noodles. It
is evidence about what the restaurant advertises and nothing more. Studio shots from
the same chain's photographer are only marginally better. So report which of the two
you are describing: "the photo shows fine strands" is honest, "their noodles are thin"
is not.

**Coverage is partial and its absence is meaningless.** Roughly 77% of menu items and
~100% of restaurant cards carry an image. A dish with no photo is a dish whose vendor
never uploaded one — never a signal about the dish.

## Output

Lead with **one concrete recommendation and why it wins**, then the ranked table, then
caveats. Do not open with the table — the ask is an answer, not a dataset.

Every rating carries its n. Anything under 35 is flagged as thin evidence. Name the
restaurants you could not check rather than leaving them out silently, and state the
coordinate you used.

When the ask was a hard constraint (a fat ceiling, a calorie limit), **separate what the
vendor published from what you inferred**. Give the vendor figure with its source, mark
your own reasoning as an estimate in the same sentence, and say plainly when nothing in
range publishes the number at all. Never let an estimate sit in a table column next to
vendor figures without a label — the table is what gets acted on.

**Say how old the data is** whenever any of it came from cache — "prices as of 11 days
ago" is a fine answer; the same sentence without the date is not. If you refetched only
the top few and left the tail cached, say that too.
