#!/usr/bin/env python3
"""
verify_players.py — verify the unique/deduplicated player count in the viz.

Three independent angles:
  1. VIZ      — extract `const RAW` from drill_down.html and count the distinct
                player names that actually appear in club rosters (this is what
                the visualisation can show you when you drill to club -> players).
  2. SOURCE   — count distinct players in clubs.csv (one row per player) and how
                many of them have at least one club that resolves into the viz.
  3. INTERNAL — recompute every confederation/country/league/club total from the
                leaf rosters by set-union and confirm it matches the stored
                totals, proving the de-duplication is internally consistent.
"""
import csv
import json
import re
from collections import defaultdict

HTML = "drill_down.html"
CLUBS = "clubs.csv"
DETAILS = "club_details.csv"


def load_raw():
    html = open(HTML, encoding="utf-8").read()
    # The page embeds three career-filter datasets; audit the "all" view.
    data = re.search(r"const DATA = (\{.*?\});\nlet RAW", html, re.S)
    if data:
        raw = json.loads(data.group(1))["all"]
    else:                                            # older single-RAW format
        raw = json.loads(re.search(r"const RAW = (\[.*?\]);\n", html, re.S).group(1))
    det = re.search(r"const PLAYER_DETAILS = (\{.*?\});\n", html, re.S)
    return raw, (json.loads(det.group(1)) if det else {})


def main():
    RAW, PLAYER_DETAILS = load_raw()

    # 1) VIZ: distinct players across all club rosters
    viz_players = set()
    club_count = league_count = 0
    for conf in RAW:
        for co in conf["countries"]:
            for lg in co["leagues"]:
                league_count += 1
                for cl in lg["clubs"]:
                    club_count += 1
                    for p in cl["players"]:
                        viz_players.add(p["n"])

    # 2) SOURCE: distinct players in clubs.csv and which resolve into the viz.
    # Each row is one player; same-named players are kept distinct by appending
    # the national team (mirrors build_drill_down.load_clubs_csv).
    club_cols = [f"Club {i}" for i in range(1, 19)]
    with open(CLUBS, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    name_counts = defaultdict(int)
    for r in rows:
        name_counts[r["Player"]] += 1
    player_career = {}
    used = defaultdict(int)
    for row in rows:
        name = row["Player"]; team = row.get("Team", "")
        if name_counts[name] > 1:
            key = f"{name} ({team})"
            if key in player_career:
                used[key] += 1
                key = f"{name} ({team} #{used[key] + 1})"
        else:
            key = name
        player_career[key] = [row[c].strip() for c in club_cols
                              if row.get(c) and row[c].strip()]
    src_players = set(player_career)
    resolvable_slugs = set()
    with open(DETAILS, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            resolvable_slugs.add(row["Slug"])
    # a player is representable if any career club has details
    representable = {n for n, career in player_career.items()
                     if any(s in resolvable_slugs for s in career)}

    # 3) INTERNAL: recompute level totals from leaf rosters
    mismatches = []
    grand_union = set()
    for conf in RAW:
        conf_set = set()
        for co in conf["countries"]:
            co_set = set()
            for lg in co["leagues"]:
                lg_set = set()
                for cl in lg["clubs"]:
                    names = {p["n"] for p in cl["players"]}
                    if len(names) != cl["count"]:
                        mismatches.append(f"club {cl['name']}: stored {cl['count']} != {len(names)}")
                    lg_set |= names
                if len(lg_set) != lg["totalPlayers"]:
                    mismatches.append(f"league {lg['name']}: stored {lg['totalPlayers']} != {len(lg_set)}")
                co_set |= lg_set
            if len(co_set) != co["totalPlayers"]:
                mismatches.append(f"country {co['country']}: stored {co['totalPlayers']} != {len(co_set)}")
            conf_set |= co_set
        if len(conf_set) != conf["totalPlayers"]:
            mismatches.append(f"conf {conf['confederation']}: stored {conf['totalPlayers']} != {len(conf_set)}")
        grand_union |= conf_set

    # 4) PROFILE INTEGRITY: every player shown at a club must have that club in
    #    their OWN career, and every name must map to exactly one profile. This
    #    is what catches a profile attached to the wrong same-named player.
    career_clubs = {k: {c["name"] for c in v.get("career", [])}
                    for k, v in PLAYER_DETAILS.items()}
    no_detail, wrong_profile = [], []
    for conf in RAW:
        for co in conf["countries"]:
            for lg in co["leagues"]:
                for cl in lg["clubs"]:
                    for p in cl["players"]:
                        key = p["n"]
                        if key not in PLAYER_DETAILS:
                            no_detail.append((cl["name"], key))
                        elif cl["name"] not in career_clubs[key]:
                            wrong_profile.append((cl["name"], key))
    # Same base-name players must each have a distinct profile key
    base_groups = defaultdict(set)
    for key in PLAYER_DETAILS:
        base = key.split(" (")[0]
        base_groups[base].add(key)
    shared_names = {b: ks for b, ks in base_groups.items() if len(ks) > 1}

    # ── Report ────────────────────────────────────────────────────────────
    print("=" * 64)
    print("UNIQUE / DE-DUPLICATED PLAYERS IN THE VISUALISATION")
    print("=" * 64)
    print(f"  Distinct players shown in club rosters : {len(viz_players)}")
    print(f"  Distinct players via set-union of tree : {len(grand_union)}")
    print(f"  PLAYER_DETAILS entries (career lookup) : {len(PLAYER_DETAILS)}")
    print(f"  Leagues / clubs in viz                 : {league_count} / {club_count}")
    print()
    print("CROSS-CHECK vs SOURCE (clubs.csv)")
    print(f"  Distinct players in clubs.csv          : {len(src_players)}")
    print(f"  ...representable (>=1 club resolves)    : {len(representable)}")
    not_shown = representable - viz_players
    extra = viz_players - src_players
    print(f"  Representable but NOT in viz           : {len(not_shown)}")
    if not_shown:
        for n in sorted(not_shown)[:10]:
            print(f"      - {n}")
    print(f"  In viz but NOT in source (should be 0) : {len(extra)}")
    print()
    print("INTERNAL DE-DUP CONSISTENCY (recomputed totals vs stored)")
    if not mismatches:
        print("  OK - all confederation/country/league/club totals match by set-union")
    else:
        print(f"  {len(mismatches)} mismatch(es):")
        for m in mismatches[:20]:
            print(f"      - {m}")
    print()
    print("PROFILE INTEGRITY (player shown at a club must have that club in their career)")
    if not wrong_profile and not no_detail:
        print("  OK - every roster entry resolves to a profile whose career includes that club")
    else:
        if no_detail:
            print(f"  {len(no_detail)} roster entries with NO profile:")
            for c, k in no_detail[:20]:
                print(f"      - {k}  @ {c}")
        if wrong_profile:
            print(f"  {len(wrong_profile)} WRONG-PROFILE entries (career doesn't include the club):")
            for c, k in wrong_profile[:20]:
                print(f"      - {k}  shown @ {c}, not in their career")
    print()
    print(f"SHARED-NAME PLAYERS (kept distinct): {len(shared_names)}")
    for base, ks in sorted(shared_names.items()):
        print(f"  '{base}' -> {sorted(ks)}")


if __name__ == "__main__":
    main()
