"""
extract_clubs.py
================
For every player in players.csv, fetch their Wikipedia page and extract
their senior career clubs from the infobox, including the years/seasons of
each spell and whether it was a loan.

Outputs:
    clubs.csv         (Player, Team, Confederation, Club 1, Club 2, ...)
                      — unique club slugs in career order (back-compatible).
    club_spells.csv   one row per spell:
                      Player, Team, Confederation, Order, ClubSlug, ClubName,
                      Years, StartYear, EndYear, Loan
                      — keeps repeated/loan spells separate (e.g. a loan and a
                      later permanent move to the same club are two rows).

Run after 01_extract_players.py has produced players.csv.
Pages are cached in ./cache/ so re-runs are fast.
"""
import csv
import hashlib
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "WorldCupClubCheck/1.0 (personal research; contact: your-email@example.com)"
}
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
SLEEP_SECONDS = 1.0

CONFEDERATION_MAP = {
    # UEFA
    "Albania": "UEFA", "Austria": "UEFA", "Belgium": "UEFA",
    "Bosnia and Herzegovina": "UEFA", "Croatia": "UEFA",
    "Czech Republic": "UEFA", "Denmark": "UEFA", "England": "UEFA",
    "France": "UEFA", "Georgia": "UEFA", "Germany": "UEFA",
    "Hungary": "UEFA", "Italy": "UEFA", "Netherlands": "UEFA",
    "Norway": "UEFA", "Poland": "UEFA", "Portugal": "UEFA",
    "Romania": "UEFA", "Scotland": "UEFA", "Serbia": "UEFA",
    "Slovakia": "UEFA", "Slovenia": "UEFA", "Spain": "UEFA",
    "Switzerland": "UEFA", "Turkey": "UEFA", "Ukraine": "UEFA",
    "Wales": "UEFA",
    # CONMEBOL
    "Argentina": "CONMEBOL", "Bolivia": "CONMEBOL", "Brazil": "CONMEBOL",
    "Chile": "CONMEBOL", "Colombia": "CONMEBOL", "Ecuador": "CONMEBOL",
    "Paraguay": "CONMEBOL", "Peru": "CONMEBOL", "Uruguay": "CONMEBOL",
    "Venezuela": "CONMEBOL",
    # CONCACAF
    "Canada": "CONCACAF", "Costa Rica": "CONCACAF", "Cuba": "CONCACAF",
    "Haiti": "CONCACAF", "Honduras": "CONCACAF", "Jamaica": "CONCACAF",
    "Mexico": "CONCACAF", "Panama": "CONCACAF",
    "Trinidad and Tobago": "CONCACAF", "United States": "CONCACAF",
    # CAF
    "Algeria": "CAF", "Angola": "CAF", "Benin": "CAF", "Cameroon": "CAF",
    "Cape Verde": "CAF", "Comoros": "CAF", "DR Congo": "CAF",
    "Egypt": "CAF", "Ghana": "CAF", "Guinea": "CAF",
    "Ivory Coast": "CAF", "Kenya": "CAF", "Mali": "CAF",
    "Morocco": "CAF", "Mozambique": "CAF", "Nigeria": "CAF",
    "Senegal": "CAF", "South Africa": "CAF", "Tanzania": "CAF",
    "Tunisia": "CAF", "Uganda": "CAF", "Zambia": "CAF", "Zimbabwe": "CAF",
    # AFC
    "Australia": "AFC", "China PR": "AFC", "India": "AFC",
    "Indonesia": "AFC", "Iran": "AFC", "Iraq": "AFC", "Japan": "AFC",
    "Jordan": "AFC", "Kuwait": "AFC", "Kyrgyzstan": "AFC",
    "Oman": "AFC", "Qatar": "AFC", "Saudi Arabia": "AFC",
    "South Korea": "AFC", "Syria": "AFC", "Tajikistan": "AFC",
    "Thailand": "AFC", "Uzbekistan": "AFC",
    # OFC
    "New Zealand": "OFC",
}


CACHE_MAX_AGE_SECONDS = 86400  # 1 day


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


_YEAR_RE = re.compile(r"\d{4}")


def parse_years(text: str):
    """Parse a senior-career year cell into (raw, start, end).

    Examples:
      '2010–2015' -> ('2010–2015', '2010', '2015')
      '2020–'     -> ('2020–',     '2020', '')      # '' end = ongoing/present
      '2012'      -> ('2012',      '2012', '2012')  # single year
    """
    raw = re.sub(r"\[.*?\]", "", text).strip()        # drop ref markers like [1]
    norm = raw.replace("–", "-").replace("—", "-").replace("‒", "-")
    years = _YEAR_RE.findall(norm)
    start = years[0] if years else ""
    if "-" in norm:                                   # it's a range
        end = years[1] if len(years) > 1 else ""      # open-ended -> ongoing
    else:
        end = start
    return raw, start, end


def extract_senior_spells(soup: BeautifulSoup) -> list[dict]:
    """Extract senior career spells from the Wikipedia footballer infobox.

    Each spell is {slug, name, years, start, end, loan}. Slugs are the part
    after /wiki/ so they map unambiguously to a Wikipedia page. Spells are kept
    in career order and NOT collapsed by club, so two stints at the same club
    (e.g. a loan then a permanent transfer) appear as separate spells.

    Infobox structure:
      <tr><th colspan=2>Senior career*</th></tr>          ← section header
      <tr><th>Years</th><td>Team</td></tr>                ← column sub-header
      <tr><th>2012–2020</th><td><a href="/wiki/Club">Club</a></td></tr>
      <tr><th>2012</th><td>→ <a ...>Club</a> (loan)</td></tr>   ← loan spell
    """
    spells = []
    seen = set()
    for infobox in soup.select("table.infobox"):
        in_senior = False
        for tr in infobox.find_all("tr"):
            row_text = tr.get_text(" ", strip=True).lower()

            # Detect section headers
            th_cols = tr.find_all("th")
            is_section_header = any(
                th.get("colspan") for th in th_cols
            ) or (len(th_cols) == 1 and not tr.find("td"))

            if is_section_header:
                if "senior career" in row_text or "club career" in row_text:
                    in_senior = True
                elif in_senior:
                    break
                continue

            if not in_senior:
                continue

            td = tr.find("td")
            if not td:
                continue

            # Club slug + display name — first real wiki link (skip flag images)
            slug = name = None
            for a in td.find_all("a", href=True):
                if a.find("img"):
                    continue
                href = a["href"]
                if not href.startswith("/wiki/") or ":" in href:  # skip File:/Category:
                    continue
                slug = href[len("/wiki/"):]
                name = a.get_text(strip=True)
                break
            if not slug:
                continue  # e.g. the "Years / Team" column sub-header row

            years_th = tr.find("th")
            years_raw, start, end = (
                parse_years(years_th.get_text(" ", strip=True)) if years_th else ("", "", "")
            )

            # Loan spells are shown as "→ Club (loan)"
            cell = td.get_text(" ", strip=True)
            loan = ("loan" in cell.lower()) or cell.lstrip().startswith("→")

            key = (slug, years_raw)                    # dedupe only exact repeats
            if key in seen:
                continue
            seen.add(key)
            spells.append({"slug": slug, "name": name, "years": years_raw,
                           "start": start, "end": end, "loan": loan})

    return spells


def unique_slugs(spells):
    """Career-ordered unique club slugs (first occurrence wins)."""
    seen, out = set(), []
    for s in spells:
        if s["slug"] not in seen:
            seen.add(s["slug"])
            out.append(s["slug"])
    return out


def main(players_csv: str = "players.csv", out_csv: str = "clubs.csv",
         spells_csv: str = "club_spells.csv"):
    with open(players_csv, newline="", encoding="utf-8") as f:
        players = list(csv.DictReader(f))

    print(f"Processing {len(players)} players...", file=sys.stderr)

    all_rows = []          # (player, nation, confederation, spells)
    max_clubs = 0

    for i, row in enumerate(players, 1):
        try:
            html = fetch(row["WikiURL"])
            soup = BeautifulSoup(html, "lxml")
            spells = extract_senior_spells(soup)
        except Exception as e:
            print(f"  [{i}/{len(players)}] ERROR {row['Player']}: {e}",
                  file=sys.stderr)
            spells = []

        nation = row["Nation"]
        confederation = CONFEDERATION_MAP.get(nation, "Unknown")
        all_rows.append((row["Player"], nation, confederation, spells))
        max_clubs = max(max_clubs, len(unique_slugs(spells)))

        if i % 50 == 0:
            print(f"  [{i}/{len(players)}] latest: {row['Player']}",
                  file=sys.stderr)

    # 1) clubs.csv — unique slugs in career order (back-compatible wide format)
    headers = ["Player", "Team", "Confederation"] + [
        f"Club {n}" for n in range(1, max_clubs + 1)
    ]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for player, nation, confederation, spells in all_rows:
            w.writerow([player, nation, confederation] + unique_slugs(spells))

    # 2) club_spells.csv — one row per spell, with years and loan flag
    with open(spells_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Player", "Team", "Confederation", "Order", "ClubSlug",
                    "ClubName", "Years", "StartYear", "EndYear", "Loan"])
        for player, nation, confederation, spells in all_rows:
            for order, s in enumerate(spells, 1):
                w.writerow([player, nation, confederation, order, s["slug"],
                            s["name"], s["years"], s["start"], s["end"],
                            "yes" if s["loan"] else "no"])

    print(f"Done. Wrote {len(all_rows)} players to {out_csv} (max {max_clubs} "
          f"clubs) and per-spell data to {spells_csv}.", file=sys.stderr)


if __name__ == "__main__":
    main()
