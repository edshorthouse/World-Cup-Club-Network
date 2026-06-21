"""
load_neo4j.py
=============
Loads players.csv, clubs.csv, and club_details.csv into Neo4j.

Graph model:
  (Confederation)-[:CONTAINS]->(Nation)-[:ENTERED]->(Player)
  (Player)-[:PLAYED_FOR]->(Club)
  (Club)-[:COMPETES_IN]->(League)
  (League)-[:IN]->(Country)

Prerequisites:
  pip install neo4j
  Neo4j Desktop or Community Edition running locally (https://neo4j.com/download/)

Usage:
  1. Start Neo4j and create/start a database.
  2. Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD below (or leave defaults).
  3. Run: python load_neo4j.py
"""
import csv
from pathlib import Path
from neo4j import GraphDatabase

# ── Connection settings ────────────────────────────────────────────────────────
NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "88888888"   # change to your Neo4j password
# ──────────────────────────────────────────────────────────────────────────────

WIKI_BASE = "https://en.wikipedia.org/wiki/"


def load_club_details(path: str = "club_details.csv") -> dict:
    """Return slug -> {name, league, country} lookup."""
    details = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            details[row["Slug"]] = {
                "name":    row["Name"],
                "league":  row["League"],
                "country": row.get("Country", ""),
            }
    return details


def load_clubs_csv(path: str = "clubs.csv") -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_players_csv(path: str = "players.csv") -> dict:
    """Return player name -> WikiURL lookup."""
    urls = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            urls[row["Player"]] = row["WikiURL"]
    return urls


def clear_database(session):
    session.run("MATCH (n) DETACH DELETE n")
    print("Database cleared.")


def create_constraints(session):
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Confederation) REQUIRE c.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Nation)        REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Player)        REQUIRE p.wiki_url IS UNIQUE",
        # Club uniqueness: (name, league) pair — prevents merging distinct clubs
        # that share a name (e.g. Everton FC vs Everton de Viña del Mar) while
        # collapsing variant slugs for the same club into one node.
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Club)          REQUIRE (c.name, c.league) IS NODE KEY",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (l:League)        REQUIRE l.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country)       REQUIRE c.name IS UNIQUE",
    ]
    for c in constraints:
        session.run(c)
    print("Constraints created.")


def ingest(session, rows: list[dict], club_details: dict, player_urls: dict):
    total = len(rows)
    for i, row in enumerate(rows, 1):
        player_name   = row["Player"]
        nation_name   = row["Team"]
        confederation = row["Confederation"]
        wiki_url      = player_urls.get(player_name, "")

        # Collect club slugs from dynamic Club N columns
        club_slugs = [
            v for k, v in row.items()
            if k.startswith("Club ") and v and v.strip()
        ]

        # Merge Confederation → Nation → Player
        session.run("""
            MERGE (conf:Confederation {name: $conf})
            MERGE (nat:Nation {name: $nation})
              ON CREATE SET nat.confederation = $conf
            MERGE (conf)-[:CONTAINS]->(nat)
            MERGE (p:Player {wiki_url: $wiki_url})
              ON CREATE SET p.name = $player, p.wiki_url = $wiki_url
            MERGE (nat)-[:ENTERED]->(p)
        """, conf=confederation, nation=nation_name,
             player=player_name, wiki_url=wiki_url)

        # Merge Club → League → Country, and Player → Club.
        # Key on (name, league) so variant slugs for the same club
        # (e.g. Manchester_City / Manchester_City_F.C.) collapse to one node.
        for slug in club_slugs:
            d       = club_details.get(slug, {})
            c_name  = (d.get("name")  or slug.replace("_", " ")).strip()
            league  = (d.get("league",  "") or "Unknown").strip()
            country = (d.get("country", "") or "Unknown").strip()
            c_url   = WIKI_BASE + slug

            session.run("""
                MERGE (club:Club {name: $name, league: $league})
                  ON CREATE SET club.slug     = $slug,
                                club.wiki_url = $url,
                                club.country  = $country
                MERGE (country:Country {name: $country})
                MERGE (lg:League {name: $league})
                MERGE (lg)-[:IN]->(country)
                MERGE (club)-[:COMPETES_IN]->(lg)
                MERGE (p:Player {wiki_url: $wiki_url})
                MERGE (p)-[:PLAYED_FOR]->(club)
            """, slug=slug, name=c_name, url=c_url,
                 country=country, league=league, wiki_url=wiki_url)

        if i % 100 == 0 or i == total:
            print(f"  [{i}/{total}] {player_name}")


def main():
    print("Loading CSVs...")
    club_details = load_club_details()
    rows         = load_clubs_csv()
    player_urls  = load_players_csv()

    print(f"  {len(rows)} players, {len(club_details)} clubs")
    print(f"Connecting to {NEO4J_URI}...")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        clear_database(session)
        create_constraints(session)
        print("Ingesting data...")
        ingest(session, rows, club_details, player_urls)

    # Post-load: calculate and store playerCount on every Club node
    with driver.session() as session:
        session.run("""
            MATCH (p:Player)-[:PLAYED_FOR]->(c:Club)
            WITH c, COUNT(DISTINCT p) AS cnt
            SET c.playerCount = cnt
        """)
        # Eviction of stale slug-keyed Club nodes from any previous load is
        # handled automatically by clear_database() at the start of each run.
        print("playerCount set on all Club nodes.")

    driver.close()
    print("\nDone. Open Neo4j Bloom and try:")
    print("  MATCH (p:Player)-[:PLAYED_FOR]->(c:Club)-[:COMPETES_IN]->(l:League)-[:IN]->(co:Country)")
    print("  RETURN p, c, l, co LIMIT 50")


if __name__ == "__main__":
    main()
