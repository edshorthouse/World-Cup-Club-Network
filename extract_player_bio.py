"""
extract_player_bio.py
=====================
Pulls each player's playing Position and Date of birth from the cached
Wikipedia pages (the same pages 02_extract_clubs.py already fetched), so no
network is needed. Age is NOT stored — it's computed live in the browser from
the DOB so it stays current.

Reads:  players.csv  +  cached player pages in ./cache/
Output: player_bio.csv  (Player, Team, Position, DOB)   DOB = YYYY-MM-DD

Run after 02_extract_clubs.py (which populates the player-page cache), before
08_build_drill_down.py.
"""
import csv
import hashlib
import re
from pathlib import Path

from bs4 import BeautifulSoup

CACHE_DIR = Path("cache")
PLAYERS_CSV = "players.csv"
OUT_CSV = "player_bio.csv"

_ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def cache_path(url: str) -> Path:
    return CACHE_DIR / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.html"


def _clean(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", "", text)        # drop [1] style refs
    return re.sub(r"\s+", " ", text).strip()


def extract_bio(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (position, dob) from the footballer infobox; '' if not found."""
    position = dob = ""
    for ib in soup.select("table.infobox"):
        for tr in ib.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            label = th.get_text(" ", strip=True).lower()
            if not position and "position" in label:           # "Position" / "Position(s)"
                # players often list several; keep the primary (first) one
                parts = [p.strip() for p in td.get_text("\n").split("\n") if p.strip()]
                position = _clean(parts[0])[:30] if parts else ""
            elif not dob and ("date of birth" in label or label == "born"):
                m = _ISO_DATE.search(td.get_text(" ", strip=True))
                if m:
                    dob = m.group(1)
        if position or dob:
            break
    return position, dob


def main(players_csv: str = PLAYERS_CSV, out_csv: str = OUT_CSV):
    rows = list(csv.DictReader(open(players_csv, newline="", encoding="utf-8")))
    out, missing, no_pos, no_dob = [], 0, 0, 0
    for r in rows:
        p = cache_path(r["WikiURL"])
        if not p.exists():
            missing += 1
            out.append({"Player": r["Player"], "Team": r["Nation"], "Position": "", "DOB": ""})
            continue
        pos, dob = extract_bio(BeautifulSoup(p.read_text(encoding="utf-8"), "lxml"))
        if not pos:
            no_pos += 1
        if not dob:
            no_dob += 1
        out.append({"Player": r["Player"], "Team": r["Nation"], "Position": pos, "DOB": dob})

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Player", "Team", "Position", "DOB"])
        w.writeheader()
        w.writerows(out)

    print(f"Wrote {out_csv}: {len(out)} players "
          f"({missing} missing from cache, {no_pos} without position, {no_dob} without DOB).")


if __name__ == "__main__":
    main()
