"""
detect_dissolved.py
===================
Scans each club's cached Wikipedia page for a "Dissolved" (or "Defunct")
field in the infobox and records the dissolution year. These clubs are
grouped into a per-country "Dissolved clubs" league by the visualisation.

Reads:
    club_details.csv   (Slug, Name, League, Country)
    ./cache/*.html      (club pages already fetched by lookup_clubs.py)

Output:
    dissolved_clubs.json   {slug: {league, country, year}}

Run after club_details.csv exists. No network needed: it only reads pages
already in ./cache/ (re-fetched by 02_extract_clubs.py / 04_lookup_clubs.py).
"""
import csv
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

CACHE_DIR = Path("cache")
WIKI_BASE = "https://en.wikipedia.org/wiki/"
DETAILS_CSV = "club_details.csv"
OUT_JSON = "dissolved_clubs.json"

_YEAR_RE = re.compile(r"\b(\d{4})\b")
DISSOLVED_LABELS = ("dissolved", "defunct")


def cache_path(slug: str) -> Path:
    """The cache file for a club slug (matches the scrapers' sha1(url) key)."""
    key = hashlib.sha1((WIKI_BASE + slug).encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.html"


def dissolved_year(soup: BeautifulSoup) -> str | None:
    """Return the dissolution year from the infobox, or None if not dissolved."""
    for infobox in soup.select("table.infobox"):
        for tr in infobox.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            label = th.get_text(" ", strip=True).lower()
            if not any(l in label for l in DISSOLVED_LABELS):
                continue
            m = _YEAR_RE.search(td.get_text(" ", strip=True))
            return m.group(1) if m else ""   # "" = dissolved, year unknown
    return None


def main(details_csv: str = DETAILS_CSV, out_json: str = OUT_JSON):
    with open(details_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    print(f"Scanning {total} cached club pages for a 'Dissolved' field "
          f"(no network needed)...", flush=True)

    found, missing_cache = {}, 0
    for i, r in enumerate(rows, 1):
        slug = (r.get("Slug") or "").strip()
        if slug:
            path = cache_path(slug)
            if path.exists():
                soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
                year = dissolved_year(soup)
                if year is not None:
                    found[slug] = {
                        "league":  (r.get("League") or "").strip(),
                        "country": (r.get("Country") or "").strip(),
                        "year":    year,
                    }
            else:
                missing_cache += 1
        if i % 250 == 0 or i == total:
            print(f"  {i}/{total} scanned - {len(found)} dissolved so far", flush=True)

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Scanned {total} clubs ({missing_cache} missing from cache); "
          f"found {len(found)} dissolved. Wrote {out_json}.", flush=True)


if __name__ == "__main__":
    main()
