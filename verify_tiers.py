#!/usr/bin/env python3
"""
verify_tiers.py — independent cross-check of league tiers in league_levels.csv.

For each league it re-fetches the Wikipedia article and extracts the tier TWO
independent ways:
  (a) infobox  -> the `levels=` field  (what league_levels.py used)
  (b) prose    -> the lead sentence, e.g. "is the second tier/level/division of"
Then it flags every league where the CSV value disagrees with the prose, so the
real mistakes float to the top instead of being buried in heuristic noise.
"""
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://en.wikipedia.org/w/api.php"
UA  = "LeaguePyramidLevelBot/1.0 (tier audit; educational)"
BATCH = 20

WORD = {"top": 1, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
        "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
        "eleventh": 11, "twelfth": 12}
ORD = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7,
       "8th": 8, "9th": 9, "10th": 10}


def api_get(params, tries=6):
    url = API + "?" + urllib.parse.urlencode(params)
    delay = 2.0
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                ra = e.headers.get("Retry-After")
                time.sleep(float(ra) if (ra and ra.isdigit()) else delay)
                delay = min(delay * 2, 60); continue
            raise
        except (urllib.error.URLError, ConnectionResetError, TimeoutError):
            if k == tries - 1: raise
            time.sleep(delay); delay = min(delay * 2, 60)
    raise RuntimeError("API failed")


def fetch(titles):
    params = {"action": "query", "prop": "revisions", "rvprop": "content",
              "rvslots": "main", "redirects": 1, "format": "json",
              "formatversion": 2, "titles": "|".join(titles)}
    q = api_get(params).get("query", {})
    norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
    redir = {r["from"]: r["to"] for r in q.get("redirects", [])}
    pages = {p.get("title"): p for p in q.get("pages", [])}
    out = {}
    for t in titles:
        cur = norm.get(t, t)
        for _ in range(4):
            if cur in redir: cur = redir[cur]
            else: break
        pg = pages.get(cur)
        wt = ""
        if pg and not pg.get("missing"):
            try: wt = pg["revisions"][0]["slots"]["main"]["content"]
            except (KeyError, IndexError): wt = ""
        out[t] = wt
    return out


def infobox_level(wt):
    box = wt
    i = wt.lower().find("{{infobox football league")
    if i >= 0:
        box = wt[i:i + 4000]
    for key in ("levels", "level", "pyramid"):
        m = re.search(r"\|\s*" + key + r"\s*=\s*([^\n]+)", box, re.I)
        if m:
            raw = m.group(1)
            raw = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", raw)
            raw = re.sub(r"<[^>]+>", "", raw)
            num = re.search(r"\d+", raw)
            if num:
                return int(num.group(0))
    return None


def strip(wt):
    # remove templates (nested), refs, links, html -> rough plain text
    prev = None
    while prev != wt:
        prev = wt
        wt = re.sub(r"\{\{[^{}]*\}\}", " ", wt)
    wt = re.sub(r"<ref[^>]*>.*?</ref>", " ", wt, flags=re.S)
    wt = re.sub(r"<ref[^>]*/>", " ", wt)
    wt = re.sub(r"<[^>]+>", " ", wt)
    wt = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", wt)
    wt = re.sub(r"'''?", "", wt)
    wt = re.sub(r"\s+", " ", wt)
    return wt


def prose_tier(wt):
    """Tier stated in the lead, but ONLY when tied to the national pyramid
    ("... of the X football league system / pyramid / in general / overall").
    This ignores a league's own name ordinal ("Vierde Divisie") and a
    sub-organisation's "highest division of the English Football League"."""
    lead = strip(wt)[:1300]
    # ordinal/number (optionally "-highest") + tier word, then up to ~55 chars,
    # then a national-system phrase.
    pat = re.compile(
        r"\b(top|highest|first|second|third|fourth|fifth|sixth|seventh|eighth|"
        r"ninth|tenth|\d+(?:st|nd|rd|th))(?:[- ]highest)?[- ]"
        r"(?:tier|level|division|flight)\b(.{0,55})", re.I)
    SYS = re.compile(r"league system|football pyramid|\bin general\b|\boverall\b",
                     re.I)
    for m in pat.finditer(lead):
        if not SYS.search(m.group(2)):
            continue
        w = m.group(1).lower()
        if w in ("top", "highest"):
            return 1
        if w in WORD:
            return WORD[w]
        num = re.match(r"(\d+)", w)
        if num:
            return int(num.group(1))
    return None


def main():
    rows = list(csv.DictReader(open("league_levels.csv", encoding="utf-8")))
    # only audit Wikipedia-derived rows (skip hand-set manual ones)
    todo = [r for r in rows if r["Status"] in ("ok",)]
    titles = []
    for r in todo:
        t = urllib.parse.unquote(r["LeagueSlug"]) if r["LeagueSlug"] else r["WikipediaTitle"]
        r["_qt"] = t
        titles.append(t)

    print(f"Auditing {len(todo)} Wikipedia-derived tiers "
          f"({(len(titles)+BATCH-1)//BATCH} requests)...")
    wt = {}
    for i in range(0, len(titles), BATCH):
        wt.update(fetch(titles[i:i + BATCH]))
        if i + BATCH < len(titles):
            time.sleep(0.4)

    mismatches, no_prose = [], 0
    for r in todo:
        csv_lv = int(r["Level"]) if r["Level"] else None
        text = wt.get(r["_qt"], "")
        ib = infobox_level(text)
        pr = prose_tier(text)
        if pr is None:
            no_prose += 1
            continue
        if pr != csv_lv:
            mismatches.append((r["Country"], r["League"], csv_lv, ib, pr))

    print(f"\n{'='*74}\nTIER MISMATCHES (CSV level != lead-sentence tier): {len(mismatches)}\n{'='*74}")
    for co, lg, csv_lv, ib, pr in sorted(mismatches):
        print(f"  {co:18} {lg:34} CSV={csv_lv}  infobox={ib}  prose={pr}")
    print(f"\n(prose tier not found for {no_prose} leagues — not necessarily wrong)")


if __name__ == "__main__":
    main()
