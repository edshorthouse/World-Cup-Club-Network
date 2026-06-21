"""
visualise_network.py
====================
Builds an interactive network graph of clubs sized by number of World Cup
players and grouped/coloured by league.

Reads:
    club_details.csv   (Slug, Name, League, LeagueSlug, Country)
    club_frequency.csv (Club, Count)

Output:
    club_network.html  — open in any browser, no server needed

Requirements:
    pip install pyvis
"""
import csv
from pathlib import Path
from pyvis.network import Network

# ── Config ────────────────────────────────────────────────────────────────────
MIN_PLAYERS   = 2    # only show clubs with at least this many players
NODE_SCALE    = 8    # multiplier: node size = count * NODE_SCALE
FONT_SIZE     = 14
OUTPUT        = "club_network.html"

# Colour palette — one per league (cycles if more leagues than colours)
PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#fffac8", "#800000", "#aaffc3",
    "#808000", "#ffd8b1", "#000075", "#a9a9a9", "#ffffff",
    "#ffe119", "#e6beff", "#fabebe", "#008080", "#e6e6e6",
]


def load_frequency(path: str = "club_frequency.csv") -> dict[str, int]:
    freq = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            freq[row["Club"]] = int(row["Count"])
    return freq


def load_details(path: str = "club_details.csv") -> dict[str, dict]:
    details = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            details[row["Slug"]] = row
    return details


def main():
    freq    = load_frequency()
    details = load_details()

    # Filter to clubs above threshold
    clubs = {
        slug: count
        for slug, count in freq.items()
        if count >= MIN_PLAYERS and slug in details
    }

    # Assign a colour per league
    leagues = sorted({details[s]["League"] for s in clubs if details[s]["League"]})
    league_colour = {
        league: PALETTE[i % len(PALETTE)]
        for i, league in enumerate(leagues)
    }

    print(f"Building network: {len(clubs)} clubs, {len(leagues)} leagues")

    net = Network(
        height="95vh",
        width="100%",
        bgcolor="#1a1a2e",
        font_color="white",
        notebook=False,
        directed=False,
    )
    net.barnes_hut(
        gravity=-8000,
        central_gravity=0.3,
        spring_length=200,
        spring_strength=0.05,
        damping=0.9,
    )

    # Add nodes
    for slug, count in clubs.items():
        d       = details[slug]
        name    = d["Name"] or slug.replace("_", " ")
        league  = d["League"] or "Unknown"
        country = d["Country"] or "Unknown"
        colour  = league_colour.get(league, "#888888")
        size    = count * NODE_SCALE

        title = (
            f"<b>{name}</b><br>"
            f"Players: {count}<br>"
            f"League: {league}<br>"
            f"Country: {country}"
        )
        net.add_node(
            slug,
            label=name,
            title=title,
            size=size,
            color=colour,
            font={"size": FONT_SIZE + count, "color": "white"},
        )

    # Add edges between clubs that share the same league
    # (creates visual clusters without needing a separate league node)
    league_clubs: dict[str, list[str]] = {}
    for slug in clubs:
        league = details[slug]["League"] or "Unknown"
        league_clubs.setdefault(league, []).append(slug)

    for league, members in league_clubs.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                net.add_edge(
                    members[i], members[j],
                    color={"color": league_colour.get(league, "#444444"), "opacity": 0.3},
                    width=0.5,
                )

    # Add a legend as a fixed HTML overlay via options
    legend_items = "".join(
        f'<div style="display:flex;align-items:center;margin:3px 0">'
        f'<div style="width:14px;height:14px;border-radius:50%;background:{colour};'
        f'margin-right:8px;flex-shrink:0"></div>'
        f'<span style="font-size:12px">{league}</span></div>'
        for league, colour in sorted(league_colour.items())
    )

    net.set_options("""
    {
      "interaction": {
        "hover": true,
        "tooltipDelay": 100,
        "navigationButtons": true,
        "keyboard": true
      },
      "physics": {
        "enabled": true
      }
    }
    """)

    net.save_graph(OUTPUT)

    # Inject legend into the saved HTML
    legend_html = f"""
    <div id="legend" style="
        position:fixed; top:10px; right:10px; background:rgba(0,0,0,0.75);
        color:white; padding:12px 16px; border-radius:8px;
        max-height:90vh; overflow-y:auto; z-index:9999;
        font-family:sans-serif; min-width:180px;">
      <b style="font-size:13px">Leagues</b>
      <div style="margin-top:6px">{legend_items}</div>
    </div>
    """

    html = Path(OUTPUT).read_text(encoding="utf-8")
    html = html.replace("</body>", legend_html + "\n</body>")
    Path(OUTPUT).write_text(html, encoding="utf-8")

    print(f"Saved to {OUTPUT} — open in your browser.")


if __name__ == "__main__":
    main()
