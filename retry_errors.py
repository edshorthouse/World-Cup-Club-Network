import csv
import sys
from check_everton import check_player

# Players that errored during the main run
retry = ["Nicolas Jackson"]

with open("players.csv", newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

targets = [r for r in rows if r["Player"] in retry]
print(f"Retrying {len(targets)} player(s)...")

results = []
for r in targets:
    try:
        hits = check_player(r["WikiURL"])
        if hits:
            for where, detail in hits:
                results.append([r["Nation"], r["Player"], r["WikiURL"], where, detail])
            print(f"HIT {r['Nation']:<20} {r['Player']} ({len(hits)} match{'es' if len(hits)!=1 else ''})")
        else:
            print(f"No hit: {r['Player']}")
    except Exception as e:
        print(f"ERROR {r['Player']}: {e}")

if results:
    # Append to everton_hits.csv
    with open("everton_hits.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(results)
    print(f"Appended {len(results)} row(s) to everton_hits.csv")
else:
    print("No new hits to append.")
