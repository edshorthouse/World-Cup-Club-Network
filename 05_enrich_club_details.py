"""
enrich_club_details.py
======================
Populates the League and Country columns in club_details.csv.

Stages:
  1. Infobox league labels  — existing approach, broad label matching
  2. Wikipedia categories   — parses "Category: X clubs" from the club page
  3. Parent club fallback   — for reserve/youth teams, inherits parent's league
  4. League → country       — fetches each league's Wikipedia page for country

Output: overwrites club_details.csv in place.
Pages are cached in ./cache/ with a 45-day TTL.
"""
import csv
import hashlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "WorldCupClubCheck/1.0 (personal research; contact: your-email@example.com)"
}
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_MAX_AGE_SECONDS = 86400 * 45  # 45 days
SLEEP_SECONDS = 1.0
WIKI_BASE = "https://en.wikipedia.org/wiki/"

LEAGUE_LABELS  = {"league", "current league", "division", "competition",
                  "current division", "top division"}
COUNTRY_LABELS = {"country", "nation", "affiliated", "association",
                  "member associations"}
PARENT_LABELS  = {"reserve team of", "parent club", "affiliated to",
                  "affiliate", "owned by"}

# Direct club slug → (league_name, league_slug) overrides for clubs that
# can't be resolved automatically (defunct, stubs, academy pages, etc.)
_CLUB_LEAGUE_OVERRIDES: dict[str, tuple[str, str]] = {
    # Mexican clubs (defunct)
    "Lobos_BUAP":                        ("Liga MX", "Liga_MX"),
    "Mazatl%C3%A1n_F.C.":               ("Liga MX", "Liga_MX"),
    "San_Luis_F.C.":                     ("Liga MX", "Liga_MX"),
    # Israeli
    "Maccabi_Haifa_F.C.":               ("Israeli Premier League", "Israeli_Premier_League"),
    "Beitar_Tel_Aviv_Bat_Yam_F.C.":     ("Israeli Premier League", "Israeli_Premier_League"),
    # Croatian
    "NK_Inter_Zapre%C5%A1i%C4%87":      ("Croatian Football League", "Croatian_Football_League"),
    "HNK_%C5%A0ibenik":                 ("Croatian Football League", "Croatian_Football_League"),
    # German reserves
    "VfL_Wolfsburg_II":                  ("Regionalliga Nord", "Regionalliga_Nord"),
    "RB_Leipzig_affiliated_teams#Reserve_team": ("Regionalliga Nordost", "Regionalliga_Nordost"),
    "RB_Leipzig_II":                     ("Regionalliga Nordost", "Regionalliga_Nordost"),
    # French academy
    "Paris_Saint-Germain_Academy":       ("Championnat National 3", "Championnat_National_3"),
    "Paris_Saint-Germain_B":             ("Championnat National 3", "Championnat_National_3"),
    "RC_Strasbourg_Alsace_Academy":      ("Championnat National 3", "Championnat_National_3"),
    # Iranian
    "Saba_Qom_F.C.":                     ("Persian Gulf Pro League", "Persian_Gulf_Pro_League"),
    "Padideh_Khorasan_FC":               ("Persian Gulf Pro League", "Persian_Gulf_Pro_League"),
    # Bosnian
    "FK_Krupa":                          ("Premier League of Bosnia and Herzegovina", "Premier_League_of_Bosnia_and_Herzegovina"),
    # Brazilian
    "Guaratinguet%C3%A1_Futebol":        ("Campeonato Paulista Série A2", "Campeonato_Paulista_S%C3%A9rie_A2"),
    "Pitua%C3%A7u_Futebol_Clube_Cajazeiras": ("Campeonato Brasileiro Série D", "Campeonato_Brasileiro_S%C3%A9rie_D"),
    # Bulgarian
    "FC_Tsarsko_Selo_Sofia":             ("First Professional Football League", "First_Professional_Football_League_(Bulgaria)"),
    # Spanish lower
    "AD_Ceuta_B":                        ("Segunda Federación", "Segunda_Federaci%C3%B3n"),
    "Torrellano_Illice_CF":              ("Tercera Federación", "Tercera_Federaci%C3%B3n"),
    # Turkish
    "Bucaspor":                          ("TFF 1. Lig", "TFF_1._Lig"),
    # American defunct
    "New_York_Cosmos_(2013%E2%80%932020)": ("North American Soccer League (2011–2017)", "North_American_Soccer_League_(2011%E2%80%932017)"),
    "Kitsap_Pumas":                      ("USL League Two", "USL_League_Two"),
    # Algerian
    "DRB_Tadjenanet":                    ("Algerian Ligue Professionnelle 1", "Algerian_Ligue_Professionnelle_1"),
    # Jordanian
    "Ittihad_Al-Zarqa":                  ("Jordanian Pro League", "Jordanian_Pro_League"),
    "Al-Salt":                           ("Jordanian Pro League", "Jordanian_Pro_League"),
    # Jordanian — That Ras is a town in Karak, Jordan (page categories: "Football
    # clubs in Jordan"); previously mis-assigned to the Yemeni Premier League.
    "That_Ras_SC":                       ("Jordanian Pro League", "Jordanian_Pro_League"),
    # Russian
    "FC_Khimki":                         ("Russian Premier League", "Russian_Premier_League"),
    # Venezuelan
    "Atl%C3%A9tico_Venezuela_C.F.":     ("Liga FUTVE", "Liga_FUTVE"),
    # Portuguese lower
    "B-SAD":                             ("Liga Portugal 2", "Liga_Portugal_2"),
    "G.D._Santa_Cruz_de_Alvarenga":      ("Portuguese District Championships", "Portuguese_District_Championships"),
    "A.C._Alcanenense":                  ("Portuguese District Championships", "Portuguese_District_Championships"),
    # Cypriot
    "Alki_Oroklini":                     ("Cypriot First Division", "Cypriot_First_Division"),
    # English lower
    "Buckingham_Town_F.C.":              ("Southern Football League", "Southern_Football_League"),
    # Norwegian
    "Nest-Sotra_Fotball":                ("Norwegian First Division", "Norwegian_First_Division"),
    "FK_Jerv_2":                         ("Norwegian Second Division", "Norwegian_Second_Division"),
    "Str%C3%B8msgodset_Toppfotball_2":   ("Norwegian Second Division", "Norwegian_Second_Division"),
    "Rosenborg_BK_2":                    ("Norwegian Second Division", "Norwegian_Second_Division"),
    "Bryne_FK_2":                        ("Norwegian Third Division", "Norwegian_Third_Division"),
    "Sandefjord_Fotball_2":              ("Norwegian Third Division", "Norwegian_Third_Division"),
    "FK_%C3%98rn_Horten_2":             ("Norwegian Third Division", "Norwegian_Third_Division"),
    # Unknown / stub pages — country derivable but no league data available
    "West_African_Football_Academy":     ("Ghana Premier League", "Ghana_Premier_League"),
    # Spanish — defunct Community of Madrid club (ground: Ciudad Real Madrid);
    # previously mis-assigned to Colombia's Categoría Primera A.
    "RSC_Internacional_FC":              ("Tercera Federación", "Tercera_Federaci%C3%B3n"),
    # Tunisian clubs with no league info on Wikipedia
    "Degache":                           ("Tunisian Ligue Professionnelle 2", "Tunisian_Ligue_Professionnelle_2"),
    "Tozeur":                            ("Tunisian Ligue Professionnelle 2", "Tunisian_Ligue_Professionnelle_2"),
    # Australian — Merrimac is on the Gold Coast, Queensland (page categories:
    # "Soccer clubs on the Gold Coast, Queensland"); previously mis-assigned to USA.
    "Merrimac_FC":                       ("Football Queensland Premier League", "Football_Queensland_Premier_League"),
    # South African
    "SuperSport_United_F.C.":            ("South African Premiership", "South_African_Premiership"),
    "Mpumalanga_Black_Aces_F.C.":        ("National First Division", "National_First_Division"),
    # Qatari — no league slug extracted
    "Al-Khor_SC":                        ("Qatar Stars League", "Qatar_Stars_League"),
    # Senegalese — no league slug extracted
    "Diambars_FC":                       ("Senegal Premier League", "Senegal_Premier_League"),
    # Haitian — wrong league extracted (CONCACAF cup ref)
    "Violette_AC":                       ("Ligue Haïtienne", "Ligue_Ha%C3%AFtienne"),
    # Russian defunct
    "FC_Anzhi_Makhachkala":              ("Russian Premier League", "Russian_Premier_League"),
    # Czech lower
    "HFK_T%C5%99eb%C3%AD%C4%8D":        ("Czech National Football League", "Czech_National_Football_League"),
    # Portuguese
    "Vit%C3%B3ria_F.C.":                 ("Liga Portugal 2", "Liga_Portugal_2"),
    "C.D._Cova_da_Piedade":              ("Liga Portugal 2", "Liga_Portugal_2"),
    # Australian
    "Mudgeeraba_S.C.":                   ("Football Queensland Premier League", "Football_Queensland_Premier_League"),
    # German defunct reserve
    "FSV_Frankfurt_II":                  ("Regionalliga Südwest", "Regionalliga_S%C3%BCdwest"),
    # New Zealand
    "Wellington_United":                 ("ASB Premiership", "ASB_Premiership"),
    "YoungHeart_Manawatu":               ("ASB Premiership", "ASB_Premiership"),
    "Wairarapa_United":                  ("ASB Premiership", "ASB_Premiership"),
    # Swedish — "None (2025)" means currently without a league
    "Dalkurd_FF":                        ("Allsvenskan", "Allsvenskan"),
    # Norwegian lower
    "Bergen_Nord_FK":                    ("Norwegian Third Division", "Norwegian_Third_Division"),
    "Namsos_IL":                         ("Norwegian Third Division", "Norwegian_Third_Division"),
    # Swiss lower — 2. Liga is Switzerland
    "FC_United_Z%C3%BCrich":            ("2. Liga Interregional", "2._Liga_Interregional"),
    # French regional
    "%C3%89vreux_FC_27":                 ("Championnat National 3", "Championnat_National_3"),
    # Jordanian lower
    "Mansheyat_Bani_Hasan":             ("Jordanian Pro League", "Jordanian_Pro_League"),
    # Uruguayan lower
    "El_Tanque_Sisley":                  ("Liga AUF Uruguaya", "Liga_AUF_Uruguaya"),
}

# Manual overrides for league slugs that can't be resolved automatically
_LEAGUE_COUNTRY_OVERRIDES = {
    "League_of_Hercegovina-Neretva_Canton":  "Bosnia and Herzegovina",
    "Paraguayan_Tercera_Divisi%C3%B3n":      "Paraguay",
    "Portuguese_District_Championships":     "Portugal",
    "S%C3%A3o_Vicente_Island_League":        "Cape Verde",
    "Santiago_Island_League_%28South%29":    "Cape Verde",
    "Santiago_Island_League_(South)":        "Cape Verde",
    "Major_League_Soccer":                   "United States",
    "Yemeni_Premier_League":                 "Yemen",
    "Premier_Soccer_League":                 "South Africa",
    "CONCACAF_Champions_Cup–winning":        "Haiti",
}

# Known confederations/competitions that are NOT country names
_NOT_COUNTRIES = {
    "concacaf champions cup", "concacaf", "uefa", "fifa", "conmebol",
    "caf", "afc", "ofc", "concacaf champions league",
}

# Adjective/city/region → canonical country name
_NORMALISE = {
    "french":     "France",
    "croatian":   "Croatia",
    "portuguese": "Portugal",
    "spanish":    "Spain",
    "german":     "Germany",
    "italian":    "Italy",
    "dutch":      "Netherlands",
    "belgian":    "Belgium",
    "scottish":   "Scotland",
    "english":    "England",
    "beja":       "Portugal",
    "lisbon":     "Portugal",
    "madeira":    "Portugal",
    "setúbal":    "Portugal",
    "porto":      "Portugal",
}

# Categories whose names contain a league name followed by " clubs"
# We parse these dynamically, but skip generic non-league categories
_CATEGORY_SKIP = re.compile(
    r"(football clubs|association football|sportspeople|births|deaths|"
    r"living people|articles|wikipedia|pages|use |cs1 |cs2 |all |"
    r"webarchive|short description|good articles|featured)", re.IGNORECASE
)


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


def get_soup(slug: str) -> BeautifulSoup | None:
    base_slug = slug.split("#")[0]
    try:
        html = fetch(WIKI_BASE + base_slug)
        return BeautifulSoup(html, "lxml")
    except Exception:
        return None


def first_link_in_cell(td) -> tuple[str, str]:
    for a in td.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/wiki/") and ":" not in href:
            return a.get_text(strip=True), href[len("/wiki/"):]
    return "", ""


def cell_text(td) -> str:
    text = td.get_text(" ", strip=True).split("\n")[0]
    for noise in ("[note", "[1]", "[2]", "[3]", "[4]", "[5]", "[6]", "[7]",
                  "[8]", "[9]", "[ z", "[z", "*", "("):
        text = text.split(noise)[0]
    return text.strip()


def _normalise(name: str) -> str:
    return _NORMALISE.get(name.lower(), name)


# ── League extraction helpers ──────────────────────────────────────────────────

def league_from_infobox(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (league_name, league_slug) from infobox league fields."""
    for infobox in soup.select("table.infobox"):
        for tr in infobox.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            label = th.get_text(" ", strip=True).lower()
            if not any(l in label for l in LEAGUE_LABELS):
                continue
            name, slug = first_link_in_cell(td)
            if name:
                return name, slug
            return cell_text(td), ""
    return "", ""


def league_from_categories(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (league_name, league_slug) by parsing page categories.

    Football club pages carry categories like 'Premier League clubs' or
    'Ligue 1 clubs'. We find the first such category, strip ' clubs',
    and look up its Wikipedia slug via the category link href.
    """
    for a in soup.select("div#mw-normal-catlinks a, div.mw-normal-catlinks a"):
        text = a.get_text(strip=True)
        href = a.get("href", "")
        if not text.endswith(" clubs"):
            continue
        if _CATEGORY_SKIP.search(text):
            continue
        league_name = text[: -len(" clubs")].strip()
        # href looks like /wiki/Category:Premier_League_clubs
        # extract the article slug by searching Wikipedia for the league name
        league_slug = league_name.replace(" ", "_")
        return league_name, league_slug
    return "", ""


def parent_club_slug(soup: BeautifulSoup) -> str:
    """Return the Wikipedia slug of a parent/affiliate club if present."""
    for infobox in soup.select("table.infobox"):
        for tr in infobox.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            label = th.get_text(" ", strip=True).lower()
            if any(l in label for l in PARENT_LABELS):
                _, slug = first_link_in_cell(td)
                if slug:
                    return slug
    return ""


# ── Stage 1: fix missing leagues (all three methods) ──────────────────────────

def fix_league(club_slug: str) -> tuple[str, str]:
    """Try overrides, infobox labels, categories, then parent club inheritance."""

    # Method 0: hardcoded overrides
    if club_slug in _CLUB_LEAGUE_OVERRIDES:
        return _CLUB_LEAGUE_OVERRIDES[club_slug]

    soup = get_soup(club_slug)
    if not soup:
        return "", ""

    # Method A: infobox league fields
    name, slug = league_from_infobox(soup)
    if name:
        return name, slug

    # Method B: page categories ("X clubs")
    name, slug = league_from_categories(soup)
    if name:
        return name, slug

    # Method C: parent club — look up parent and inherit its league
    parent_slug = parent_club_slug(soup)
    if parent_slug:
        parent_soup = get_soup(parent_slug)
        if parent_soup:
            name, slug = league_from_infobox(parent_soup)
            if not name:
                name, slug = league_from_categories(parent_soup)
            if name:
                return name, slug

    return "", ""


# ── Stage 2: country from league ──────────────────────────────────────────────

def country_from_league_slug(league_slug: str) -> str:
    if not league_slug:
        return ""

    if league_slug in _LEAGUE_COUNTRY_OVERRIDES:
        return _LEAGUE_COUNTRY_OVERRIDES[league_slug]

    soup = get_soup(league_slug)
    if not soup:
        return ""

    h1 = soup.select_one("h1#firstHeading, h1.firstHeading")
    if h1 and "disambiguation" in h1.get_text().lower():
        return ""

    # Try infobox country fields
    for infobox in soup.select("table.infobox"):
        for tr in infobox.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            label = th.get_text(" ", strip=True).lower()
            if not any(l in label for l in COUNTRY_LABELS):
                continue
            name, _ = first_link_in_cell(td)
            if not name:
                name = cell_text(td)
            if not name or name.lower() in _NOT_COUNTRIES:
                continue
            return _normalise(name)

    # Fallback: derive from page title for association/system pages
    if h1:
        title = h1.get_text(strip=True)
        for suffix in (" Football Association", " football league system",
                       " Football League", " football league"):
            if title.endswith(suffix):
                return _normalise(title[: -len(suffix)].strip())

    return ""


# ── Main ──────────────────────────────────────────────────────────────────────

def main(csv_path: str = "club_details.csv"):
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        row.setdefault("LeagueSlug", "")
        row.setdefault("Country", "")

    total = len(rows)
    print(f"Stage 1: fixing missing leagues for {total} clubs...", file=sys.stderr)

    fixed = 0
    for row in rows:
        # Apply override if league is missing OR if we have a league name but
        # no slug (can't do country lookup without a slug)
        needs_fix = (
            not row["League"].strip()
            or not row["LeagueSlug"].strip()
        )
        if needs_fix:
            name, slug = fix_league(row["Slug"])
            if name:
                row["League"] = name
                row["LeagueSlug"] = slug
                fixed += 1
                print(f"  Fixed: {row['Name']} → {name}", file=sys.stderr)
    print(f"  Fixed {fixed} missing leagues.", file=sys.stderr)

    league_slugs = sorted({
        row["LeagueSlug"].strip()
        for row in rows
        if row["LeagueSlug"].strip()
    })
    print(f"\nStage 2: looking up countries for {len(league_slugs)} league slugs...",
          file=sys.stderr)

    league_country: dict[str, str] = {}
    for i, slug in enumerate(league_slugs, 1):
        country = country_from_league_slug(slug)
        league_country[slug] = country
        status = country if country else "NOT FOUND"
        print(f"  [{i}/{len(league_slugs)}] {slug} → {status}", file=sys.stderr)

    for row in rows:
        slug = row["LeagueSlug"].strip()
        if slug and league_country.get(slug):
            row["Country"] = league_country[slug]

    fieldnames = ["Slug", "Name", "League", "LeagueSlug", "Country"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    missing_league  = sum(1 for r in rows if not r["League"].strip())
    missing_country = sum(1 for r in rows if not r["Country"].strip())
    print(f"\nDone. {total} clubs written to {csv_path}.", file=sys.stderr)
    print(f"  Still missing league : {missing_league}", file=sys.stderr)
    print(f"  Still missing country: {missing_country}", file=sys.stderr)


if __name__ == "__main__":
    main()
