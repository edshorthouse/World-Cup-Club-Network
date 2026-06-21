#!/usr/bin/env python3
"""
verify_countries.py
===================
Cross-checks every club's assigned Country (club_details.csv, which is derived
from the club's *league*) against the country stated in the club's own
Wikipedia categories (e.g. "Football clubs in Jordan"). A mismatch usually
means a wrong league/country attribution — most often a hand-entered
_CLUB_LEAGUE_OVERRIDES entry in 05_enrich_club_details.py pointing at the wrong
country (this is how "That Ras SC" ended up listed as Yemeni instead of
Jordanian).

Reads:  club_details.csv  +  cached club pages in ./cache/  (no network)
Output: a list of clubs whose assigned country disagrees with their categories.

Some clubs legitimately play in another country's league (e.g. NZ's Wellington
Phoenix in the Australian A-League, like Monaco in France's Ligue 1). Those are
listed in ALLOWED_CROSS_BORDER so they don't raise a false alarm.

Run after 05_enrich_club_details.py. Exits non-zero if any unexplained
mismatch is found, so it can gate a pipeline run.
"""
import csv
import hashlib
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

CACHE_DIR = Path("cache")
WIKI_BASE = "https://en.wikipedia.org/wiki/"
DETAILS_CSV = "club_details.csv"

# (Slug) -> reason. Clubs that genuinely compete in another country's league.
ALLOWED_CROSS_BORDER = {
    "Wellington_Phoenix_FC":   "NZ club in the Australian A-League",
    "Wellington_Phoenix_F.C.": "NZ club in the Australian A-League",
    "Auckland_FC":             "NZ club in the Australian A-League",
}

# Wikipedia category place names -> our canonical country names.
NORM = {
    "the United States": "United States", "United States of America": "United States",
    "the Republic of Ireland": "Ireland", "Republic of Ireland": "Ireland",
    "the Netherlands": "Netherlands", "Czechia": "Czech Republic",
    "the Czech Republic": "Czech Republic", "Türkiye": "Turkey",
    "the United Arab Emirates": "United Arab Emirates",
    "the Democratic Republic of the Congo": "DR Congo",
    "the People's Republic of China": "China",
}

_PATTERNS = [
    re.compile(r"^Football clubs in (.+)$"),
    re.compile(r"^Association football clubs .*? in (.+)$"),
    re.compile(r"^\d{4} establishments in (.+)$"),
    re.compile(r"^Sport in (.+)$"),
]


def cache_path(slug: str) -> Path:
    url = WIKI_BASE + slug.split("#")[0]
    return CACHE_DIR / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.html"


def category_countries(soup, valid: set) -> set:
    """Countries named in the page's categories that we recognise."""
    out = set()
    for a in soup.select("div#mw-normal-catlinks a, div.mw-normal-catlinks a"):
        text = a.get_text(strip=True)
        for pat in _PATTERNS:
            m = pat.match(text)
            if m:
                place = NORM.get(m.group(1).strip(), m.group(1).strip())
                if place in valid:
                    out.add(place)
    return out


def main(details_csv: str = DETAILS_CSV) -> int:
    rows = list(csv.DictReader(open(details_csv, encoding="utf-8")))
    valid = {(r["Country"] or "").strip() for r in rows if (r["Country"] or "").strip()}

    checked = no_cache = no_category = 0
    mismatches, allowed = [], []
    for r in rows:
        slug = r["Slug"]
        assigned = (r["Country"] or "").strip()
        p = cache_path(slug)
        if not p.exists():
            no_cache += 1
            continue
        soup = BeautifulSoup(p.read_text(encoding="utf-8"), "lxml")
        cats = category_countries(soup, valid)
        checked += 1
        if not cats:
            no_category += 1
            continue
        if assigned and assigned not in cats:
            entry = (r["Name"], slug, assigned, sorted(cats))
            (allowed if slug in ALLOWED_CROSS_BORDER else mismatches).append(entry)

    print(f"Checked {checked} clubs against Wikipedia categories "
          f"({no_cache} not cached, {no_category} had no country category).")
    if allowed:
        print(f"\n{len(allowed)} known cross-border club(s) (league in another country — OK):")
        for name, slug, assigned, cats in allowed:
            print(f"  - {name}: league country {assigned}, located in {cats} "
                  f"({ALLOWED_CROSS_BORDER[slug]})")
    if mismatches:
        print(f"\n*** {len(mismatches)} COUNTRY MISMATCH(ES) — likely wrong attribution ***")
        for name, slug, assigned, cats in sorted(mismatches, key=lambda x: x[2]):
            print(f"  - {name} [{slug}]: assigned {assigned!r}, categories say {cats}")
        print("\nFix the league/country in 05_enrich_club_details.py "
              "(_CLUB_LEAGUE_OVERRIDES) then re-run 05 -> 08.")
        return 1
    print("\nOK - every club's assigned country matches its Wikipedia categories.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
