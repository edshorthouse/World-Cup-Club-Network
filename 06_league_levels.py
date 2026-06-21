#!/usr/bin/env python3
"""
league_levels.py
================
For every league in ``club_details.csv``, look up which tier it occupies in
its national football pyramid by reading the "Level on pyramid" field
(the ``levels=`` parameter of the ``{{Infobox football league}}`` template)
from the league's English-Wikipedia article.

Input : club_details.csv          (uses columns: League, LeagueSlug, Country)
Output: league_levels.csv         (League, Country, LeagueSlug,
                                    WikipediaTitle, Level, RawLevel, Status)
Cache : league_levels_cache.json  (results are cached so re-runs are instant;
                                    delete this file to force a fresh fetch)

Standard library only. Polite to Wikipedia:
  * one descriptive User-Agent,
  * up to 40 article titles per API request (≈10 requests for ~380 leagues),
  * exponential backoff that honours the Retry-After header on HTTP 429.

Status values
-------------
  ok        level found
  no-level  article exists but has no levels/pyramid field (often a cup, a
            defunct competition, or a non-standard infobox)
  missing   no Wikipedia article for that title
"""
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, OrderedDict

from league_dedup import build_canonical_map, canonical_league, load_detail_rows

API     = "https://en.wikipedia.org/w/api.php"
UA      = "LeaguePyramidLevelBot/1.0 (World Cup 2026 squad visualisation; educational use)"
IN_CSV  = "club_details.csv"
OUT_CSV = "league_levels.csv"
CACHE   = "league_levels_cache.json"
BATCH   = 40                       # article titles per API request (API max is 50)

# ── Manual overrides ─────────────────────────────────────────────────────────
# Levels determined by hand for leagues whose Wikipedia article lacks a parsable
# "levels" field (or whose slug is a dead link). Keyed by (League, Country).
# `level` is the tier in the national pyramid; None = not a senior pyramid tier.
# Sources are the linked Wikipedia articles / national league-system pages.
MANUAL_LEVELS = {
    # Yemen — slug "Yemeni_Premier_League" is dead; real article "Yemeni League" has levels=1
    ("Yemeni Premier League", "Yemen"):                      (1,    "top division (Wikipedia: Yemeni League, levels=1)"),
    # Cape Verde — island Premier Divisions are the top league tier; winners contest the
    # national Cape Verdean Football Championship (a play-off among island champions)
    ("São Vicente Island League", "Cape Verde"):             (1,    "island top division (feeds national championship)"),
    ("Santiago Island League (South)", "Cape Verde"):        (1,    "island top division (feeds national championship)"),
    # France — Régional 1=L6, Régional 2=L7, Régional 3=L8 (French football league system)
    ("Régional 2", "France"):                                (7,    "French football league system: Level 7"),
    ("Régional 3", "France"):                                (8,    "French football league system: Level 8"),
    # Portugal — district leagues sit at Level 5; a district 2nd division is Level 6
    ("AF Madeira 1ª Divisão", "Portugal"):                   (5,    "Madeira FA first division = district Level 5"),
    ("Beja FA", "Portugal"):                                 (5,    "Beja FA first division = district Level 5"),
    ("Portuguese District Championships", "Portugal"):       (5,    "top district division = Level 5"),
    ("District Championship", "Portugal"):                   (5,    "top district division = Level 5"),
    ("Lisbon FA 2nd Division", "Portugal"):                  (6,    "Lisbon FA second division = district Level 6"),
    # Croatia — Četvrta NL (regional) sits at Level 5 after the 2022 restructuring
    ("4. NL Središte Zagreb podskupina A", "Croatia"):       (5,    "Četvrta NL Zagreb, regional ~Level 5 (post-2022)"),
    # Bosnia — explicitly "a fourth level league"
    ("League of Hercegovina-Neretva Canton", "Bosnia and Herzegovina"): (4, "cantonal league = Level 4 (per article)"),
    # Paraguay — slug links to "Paraguayan Tercera División" = third division (name/slug mismatch)
    ("Primera B Nacional", "Paraguay"):                      (3,    "slug -> Paraguayan Tercera Division = Level 3 (name mismatch)"),
    # USA — amateur/pre-professional 4th tier (below D-III); not formally numbered by US Soccer
    ("USL League Two", "United States"):                     (4,    "amateur/pre-pro, ~Level 4 (below USL League One)"),
    ("Premier Development League", "United States"):         (4,    "former name of USL League Two, ~Level 4"),
    ("NPSL", "United States"):                               (4,    "amateur, ~Level 4 (USASA)"),
    ("United Premier Soccer League", "United States"):       (5,    "amateur/semi-pro, outside sanctioned pyramid (~Level 5)"),
    ("Eastern Premier Soccer League", "United States"):      (5,    "regional amateur, outside sanctioned pyramid (~Level 5)"),
    # USA youth — not part of the senior pyramid
    ("MLS Next", "United States"):                           (None, "youth development league (not a senior pyramid tier)"),
    # Canada — unsanctioned semi-pro (Ontario); roughly provincial/Level 3 equivalent
    ("Canadian Soccer League", "Canada"):                    (3,    "unsanctioned semi-pro, ~Level 3 (outside official pyramid)"),
}

# ── Level corrections ────────────────────────────────────────────────────────
# Overrides where the Wikipedia *infobox* `levels` field is stale or wrong (e.g.
# it wasn't updated after a league-system restructuring). Each was confirmed
# against the article's own lead sentence. Keyed by (canonical League, Country);
# applied after de-duplication. `None` = not a senior pyramid tier.
LEVEL_CORRECTIONS = {
    # Portugal — Liga 3 was inserted as tier 3 in 2021, pushing this down a level
    # (lead: "is the fourth level of the Portuguese football league system").
    ("Campeonato de Portugal", "Portugal"):            (4,    "lead: 'fourth level' (Liga 3 added as tier 3 in 2021)"),
    # Australia — the NPL state leagues are the national second tier (NPL Victoria
    # lead: "the second tier within the overall Australian pyramid"); the infobox
    # mislabels them 3. Everything below shifts up one, and the youth league drops
    # out of the senior pyramid.
    ("NPL Queensland", "Australia"):                    (2,    "NPL = second tier of the Australian pyramid"),
    ("NPL South Australia", "Australia"):              (2,    "NPL = second tier of the Australian pyramid"),
    ("NPL Victoria", "Australia"):                      (2,    "lead: 'second tier within the overall Australian pyramid'"),
    ("NPL Western Australia", "Australia"):            (2,    "NPL = second tier of the Australian pyramid"),
    ("National Premier Leagues NSW", "Australia"):     (2,    "NPL = second tier of the Australian pyramid"),
    ("A-League Youth", "Australia"):                   (None, "A-League youth/reserve competition, not a senior tier"),
    ("Football Queensland Premier League", "Australia"): (3,  "state league directly below NPL (national tier 3)"),
    ("NSW League One", "Australia"):                    (3,    "state league directly below NPL NSW"),
    ("Victoria Premier League 1", "Australia"):         (3,    "state league directly below NPL Victoria"),
    ("FQLD 3 – South Coast", "Australia"):             (4,    "Queensland regional level below FQPL"),
    ("State League Division 4-South", "Australia"):    (5,    "low Australian state-league level"),
    # Spain — "3ª" is the current Tercera Federación, the 5th tier (the linked
    # historic "Tercera División" article still reads "fourth tier").
    ("Tercera Federación – Group 5", "Spain"):          (5,    "current Tercera Federación = 5th tier of Spanish pyramid"),
    # France — infobox says 2, but Régional 1 (ex-Division d'Honneur) is the
    # sixth tier (lead: "the sixth-tier ... run by each of the 13 regional leagues").
    ("Régional 1", "France"):                           (6,    "lead: 'sixth-tier' regional leagues (below National 3)"),
}


# ── Input ───────────────────────────────────────────────────────────────────
def load_unique_leagues(path=IN_CSV):
    """Return [(league, country, slug)] de-duplicated, preserving first-seen order."""
    seen = OrderedDict()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            league = (row.get("League")     or "").strip()
            slug   = (row.get("LeagueSlug") or "").strip()
            country = (row.get("Country")   or "").strip()
            if not league:
                continue
            key = (league, country)
            if key not in seen:
                seen[key] = slug
    return [(lg, co, slug) for (lg, co), slug in seen.items()]


def title_for(league, slug):
    """The Wikipedia article title to query. The slug is the URL-encoded
    article path; decoding it is the most reliable source. Fall back to the
    league name. (Wikipedia normalises underscores to spaces itself.)"""
    if slug:
        return urllib.parse.unquote(slug)
    return league


# ── Cache ─────────────────────────────────────────────────────────────────--
def load_cache(path=CACHE):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_cache(cache, path=CACHE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)


# ── Wikipedia API ─────────────────────────────────────────────────────────--
def api_get(params, tries=6):
    """GET the MediaWiki API with retries + exponential backoff."""
    url = API + "?" + urllib.parse.urlencode(params)
    delay = 2.0
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:                       # too many requests
                retry_after = e.headers.get("Retry-After")
                wait = float(retry_after) if (retry_after and retry_after.isdigit()) else delay
                time.sleep(wait)
                delay = min(delay * 2, 60)
                continue
            if e.code >= 500:                       # transient server error
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise
        except (urllib.error.URLError, ConnectionResetError, TimeoutError):
            if attempt == tries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise RuntimeError("Wikipedia API request failed after retries")


def fetch_wikitext_batch(titles):
    """Return {requested_title: (wikitext_or_None, final_title)} for a batch,
    resolving title normalisation and redirects back to the requested title."""
    params = {
        "action": "query", "prop": "revisions", "rvprop": "content",
        "rvslots": "main", "redirects": 1, "format": "json",
        "formatversion": 2, "titles": "|".join(titles),
    }
    q = api_get(params).get("query", {})
    norm  = {n["from"]: n["to"] for n in q.get("normalized", [])}
    redir = {r["from"]: r["to"] for r in q.get("redirects", [])}
    pages = {p.get("title"): p for p in q.get("pages", [])}

    out = {}
    for t in titles:
        cur = norm.get(t, t)
        for _ in range(4):                          # follow redirect chain
            if cur in redir:
                cur = redir[cur]
            else:
                break
        pg = pages.get(cur)
        if not pg or pg.get("missing"):
            out[t] = (None, cur)
            continue
        try:
            wt = pg["revisions"][0]["slots"]["main"]["content"]
        except (KeyError, IndexError):
            wt = ""
        out[t] = (wt, pg.get("title"))
    return out


# ── Parsing ───────────────────────────────────────────────────────────────--
def extract_infobox(wikitext):
    """Return the ``{{Infobox football league ...}}`` block (brace-matched),
    or the whole article if no such infobox is found."""
    low = wikitext.lower()
    i = low.find("{{infobox football league")
    if i < 0:
        i = low.find("{{infobox football")
    if i < 0:
        return wikitext
    depth, j = 0, i
    while j < len(wikitext):
        if wikitext[j:j + 2] == "{{":
            depth += 1
            j += 2
        elif wikitext[j:j + 2] == "}}":
            depth -= 1
            j += 2
            if depth == 0:
                return wikitext[i:j]
        else:
            j += 1
    return wikitext[i:]


def _delink(s):
    """[[target|label]] -> label, [[target]] -> target, then strip HTML/refs."""
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    return s


def parse_level(wikitext):
    """Return (level:int|None, raw:str|None, via:str|None).

    The pyramid tier lives in the infobox ``levels`` parameter (sometimes
    ``level`` or ``pyramid``). The value is usually a wikilink whose label is
    the tier number, e.g. ``[[English football league system|1]]``, or a bare
    number, or text like ``1st`` — so we delink and take the first integer."""
    if not wikitext:
        return None, None, None
    box = extract_infobox(wikitext)
    for key in ("levels", "level", "pyramid"):
        m = re.search(r"\|\s*" + key + r"\s*=\s*([^\n]+)", box, re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1).strip()
        if not raw:
            continue
        clean = _delink(raw).strip()
        num = re.search(r"\d+", clean)
        if num:
            return int(num.group(0)), raw, key
    return None, None, None


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    leagues = load_unique_leagues()
    print(f"Loaded {len(leagues)} unique leagues from {IN_CSV}")

    cache = load_cache()

    # Which Wikipedia titles still need fetching?
    wanted = OrderedDict()                           # title -> None (set of titles, ordered)
    for league, country, slug in leagues:
        wanted[title_for(league, slug)] = None
    todo = [t for t in wanted if t not in cache]
    print(f"{len(wanted) - len(todo)} cached, {len(todo)} to fetch "
          f"({(len(todo) + BATCH - 1) // BATCH} request(s))")

    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        results = fetch_wikitext_batch(batch)
        for t in batch:
            wt, final = results.get(t, (None, t))
            if wt is None:
                cache[t] = {"level": None, "raw": None, "via": None,
                            "final_title": final, "status": "missing"}
            else:
                level, raw, via = parse_level(wt)
                cache[t] = {
                    "level": level, "raw": raw, "via": via,
                    "final_title": final,
                    "status": "ok" if level is not None else "no-level",
                }
        save_cache(cache)
        done = min(start + BATCH, len(todo))
        print(f"  fetched {done}/{len(todo)}")
        if done < len(todo):
            time.sleep(0.5)                          # be polite between batches

    def resolve(league, country, slug):
        """Final (level, raw, status, title) for a league: a hand-checked
        MANUAL_LEVELS entry takes precedence over the Wikipedia-parsed value."""
        info = cache.get(title_for(league, slug), {})
        title = info.get("final_title") or title_for(league, slug)
        if (league, country) in MANUAL_LEVELS:
            level, note = MANUAL_LEVELS[(league, country)]
            status = "manual" if level is not None else "manual-na"
            return level, ("manual: " + note), status, title
        return info.get("level"), (info.get("raw") or ""), info.get("status") or "unknown", title

    # De-duplicate: collapse same-league-different-name entries to one canonical
    # row (shared with build_drill_down.py via league_dedup).
    canon_slug, canon_league, _ = build_canonical_map(load_detail_rows(), cache)

    grouped = OrderedDict()                       # (country, canonical) -> [member dicts]
    for league, country, slug in leagues:
        level, raw, status, title = resolve(league, country, slug)
        canon = canonical_league(country, league, slug, canon_slug, canon_league)
        grouped.setdefault((country, canon), []).append(
            {"league": league, "slug": slug, "level": level,
             "raw": raw, "status": status, "title": title})

    # Write output, one row per real league
    rows_out = []
    for (country, canon), members in grouped.items():
        # Representative: the member named like the canonical with a level,
        # else any member with a level, else the first.
        rep = (next((m for m in members if m["league"] == canon and m["level"] is not None), None)
               or next((m for m in members if m["level"] is not None), None)
               or members[0])
        aliases = sorted({m["league"] for m in members if m["league"] != canon})
        level, raw, status = rep["level"], rep["raw"], rep["status"]
        # Apply a hand-checked correction to a stale/wrong Wikipedia level
        if (canon, country) in LEVEL_CORRECTIONS:
            level, note = LEVEL_CORRECTIONS[(canon, country)]
            raw = "corrected: " + note
            status = "corrected" if level is not None else "corrected-na"
        rows_out.append((canon, country, rep["slug"], rep["title"],
                         level, raw, status, "; ".join(aliases)))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["League", "Country", "LeagueSlug", "WikipediaTitle",
                    "Level", "RawLevel", "Status", "Aliases"])
        for r in rows_out:
            w.writerow([r[0], r[1], r[2], r[3],
                        r[4] if r[4] is not None else "", r[5], r[6], r[7]])

    # Summary
    statuses = Counter(r[6] for r in rows_out)
    levels   = Counter(r[4] for r in rows_out if r[4] is not None)
    merged   = sum(1 for _, members in grouped.items() if len(members) > 1)
    print(f"\nWrote {OUT_CSV}")
    print(f"Leagues: {len(leagues)} raw -> {len(rows_out)} after de-dup "
          f"({merged} merged group(s))")
    print("Status:", dict(statuses))
    print("Level distribution:", dict(sorted(levels.items())))

    # Leagues with no pyramid level fall into two groups:
    #   intentional — hand-checked as outside the senior pyramid (youth/reserve
    #                 development competitions, etc.), flagged via a "*-na" status.
    #                 These are EXPECTED; build_drill_down groups them in a "Youth"
    #                 pyramid row. Mark a new one by adding a MANUAL_LEVELS /
    #                 LEVEL_CORRECTIONS entry with level=None and a "youth"/"reserve" note.
    #   unresolved  — Wikipedia had no parsable level and we haven't classified it;
    #                 these are the ones actually worth a manual look.
    no_level    = [(r[0], r[1], r[6]) for r in rows_out if r[4] is None]
    intentional = [(lg, co) for lg, co, st in no_level if st in ("manual-na", "corrected-na")]
    unresolved  = [(lg, co) for lg, co, st in no_level if st not in ("manual-na", "corrected-na")]
    if intentional:
        print(f"\n{len(intentional)} league(s) intentionally outside the senior pyramid "
              f"(youth/reserve, etc. - expected, shown in the 'Youth' row):")
        for lg, co in intentional:
            print(f"  - {lg}  ({co})")
    if unresolved:
        print(f"\n{len(unresolved)} league(s) still without a level (need attention):")
        for lg, co in unresolved:
            print(f"  - {lg}  ({co})")
    elif not intentional:
        print("\nAll leagues have a pyramid level.")


if __name__ == "__main__":
    main()
