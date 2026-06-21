"""
lookup_clubs.py
===============
For every unique club slug in club_frequency.csv, fetch the Wikipedia page
and extract the club's common name and league from the infobox.

Output:
    club_details.csv  (Slug, Name, League, LeagueSlug, Country)

    LeagueSlug is the Wikipedia article slug for the league (e.g.
    "Premier_League"), taken directly from the href in the infobox link.
    This is used by 05_enrich_club_details.py to look up the country reliably
    without guessing URLs from free-text league names.

    Country is left blank here — enrich_club_details.py populates it.

Run after club_frequency.csv has been produced.
Pages are cached in ./cache/ with a 45-day TTL.
"""
import csv
import hashlib
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "WorldCupClubCheck/1.0 (personal research; contact: your-email@example.com)"
}
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
SLEEP_SECONDS = 1.0
CACHE_MAX_AGE_SECONDS = 86400 * 45  # 45 days
WIKI_BASE = "https://en.wikipedia.org/wiki/"

LEAGUE_LABELS = {"league", "current league", "division", "competition",
                 "current division", "top division"}


def fetch(url: str) -> str:
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    cache_path = CACHE_DIR / f"{key}.html"
    if cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < CACHE_MAX_AGE_SECONDS:
            return cache_path.read_text(encoding="utf-8")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    cache_path.write_text(r.text, encoding="utf-8")
    time.sleep(SLEEP_SECONDS)
    return r.text


def extract_league(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (league_name, league_slug) from the club infobox.

    Uses the first <a href="/wiki/..."> inside the matching cell so we get
    the canonical league name and its Wikipedia slug directly — avoiding
    concatenated multi-league text and ambiguous plain-text names.
    """
    for infobox in soup.select("table.infobox"):
        for tr in infobox.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            label = th.get_text(" ", strip=True).lower().strip()
            if not any(l in label for l in LEAGUE_LABELS):
                continue
            # Use the first wiki link in the cell
            for a in td.find_all("a", href=True):
                href = a["href"]
                if href.startswith("/wiki/") and ":" not in href:
                    name = a.get_text(strip=True)
                    slug = href[len("/wiki/"):]
                    return name, slug
            # No link found — fall back to plain text (first line only)
            text = td.get_text(" ", strip=True).split("\n")[0].strip()
            for noise in ("[note", "[1]", "[2]", "[3]"):
                text = text.split(noise)[0].strip()
            return text, ""
    return "", ""


def lookup_club(slug: str) -> tuple[str, str, str]:
    """Return (name, league_name, league_slug) for a Wikipedia club slug."""
    url = WIKI_BASE + slug
    try:
        html = fetch(url)
    except Exception as e:
        print(f"  ERROR fetching {slug}: {e}", file=sys.stderr)
        return unquote(slug.replace("_", " ")), "", ""

    soup = BeautifulSoup(html, "lxml")

    h1 = soup.select_one("h1#firstHeading, h1.firstHeading")
    name = h1.get_text(strip=True) if h1 else unquote(slug.replace("_", " "))

    league_name, league_slug = extract_league(soup)
    return name, league_name, league_slug


def main(freq_csv: str = "club_frequency.csv", out_csv: str = "club_details.csv"):
    with open(freq_csv, newline="", encoding="utf-8") as f:
        slugs = [row["Club"] for row in csv.DictReader(f)]

    print(f"Looking up {len(slugs)} clubs...", file=sys.stderr)

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Slug", "Name", "League", "LeagueSlug", "Country"])

        for i, slug in enumerate(slugs, 1):
            name, league, league_slug = lookup_club(slug)
            w.writerow([slug, name, league, league_slug, ""])
            if i % 25 == 0 or i == len(slugs):
                print(f"  [{i}/{len(slugs)}] {slug}", file=sys.stderr)

    print(f"Done. Written to {out_csv}.", file=sys.stderr)


if __name__ == "__main__":
    main()
