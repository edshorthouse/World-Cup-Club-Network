"""
extract_players.py
==================
Scrapes https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads and writes
players.csv with one row per player (Nation, Player, WikiURL).

How it works
------------
The squads page lists 48 nations as <h3> headings; the squad under each
heading is a wikitable with a 'Player' column whose cells link to the
player's own Wikipedia page. We walk the document in order so we know which
nation a given table belongs to, then extract every player-link from each
table's rows.

Run:
    pip install requests beautifulsoup4 lxml
    python extract_players.py

Output:
    players.csv  (Nation, Player, WikiURL)
"""
import csv
import re
import sys
import time
import requests
from bs4 import BeautifulSoup

PAGE_TITLE = "2026_FIFA_World_Cup_squads"
API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = {
    "User-Agent": "EvertonAcademyCheck/1.0 (personal research; contact: your-email@example.com)"
}


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_squads_html() -> str:
    """Fetch the squads page via the Wikipedia parse API (avoids empty-body issue
    with direct HTML scraping of transcluded pages)."""
    r = requests.get(API_URL, headers=HEADERS, timeout=30, params={
        "action": "parse",
        "page": PAGE_TITLE,
        "prop": "text",
        "format": "json",
    })
    r.raise_for_status()
    data = r.json()
    if "parse" not in data:
        raise RuntimeError(f"Wikipedia API error: {data}")
    return data["parse"]["text"]["*"]


def extract_players(html: str):
    """Yield (nation, player_name, full_wiki_url) tuples from the squads page."""
    soup = BeautifulSoup(html, "lxml")
    content = soup.select_one("div.mw-parser-output") or soup

    current_nation = None
    # Walk every child of the parser output in order.
    for el in content.descendants:
        if not hasattr(el, "name") or el.name is None:
            continue

        # Nation headings: h3 with a .mw-headline span, or just h3 text.
        if el.name in ("h2", "h3"):
            headline = el.find("span", class_="mw-headline")
            text = (headline.get_text(strip=True) if headline
                    else el.get_text(strip=True).replace("[edit]", ""))
            if not text:
                continue
            skip_words = ("group ", "statistics", "references", "see also",
                          "notes", "external", "contents", "navigation",
                          "by club", "by confederation", "coach")
            low = text.lower()
            if any(w in low for w in skip_words):
                continue
            if el.name == "h3":
                current_nation = text
            continue

        # Squad tables: wikitable directly under the current h3.
        if el.name == "table" and current_nation:
            css = el.get("class") or []
            if "wikitable" not in css:
                continue
            # A squad table's first row is the column headers
            # (No., Pos., Player, Date of birth (age), Caps, Club).
            for tr in el.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if len(cells) < 4:
                    continue
                player_cell = _find_player_cell(cells)
                if player_cell is None:
                    continue
                link = _find_player_link(player_cell)
                if link is None:
                    continue
                name = link.get_text(strip=True)
                href = link["href"]
                if href.startswith("/wiki/"):
                    url = "https://en.wikipedia.org" + href
                elif href.startswith("./"):
                    url = "https://en.wikipedia.org/wiki/" + href[2:]
                else:
                    url = href
                yield current_nation, name, url


def _find_player_cell(cells):
    """The Player cell is the 3rd column in a standard squad table."""
    return cells[2] if len(cells) >= 3 else None


def _find_player_link(cell):
    """Return the player's <a> link from a Player-column cell, ignoring
    flag-icon links and other non-player anchors."""
    for a in cell.find_all("a", href=True):
        href = a["href"]
        # Skip flag images and section anchors.
        if a.find("img"):
            continue
        if href.startswith("#"):
            continue
        # Player wiki links look like /wiki/Player_Name with no colon.
        if href.startswith("/wiki/") and ":" not in href:
            return a
        if href.startswith("./") and ":" not in href:
            return a
    return None


def main():
    print(f"Fetching {PAGE_TITLE} via Wikipedia API ...", file=sys.stderr)
    html = fetch_squads_html()
    rows = list(extract_players(html))

    # Deduplicate while preserving order (same player listed twice = unlikely
    # but possible if the page structure changes).
    seen = set()
    deduped = []
    for nation, name, url in rows:
        key = (nation, url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((nation, name, url))

    with open("players.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Nation", "Player", "WikiURL"])
        w.writerows(deduped)

    nations = sorted({n for n, _, _ in deduped})
    print(f"Wrote players.csv with {len(deduped)} players across "
          f"{len(nations)} nations.", file=sys.stderr)
    print("Sample:", file=sys.stderr)
    for r in deduped[:3] + deduped[-3:]:
        print(" ", r, file=sys.stderr)


if __name__ == "__main__":
    main()
