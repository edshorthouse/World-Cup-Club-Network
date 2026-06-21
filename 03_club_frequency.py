"""
club_frequency.py
=================
Reads clubs.csv and counts how many players have played for each club.
Deduplicates slugs that resolve to the same (Name, League) in club_details.csv
so that variant slugs for the same club (e.g. Manchester_City and
Manchester_City_F.C.) are merged into one count.

Output:
    club_frequency.csv  (Club, Name, League, Count) sorted by Count descending.
    'Club' is the canonical slug (first one seen for that Name+League pair).
"""
import csv
from collections import defaultdict


def load_details(path: str = "club_details.csv") -> dict[str, dict]:
    details = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            details[row["Slug"]] = row
    return details


def main(clubs_csv: str = "clubs.csv",
         details_csv: str = "club_details.csv",
         out_csv: str = "club_frequency.csv"):

    details = load_details(details_csv)

    # (name, league) -> {canonical_slug, player_set}
    groups: dict[tuple, dict] = {}

    with open(clubs_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            player = row["Player"]
            for key, value in row.items():
                if not (key.startswith("Club ") and value and value.strip()):
                    continue
                slug = value.strip()
                d = details.get(slug, {})
                name   = (d.get("Name")   or slug.replace("_", " ")).strip()
                league = (d.get("League") or "Unknown").strip()
                key_nl = (name, league)
                if key_nl not in groups:
                    groups[key_nl] = {"slug": slug, "players": set()}
                groups[key_nl]["players"].add(player)

    rows = [
        (g["slug"], name, league, len(g["players"]))
        for (name, league), g in groups.items()
    ]
    rows.sort(key=lambda r: -r[3])

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Club", "Name", "League", "Count"])
        for slug, name, league, count in rows:
            w.writerow([slug, name, league, count])

    print(f"Done. {len(rows)} unique clubs written to {out_csv}.")
    print("\nTop 20:")
    for slug, name, league, count in rows[:20]:
        print(f"  {count:>4}  {name}  ({league})")


if __name__ == "__main__":
    main()
