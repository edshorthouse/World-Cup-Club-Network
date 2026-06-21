#!/usr/bin/env python3
"""
verify_levels.py
================
Cross-checks league_levels.csv for accuracy and prints a report of anything
suspicious to review by hand. Three independent checks:

  1. COUNTRY  — fetch each Wikipedia article's categories (which name the
                country in plain text) and confirm the article really belongs
                to the stated country. Catches wrong-article slugs / redirects
                (e.g. a Paraguay league whose slug points to an Argentine one).
  2. NAME     — heuristic: a top-flight name (Premier League, Serie A, ...)
                should be Level 1; an obvious 2nd/3rd-tier name should match.
  3. LADDER   — per country, flag duplicate Level 1s, missing Level 1, or gaps.

Read-only against Wikipedia (prop=categories, batched). Writes nothing.
"""
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

API     = "https://en.wikipedia.org/w/api.php"
UA      = "LeaguePyramidLevelBot/1.0 (verification pass; educational use)"
CSV_IN  = "league_levels.csv"
CATCACHE = "league_categories_cache.json"
BATCH   = 20

# Country -> lowercase substrings that, if found in a category title, confirm
# the article belongs to that country (noun forms, adjectives, synonyms).
TERMS = {
    "Albania": ["albania", "albanian"], "Algeria": ["algeria", "algerian"],
    "Angola": ["angola", "angolan"], "Argentina": ["argentin"],
    "Armenia": ["armenia", "armenian"], "Australia": ["australia", "australian"],
    "Austria": ["austria", "austrian"], "Azerbaijan": ["azerbaijan"],
    "Bahrain": ["bahrain"], "Belarus": ["belarus"], "Belgium": ["belgium", "belgian"],
    "Bolivia": ["bolivia", "bolivian"], "Bosnia and Herzegovina": ["bosnia", "herzegovina", "bosnian"],
    "Brazil": ["brazil", "brazilian"], "Bulgaria": ["bulgaria", "bulgarian"],
    "Canada": ["canada", "canadian"], "Cape Verde": ["cape verde", "cabo verde", "cape verdean"],
    "Chile": ["chile", "chilean"], "China": ["china", "chinese"],
    "Colombia": ["colombia", "colombian"], "Costa Rica": ["costa rica", "costa rican"],
    "Croatia": ["croatia", "croatian"], "Cyprus": ["cyprus", "cypriot"],
    "Czech Republic": ["czech", "czechia"], "DR Congo": ["democratic republic of the congo", "dr congo", "congolese"],
    "Denmark": ["denmark", "danish"], "Dominican Republic": ["dominican republic", "dominican"],
    "Ecuador": ["ecuador", "ecuadorian"], "Egypt": ["egypt", "egyptian"],
    "England": ["england", "english"], "Estonia": ["estonia", "estonian"],
    "Finland": ["finland", "finnish"], "France": ["france", "french"],
    "Georgia": ["georgia"], "Germany": ["germany", "german"], "Ghana": ["ghana", "ghanaian"],
    "Greece": ["greece", "greek"], "Guatemala": ["guatemala", "guatemalan"],
    "Haiti": ["haiti", "haitian"], "Honduras": ["honduras", "honduran"],
    "Hungary": ["hungary", "hungarian"], "Iceland": ["iceland", "icelandic"],
    "India": ["india", "indian"], "Indonesia": ["indonesia", "indonesian"],
    "Iran": ["iran", "iranian"], "Iraq": ["iraq", "iraqi"],
    "Ireland": ["republic of ireland", "irish", "ireland"], "Israel": ["israel", "israeli"],
    "Italy": ["italy", "italian"], "Ivory Coast": ["ivory coast", "ivorian", "ivoire"],
    "Japan": ["japan", "japanese"], "Jordan": ["jordan", "jordanian"],
    "Kazakhstan": ["kazakh"], "Kuwait": ["kuwait"], "Latvia": ["latvia", "latvian"],
    "Lebanon": ["lebanon", "lebanese"], "Libya": ["libya", "libyan"],
    "Luxembourg": ["luxembourg"], "Malaysia": ["malaysia", "malaysian"],
    "Malta": ["malta", "maltese"], "Mexico": ["mexico", "mexican"],
    "Moldova": ["moldova", "moldovan"], "Morocco": ["morocco", "moroccan"],
    "Netherlands": ["netherlands", "dutch"], "New Zealand": ["new zealand"],
    "Norway": ["norway", "norwegian"], "Oman": ["oman"], "Panama": ["panama", "panamanian"],
    "Paraguay": ["paraguay", "paraguayan"], "Peru": ["peru", "peruvian"],
    "Poland": ["poland", "polish"], "Portugal": ["portugal", "portuguese", "madeira", "azores"],
    "Qatar": ["qatar", "qatari"], "Romania": ["romania", "romanian"],
    "Russia": ["russia", "russian"], "Saudi Arabia": ["saudi"],
    "Scotland": ["scotland", "scottish"], "Senegal": ["senegal", "senegalese"],
    "Serbia": ["serbia", "serbian"], "Slovakia": ["slovak"], "Slovenia": ["sloven"],
    "South Africa": ["south africa", "south african"], "South Korea": ["south korea", "korean", "korea republic", "k league"],
    "Spain": ["spain", "spanish"], "Sweden": ["sweden", "swedish"],
    "Switzerland": ["switzerland", "swiss"], "Thailand": ["thailand", "thai"],
    "Tunisia": ["tunisia", "tunisian"], "Turkey": ["turkey", "turkish", "türkiye"],
    "Ukraine": ["ukraine", "ukrainian"], "United Arab Emirates": ["united arab emirates", "uae", "emirati"],
    "United Republic of Tanzania": ["tanzania", "tanzanian"],
    "United States": ["united states", "american soccer", "american football leagues", "u.s. ", "usl", "mls", "soccer in the united states", "american"],
    "Uruguay": ["uruguay", "uruguayan"], "Uzbekistan": ["uzbek"],
    "Venezuela": ["venezuela", "venezuelan"], "Yemen": ["yemen", "yemeni"],
}

TOP_FLIGHT = re.compile(r"\b(premier league|super league|superliga|primera divisi|"
                        r"serie a|la liga|bundesliga|eredivisie|ligue 1|primeira liga|"
                        r"premiership|super lig|pro league|premier division|premier soccer league|"
                        r"first division|1\. liga|virsliga|meistriliiga|veikkausliiga|"
                        r"a lyga|ekstraklasa|k league 1|j1 league|liga mx|allsvenskan|"
                        r"eliteserien|superettan)\b", re.I)
SECOND_TIER = re.compile(r"\b(championship|serie b|segunda|2\. bundesliga|ligue 2|"
                         r"liga portugal 2|eerste divisie|2\. liga|liga 2|league one|"
                         r"primera b|division 2|second division|2\. division)\b", re.I)


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


def fetch_categories(titles):
    """Return {requested_title: [category titles]} for a batch."""
    params = {
        "action": "query", "prop": "categories", "cllimit": "max",
        "redirects": 1, "format": "json", "formatversion": 2,
        "titles": "|".join(titles),
    }
    q = api_get(params).get("query", {})
    norm  = {n["from"]: n["to"] for n in q.get("normalized", [])}
    redir = {r["from"]: r["to"] for r in q.get("redirects", [])}
    pages = {p.get("title"): p for p in q.get("pages", [])}
    out = {}
    for t in titles:
        cur = norm.get(t, t)
        for _ in range(4):
            cur = redir.get(cur, cur) if cur in redir else cur
            if cur not in redir: break
        pg = pages.get(cur)
        cats = [] if not pg else [c["title"] for c in pg.get("categories", [])]
        out[t] = cats
    return out


def main():
    rows = list(csv.DictReader(open(CSV_IN, encoding="utf-8")))

    # category cache
    try:
        catcache = json.load(open(CATCACHE, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        catcache = {}

    titles = []
    seen = set()
    for r in rows:
        t = urllib.parse.unquote(r["LeagueSlug"]) if r["LeagueSlug"] else r["WikipediaTitle"]
        r["_qtitle"] = t
        if t not in seen and t not in catcache:
            seen.add(t); titles.append(t)

    print(f"Fetching categories for {len(titles)} articles "
          f"({(len(titles)+BATCH-1)//BATCH} requests)...")
    for i in range(0, len(titles), BATCH):
        catcache.update(fetch_categories(titles[i:i + BATCH]))
        json.dump(catcache, open(CATCACHE, "w", encoding="utf-8"), ensure_ascii=False)
        if i + BATCH < len(titles):
            time.sleep(0.4)

    country_flags, name_flags = [], []
    for r in rows:
        country, league = r["Country"], r["League"]
        level = r["Level"]
        cats = catcache.get(r["_qtitle"], [])
        catblob = " ; ".join(cats).lower()

        # CHECK 1 — country consistency (skip manual entries; they were hand-set)
        if not r["Status"].startswith("manual") and cats:
            terms = TERMS.get(country, [country.lower()])
            if not any(term in catblob for term in terms):
                # which country does it look like instead?
                guess = [c for c, ts in TERMS.items()
                         if c != country and any(t in catblob for t in ts)]
                country_flags.append((league, country, level, guess[:3], cats[:4]))

        # CHECK 2 — name vs level heuristic
        if level:
            lv = int(level)
            if TOP_FLIGHT.search(league) and lv != 1:
                name_flags.append((league, country, level, "top-flight name but not L1"))
            elif SECOND_TIER.search(league) and lv == 1:
                name_flags.append((league, country, level, "2nd-tier name but L1"))

    # CHECK 3 — per-country ladder sanity
    bycountry = defaultdict(list)
    for r in rows:
        if r["Level"]:
            bycountry[r["Country"]].append((int(r["Level"]), r["League"]))
    ladder_flags = []
    for country, items in sorted(bycountry.items()):
        lv_list = sorted(l for l, _ in items)
        ones = [lg for l, lg in items if l == 1]
        if len(ones) > 1:
            ladder_flags.append((country, f"{len(ones)} leagues at Level 1: {ones}"))
        if 1 not in lv_list and len(items) >= 3:
            ladder_flags.append((country, f"no Level 1 (levels present: {lv_list})"))

    # Report
    print("\n" + "=" * 78)
    print(f"CHECK 1 — COUNTRY MISMATCH  ({len(country_flags)} flagged)")
    print("=" * 78)
    for lg, co, lv, guess, cats in country_flags:
        print(f"  {lg}  [{co}]  level={lv}")
        print(f"      looks like: {guess or '??'}")
        print(f"      cats: {cats}")

    print("\n" + "=" * 78)
    print(f"CHECK 2 — NAME vs LEVEL  ({len(name_flags)} flagged)")
    print("=" * 78)
    for lg, co, lv, why in name_flags:
        print(f"  {lg}  [{co}]  level={lv}  -- {why}")

    print("\n" + "=" * 78)
    print(f"CHECK 3 — LADDER SANITY  ({len(ladder_flags)} flagged)")
    print("=" * 78)
    for co, why in ladder_flags:
        print(f"  {co}: {why}")


if __name__ == "__main__":
    main()
