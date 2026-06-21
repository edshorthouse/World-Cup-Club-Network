"""
check_squad_updates.py
======================
Re-scrapes the 2026 FIFA World Cup squads Wikipedia page and compares
against the existing players.csv, reporting any additions or removals.

Run at any time to check if the squads page has changed since players.csv
was last generated.
"""
import csv
import sys
import requests
from bs4 import BeautifulSoup

PAGE_TITLE = "2026_FIFA_World_Cup_squads"
API_URL    = "https://en.wikipedia.org/w/api.php"
HEADERS    = {
    "User-Agent": "WorldCupSquadCheck/1.0 (personal research; contact: your-email@example.com)"
}


def fetch_squads_html() -> str:
    r = requests.get(API_URL, headers=HEADERS, timeout=30, params={
        "action": "parse",
        "page":   PAGE_TITLE,
        "prop":   "text",
        "format": "json",
    })
    r.raise_for_status()
    data = r.json()
    if "parse" not in data:
        raise RuntimeError(f"Wikipedia API error: {data}")
    return data["parse"]["text"]["*"]


def scrape_players(html: str) -> dict[tuple, str]:
    """Return {(nation, wiki_slug): player_name} from the live page."""
    soup = BeautifulSoup(html, "lxml")
    players = {}
    current_nation = None

    for el in soup.descendants:
        if not hasattr(el, "name") or el.name is None:
            continue

        if el.name in ("h2", "h3"):
            headline = el.find("span", class_="mw-headline")
            text = (headline.get_text(strip=True) if headline
                    else el.get_text(strip=True).replace("[edit]", ""))
            skip_words = ("group ", "statistics", "references", "see also",
                          "notes", "external", "contents", "navigation",
                          "by club", "by confederation", "coach")
            if any(w in text.lower() for w in skip_words):
                continue
            if el.name == "h3":
                current_nation = text
            continue

        if el.name == "table" and current_nation:
            if "wikitable" not in (el.get("class") or []):
                continue
            for tr in el.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if len(cells) < 3:
                    continue
                cell = cells[2]
                for a in cell.find_all("a", href=True):
                    if a.find("img"):
                        continue
                    href = a["href"]
                    if href.startswith("#"):
                        continue
                    if href.startswith("/wiki/") and ":" not in href:
                        slug = href[len("/wiki/"):]
                        players[(current_nation, slug)] = a.get_text(strip=True)
                        break

    return players


def load_existing(path: str = "players.csv") -> dict[tuple, str]:
    """Return {(nation, wiki_slug): player_name} from the local CSV."""
    players = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            slug = row["WikiURL"].replace("https://en.wikipedia.org/wiki/", "")
            players[(row["Nation"], slug)] = row["Player"]
    return players


def main():
    print("Fetching live squads page...", file=sys.stderr)
    html = fetch_squads_html()
    live = scrape_players(html)

    print("Loading existing players.csv...", file=sys.stderr)
    existing = load_existing()

    added   = {k: v for k, v in live.items()     if k not in existing}
    removed = {k: v for k, v in existing.items() if k not in live}
    changed = {
        k: (existing[k], live[k])
        for k in live
        if k in existing and live[k] != existing[k]
    }

    print(f"\n── Summary ───────────────────────────────")
    print(f"  Existing players.csv : {len(existing):>4} players")
    print(f"  Live Wikipedia page  : {len(live):>4} players")
    print(f"  Added                : {len(added):>4}")
    print(f"  Removed              : {len(removed):>4}")
    print(f"  Name changes         : {len(changed):>4}")

    if added:
        print(f"\n── Added ({len(added)}) ───────────────────────────")
        for (nation, slug), name in sorted(added.items()):
            print(f"  + [{nation}] {name}  (/wiki/{slug})")

    if removed:
        print(f"\n── Removed ({len(removed)}) ─────────────────────────")
        for (nation, slug), name in sorted(removed.items()):
            print(f"  - [{nation}] {name}  (/wiki/{slug})")

    if changed:
        print(f"\n── Name changes ({len(changed)}) ──────────────────────")
        for (nation, slug), (old, new) in sorted(changed.items()):
            print(f"  ~ [{nation}] '{old}' → '{new}'  (/wiki/{slug})")

    if not added and not removed and not changed:
        print("\n  No changes — players.csv is up to date.")


if __name__ == "__main__":
    main()
