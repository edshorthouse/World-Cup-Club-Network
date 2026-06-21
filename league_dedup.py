#!/usr/bin/env python3
"""
league_dedup.py
===============
Shared league de-duplication used by both league_levels.py and
build_drill_down.py so the levels table and the visualisation agree on a
single canonical name per real-world league.

The source data lists the same league under several names (sponsor names,
era names, generic vs country-qualified), e.g. Argentina's top flight appears
as "Primera División", "Liga Profesional" and "Liga Profesional de Fútbol".
These are detected by resolving each LeagueSlug to its Wikipedia article
(via league_levels_cache.json) and grouping entries in the same country that
land on the same article.

Care is taken NOT to over-merge: some slugs point at an umbrella article with
a #section anchor (e.g. Ghana's Division One vs Division Two both link to
"Ghana Football Leagues#..."); the anchor is kept in the key so those stay
separate.

Canonical display name for a group = the member name used by the most clubs
(ties broken by longer, then alphabetical). Override via CANON_OVERRIDES.
"""
import csv
import json
import os
import urllib.parse
from collections import Counter, defaultdict

CACHE = "league_levels_cache.json"

# (Country, canonical-we-would-pick) -> preferred display name. Use to fix a
# group whose most-common member name is a defunct sponsor name, etc.
CANON_OVERRIDES = {
    # Most-common member name is a defunct sponsor name; prefer the neutral one.
    ("New Zealand", "ASB Premiership"): "New Zealand Football Championship",
    # Stale display names whose number contradicts the actual tier — relabel to
    # the league's current name (tier is handled separately in league_levels).
    ("France", "Championnat National 3"): "Championnat National 2 (National 2)",
    ("Spain", "3ª – Group 5"): "Tercera Federación – Group 5",
    # Leagues that have been officially renamed — show the current name.
    ("Canada", "Ligue1 Québec"): "LS Pro",
    ("Oman", "Oman Elite League"): "Oman Professional League",
    ("Australia", "National Youth League"): "A-League Youth",
    ("Belgium", "Proximus League"): "Belgian Second Division",
    ("Morocco", "Amateurs I"): "Amateur National",
}


def load_cache(path=CACHE):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def load_detail_rows(path="club_details.csv"):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def group_key(country, league, slug, cache):
    """Identity of the real league. Same key => same league => merge."""
    if slug:
        anchor = "#" + slug.split("#", 1)[1] if "#" in slug else ""
        final = cache.get(urllib.parse.unquote(slug), {}).get("final_title")
        if final:
            return (country, "WIKI::" + final + anchor)
        return (country, "SLUG::" + slug)        # no wiki match: same slug only
    return (country, "RAW::" + league)            # no slug: name only


def build_canonical_map(detail_rows, cache=None):
    """Return (canon_by_country_slug, canon_by_country_league, canon_of_root).

    canon_by_country_slug  : {(country, league_slug): canonical_name}
    canon_by_country_league: {(country, raw_league_name): canonical_name}
    canon_of_root          : {component_root: canonical_name}  (introspection)

    Two entries are the same league (merged) if, within a country, they share
    either the same resolved-article group_key OR the same display name. These
    two signals are combined with union-find so the result is order-independent
    and identical no matter which slug a caller happens to pass (e.g. Norway's
    "2. divisjon", which appears under two different slugs).
    """
    if cache is None:
        cache = load_cache()

    entry_count = Counter()                       # (country, league, slug) -> clubs
    for r in detail_rows:
        country = (r.get("Country") or "").strip()
        league  = (r.get("League") or "").strip()
        slug    = (r.get("LeagueSlug") or "").strip()
        if not league:
            continue
        entry_count[(country, league, slug)] += 1
    entries = list(entry_count)

    parent = {e: e for e in entries}
    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_group = defaultdict(list)                   # group_key            -> entries
    by_name  = defaultdict(list)                   # (country, name)      -> entries
    for e in entries:
        country, league, slug = e
        by_group[group_key(country, league, slug, cache)].append(e)
        by_name[(country, league)].append(e)
    for bucket in list(by_group.values()) + list(by_name.values()):
        for e in bucket[1:]:
            union(bucket[0], e)

    comp_names = defaultdict(Counter)             # root -> Counter(name -> clubs)
    for e in entries:
        comp_names[find(e)][e[1]] += entry_count[e]

    canon_of_root = {}
    for root, counts in comp_names.items():
        best = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]
        canon_of_root[root] = CANON_OVERRIDES.get((root[0], best), best)

    canon_by_country_slug = {}
    canon_by_country_league = {}
    for e in entries:
        country, league, slug = e
        name = canon_of_root[find(e)]
        canon_by_country_slug[(country, slug)] = name
        canon_by_country_league[(country, league)] = name

    return canon_by_country_slug, canon_by_country_league, canon_of_root


def canonical_league(country, league, slug, canon_by_country_slug, canon_by_country_league):
    """Resolve one (country, league, slug) to its canonical league name."""
    return (canon_by_country_slug.get((country, slug))
            or canon_by_country_league.get((country, league))
            or league)
