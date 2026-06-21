"""
check_everton.py
================
For every player in players.csv, fetch their Wikipedia page and check whether
"Everton" appears as a CLUB association — specifically:
  1) inside the right-hand infobox (Youth career / Senior career), OR
  2) inside a Career statistics table (Club column).

Mentions in the prose (e.g. "scored against Everton") are deliberately
EXCLUDED, because those don't mean the player was contracted to the club.

Run:
    pip install requests beautifulsoup4 lxml
    python extract_players.py        # produces players.csv
    python check_everton.py          # produces everton_hits.csv

Politeness:
    - 1 request per second (Wikipedia's recommended rate for unauthenticated
      bulk fetching). For ~1200 players, expect ~20 minutes.
    - Cached: pages already fetched into ./cache/ are not refetched.

Output:
    everton_hits.csv  (Nation, Player, WikiURL, Where, Detail)
        Where = 'infobox' or 'career_stats'
        Detail = the row text where Everton was found
"""
import csv
import hashlib
import os
import re
import sys
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup, Tag

HEADERS = {
    "User-Agent": "EvertonAcademyCheck/1.0 (personal research; contact: your-email@example.com)"
}
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
SLEEP_SECONDS = 1.0  # be polite
CACHE_MAX_AGE_SECONDS = 86400  # 1 day

EVERTON_FC_HREF = "/wiki/Everton_F.C."


def fetch(url: str) -> str:
    """Fetch a URL with on-disk caching (1-day TTL)."""
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


def row_links_to_everton_fc(tag) -> bool:
    """True if the tag contains a link whose href is exactly /wiki/Everton_F.C."""
    for a in tag.find_all("a", href=True):
        if a["href"] == EVERTON_FC_HREF:
            return True
    return False


def check_infobox(soup: BeautifulSoup):
    """Return list of (where, snippet) tuples for Everton F.C. hits in the
    right-hand infobox (Youth career / Senior career / Managerial career)."""
    hits = []
    for infobox in soup.select("table.infobox"):
        for tr in infobox.find_all("tr"):
            if not row_links_to_everton_fc(tr):
                continue
            text = tr.get_text(" ", strip=True)
            if not re.search(r"\b(19|20)\d{2}\b", text):
                continue
            hits.append(("infobox", text))
    return hits


def check_career_stats(soup: BeautifulSoup):
    """Return list of (where, snippet) tuples for Everton F.C. hits in any
    career statistics wikitable."""
    hits = []
    for table in soup.select("table.wikitable"):
        first_row = table.find("tr")
        if not first_row:
            continue
        headers = [th.get_text(" ", strip=True).lower()
                   for th in first_row.find_all(["th", "td"])]
        is_stats_table = (
            "club" in headers
            and any(h in headers for h in ("season", "apps", "appearances",
                                            "league", "total"))
        )
        if not is_stats_table:
            continue
        for tr in table.find_all("tr")[1:]:
            if row_links_to_everton_fc(tr):
                hits.append(("career_stats", tr.get_text(" | ", strip=True)))
    return hits


def check_player(url: str):
    """Return list of (where, snippet) hits for this player's wiki page."""
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    hits = []
    hits.extend(check_infobox(soup))
    hits.extend(check_career_stats(soup))
    return hits


def main(players_csv: str = "players.csv",
         out_csv: str = "everton_hits.csv"):
    with open(players_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Checking {len(rows)} players...", file=sys.stderr)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Nation", "Player", "WikiURL", "Where", "Detail"])

        for i, row in enumerate(rows, 1):
            try:
                hits = check_player(row["WikiURL"])
            except Exception as e:
                print(f"  [{i}/{len(rows)}] ERROR {row['Player']}: {e}",
                      file=sys.stderr)
                continue
            if hits:
                for where, detail in hits:
                    w.writerow([row["Nation"], row["Player"], row["WikiURL"],
                                where, detail])
                print(f"  [{i}/{len(rows)}] HIT {row['Nation']:<20} "
                      f"{row['Player']} ({len(hits)} match{'es' if len(hits) != 1 else ''})",
                      file=sys.stderr)
            elif i % 50 == 0:
                print(f"  [{i}/{len(rows)}] no hit, "
                      f"latest: {row['Player']}", file=sys.stderr)

    print(f"Done. Hits written to {out_csv}.", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:])
