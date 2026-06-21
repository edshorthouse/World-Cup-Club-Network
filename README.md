# World Cup 2026 club career-path visualisation

`drill_down.html` is an interactive drill‑down (Confederation → Country → League →
Club → Players → Player career) of every 2026 FIFA World Cup squad player's club
career, scraped from Wikipedia. This note explains how to **refresh the data** and
what each file does.

---

## Quick refresh — one command

```bash
python refresh.py                # full refresh: scrape Wikipedia + rebuild the HTML
```

`refresh.py` runs the whole pipeline (`01 → 08`) in order, stops at the first
real failure, and prints per‑step timings. Handy flags:

```bash
python refresh.py --build-only   # only step 08 — rebuild the HTML from existing CSVs
                                 # (use this to publish code/template changes, no re-scrape)
python refresh.py --from 4       # resume from step 04 (e.g. after a network drop)
```

It uses the same interpreter you launch it with (so it respects your venv), and
the optional player‑bio step is treated as a warning, not a failure.

To publish a refresh:

```bash
git add -A && git commit -m "Refresh data" && git push
```

GitHub Pages then redeploys `index.html` automatically — live at
https://edshorthouse.github.io/World-Cup-Club-Network/ . To preview locally
first, open **`drill_down.html`** in any browser (no server needed).

### …or run the numbered scripts by hand

`refresh.py` is just a wrapper. The underlying steps, in their fixed run order
(each step's output feeds the next, so don't skip or reorder):

```bash
python 01_extract_players.py       # squads        -> players.csv
python 02_extract_clubs.py         # career clubs  -> clubs.csv, club_spells.csv
python 03_club_frequency.py        # club counts   -> club_frequency.csv
python 04_lookup_clubs.py          # club name/league -> club_details.csv
python 05_enrich_club_details.py   # league+country  -> club_details.csv (in place)
python 06_league_levels.py         # pyramid tiers   -> league_levels.csv
python 07_detect_dissolved.py      # defunct clubs   -> dissolved_clubs.json
python extract_player_bio.py       # position + DOB  -> player_bio.csv  (optional enrichment)
python 08_build_drill_down.py      # the viz         -> drill_down.html + index.html
```

`08` writes **both** `drill_down.html` (open locally) and `index.html` (served at
the GitHub Pages root).

> **Timing / network:** steps 01, 02, 04, 05, 06 scrape Wikipedia (polite 1s
> delay between requests). Pages are cached under `./cache/`, so re‑runs are fast.
> Step 02 has a **1‑day** cache, so a same‑day re‑run is instant but a refresh a
> few days later re‑fetches ~1,250 player pages (~20 min). Steps 04/05/06 cache
> for 45 days. Steps 03, 07, 08 need no network (they only read local files/cache).

---

## What each script does

| # | Script | Reads | Writes |
|---|--------|-------|--------|
| 01 | `01_extract_players.py` | Wikipedia squads page | `players.csv` — one row per player (Nation, Player, WikiURL) |
| 02 | `02_extract_clubs.py` | `players.csv` + each player's Wikipedia page | `clubs.csv` (unique clubs per player, career order) and `club_spells.csv` (one row per spell: years, start/end, loan flag) |
| 03 | `03_club_frequency.py` | `clubs.csv`, `club_details.csv` | `club_frequency.csv` — every unique club slug with a player count (used as the slug list for step 04) |
| 04 | `04_lookup_clubs.py` | `club_frequency.csv` + each club's Wikipedia page | `club_details.csv` — Slug, Name, League, LeagueSlug, Country |
| 05 | `05_enrich_club_details.py` | `club_details.csv` + Wikipedia pages | `club_details.csv` (overwritten) — fills League/Country via infobox, categories, parent‑club fallback, then league→country |
| 06 | `06_league_levels.py` | `club_details.csv` + each league's Wikipedia page | `league_levels.csv` — pyramid tier (level) per (Country, League) |
| 07 | `07_detect_dissolved.py` | `club_details.csv` + cached club pages | `dissolved_clubs.json` — `{slug: {league, country, year}}` for defunct clubs |
| — | `extract_player_bio.py` | `players.csv` + cached player pages | `player_bio.csv` — each player's Position + Date of birth (cache-only; run after 02, before 08). Optional: the build degrades gracefully without it |
| 08 | `08_build_drill_down.py` | `players.csv`, `clubs.csv`, `club_spells.csv`, `club_details.csv`, `league_levels.csv`, `dissolved_clubs.json`, `player_bio.csv` | **`drill_down.html`** — the finished visualisation |

### The data files

- `players.csv` – squads (step 01)
- `clubs.csv` – unique career clubs per player, in order (step 02)
- `club_spells.csv` – per‑spell detail: years, start/end, loan flag — drives the
  career timeline and the current/first/loan filters (step 02)
- `club_frequency.csv` – club → player count (step 03)
- `club_details.csv` – the club lookup: name, league, country (steps 04→05)
- `league_levels.csv` – league → pyramid tier (step 06)
- `dissolved_clubs.json` – defunct clubs + dissolution year (step 07)
- `player_bio.csv` – each player's position + date of birth (age is computed live
  in the browser); drives the profile card (extract_player_bio.py)
- `drill_down.html` – the output you open (step 08)

---

## Supporting files (not part of the linear run)

**Pipeline runner:**
- `refresh.py` – runs steps `01 → 08` in order (the easy path above). Wraps the
  numbered scripts; supports `--build-only` and `--from N`. Not imported by
  anything — purely a convenience entry point.

**Shared library — do not rename or number:**
- `league_dedup.py` – canonical league‑name de‑duplication, **imported** by
  `06_league_levels.py` and `08_build_drill_down.py` so the levels table and the
  viz agree on one name per real league. (It is `import`ed, so its name must stay
  a valid module name — that's why it has no number.)

**Verification (optional, run after step 08):**
- `verify_players.py` – cross‑checks the player counts in `drill_down.html`
  against `clubs.csv` and recomputes every level total by set‑union.
- `verify_levels.py`, `verify_tiers.py` – sanity‑check the league pyramid tiers.
- `verify_countries.py` – flags any club whose assigned country (from its league)
  disagrees with its own Wikipedia categories ("Football clubs in X"). Catches
  wrong `_CLUB_LEAGUE_OVERRIDES` entries in `05_enrich_club_details.py`
  (the kind of mistake that put a Jordanian club under Yemen). Run after `05`.

**Auxiliary / one‑off (not needed to refresh):**
- `check_squad_updates.py` – re‑scrapes the squads page and reports additions /
  removals vs `players.csv` (run any time to see if squads changed).
- `visualise_network.py` – an alternative network‑graph view (`club_network.html`).
- `load_neo4j.py` – loads the data into a Neo4j graph database.
- `check_everton.py`, `retry_errors.py` – debug helpers (`everton_hits.csv`).

**Caches (auto‑generated, safe to delete to force a fresh scrape):**
- `cache/` – raw Wikipedia HTML keyed by `sha1(url)`.
- `league_levels_cache.json`, `league_categories_cache.json`, `uk_nations.json` –
  resolved‑article / category / UK‑home‑nation lookups.

**Vendored map (optional but recommended):**
- `countries-50m.json` – the world atlas (Natural Earth 50m, ~750 KB). `drill_down.html`
  loads it **locally first**, falling back to the CDN if absent — so keep it next to the
  HTML for offline / locked‑down use. Re‑download with
  `curl -L -o countries-50m.json https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json`.
  At load the build re‑tags disputed areas where there is broad international/UN
  consensus on sovereignty — **Crimea → Ukraine** and **Northern Cyprus → Cyprus**
  (so they colour/click as that country). **Western Sahara is deliberately left as its
  own neutral territory** (a UN non‑self‑governing territory with no agreed sovereign),
  rather than merged into Morocco.

---

## Data flow

```
01_extract_players        ->  players.csv
02_extract_clubs          ->  clubs.csv, club_spells.csv   (reads players.csv)
03_club_frequency         ->  club_frequency.csv           (reads clubs.csv, club_details.csv)
04_lookup_clubs           ->  club_details.csv             (reads club_frequency.csv)
05_enrich_club_details    ->  club_details.csv (enriched)
06_league_levels          ->  league_levels.csv            (reads club_details.csv)
07_detect_dissolved       ->  dissolved_clubs.json         (reads club_details.csv + cache)
08_build_drill_down       ->  drill_down.html
       reads: players.csv + clubs.csv + club_spells.csv + club_details.csv
              + league_levels.csv + dissolved_clubs.json
```
