"""
refresh.py — one command to rebuild the visualisation
=====================================================
Runs the numbered pipeline (01 → 08) in order so you don't have to invoke
nine scripts by hand. Each step's output feeds the next, so the order is
fixed; this just chains them and stops at the first real failure.

Usage (from the project root, e.g. PyCharm's Terminal):

    python refresh.py                # full refresh: scrape + rebuild the HTML
    python refresh.py --build-only   # only step 08 (rebuild HTML from existing CSVs)
    python refresh.py --from 4       # resume from step 04 (e.g. after a network drop)

After it finishes, publish with:

    git add -A && git commit -m "Refresh data" && git push

GitHub Pages then redeploys index.html automatically.

Notes
-----
* Uses the SAME interpreter you launched it with (sys.executable), so it
  respects your virtualenv.
* The player-bio step is optional — the build degrades gracefully without it,
  so a failure there is reported as a warning and does NOT stop the run.
* Step 02 caches player pages for 1 day; the first refresh after a few days
  re-fetches ~1,250 pages (~20 min). Re-runs are fast (everything is cached
  under ./cache/).
"""

import argparse
import subprocess
import sys
import time

# (step number, script, human description, optional?) — run in this exact order.
STEPS = [
    (1, "01_extract_players.py",     "squads        -> players.csv",                       False),
    (2, "02_extract_clubs.py",       "career clubs  -> clubs.csv, club_spells.csv",        False),
    (3, "03_club_frequency.py",      "club counts   -> club_frequency.csv",                False),
    (4, "04_lookup_clubs.py",        "name/league   -> club_details.csv",                  False),
    (5, "05_enrich_club_details.py", "league+country-> club_details.csv",                  False),
    (6, "06_league_levels.py",       "pyramid tiers -> league_levels.csv",                 False),
    (7, "07_detect_dissolved.py",    "defunct clubs -> dissolved_clubs.json",              False),
    (8, "extract_player_bio.py",     "position+DOB  -> player_bio.csv (optional)",         True),
    (9, "08_build_drill_down.py",    "the viz       -> drill_down.html + index.html",      False),
]


def fmt_secs(s):
    """Compact 'm s' / 's' duration for the per-step + total timings."""
    s = int(round(s))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def run_step(num, script, desc, optional):
    """Run one script as its own process (exactly like running it by hand).
    Returns True on success. An optional step that fails returns True (warn only)."""
    label = "08_build_drill_down.py" if script == "08_build_drill_down.py" else script
    print(f"\n=== Step {num:>2} · {label} — {desc} ===", flush=True)
    t0 = time.time()
    result = subprocess.run([sys.executable, script])
    dt = fmt_secs(time.time() - t0)

    if result.returncode == 0:
        print(f"--- ok ({dt})", flush=True)
        return True
    if optional:
        print(f"--- WARNING: optional step failed (exit {result.returncode}, {dt}) — "
              f"continuing; the build degrades gracefully without it.", flush=True)
        return True
    print(f"--- FAILED (exit {result.returncode}, {dt})", flush=True)
    return False


def main():
    ap = argparse.ArgumentParser(description="Rebuild the World Cup club-network visualisation.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--build-only", action="store_true",
                   help="run only step 08 (rebuild the HTML from existing CSVs)")
    g.add_argument("--from", dest="from_step", type=int, metavar="N",
                   help="resume from step N (1-9); earlier steps are skipped")
    args = ap.parse_args()

    if args.build_only:
        steps = [s for s in STEPS if s[1] == "08_build_drill_down.py"]
    elif args.from_step is not None:
        steps = [s for s in STEPS if s[0] >= args.from_step]
        if not steps:
            ap.error(f"--from must be between 1 and {STEPS[-1][0]}")
    else:
        steps = STEPS

    print(f"Refreshing the viz: {len(steps)} step(s) with {sys.executable}")
    t0 = time.time()
    for num, script, desc, optional in steps:
        if not run_step(num, script, desc, optional):
            print(f"\nStopped at step {num}. Fix the error above and re-run, "
                  f"e.g. `python refresh.py --from {num}`.", flush=True)
            return 1

    print(f"\nDone in {fmt_secs(time.time() - t0)}. Wrote drill_down.html + index.html.")
    print("Publish with:  git add -A && git commit -m \"Refresh data\" && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
