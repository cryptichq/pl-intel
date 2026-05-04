"""
Final fix for player team assignments
Uses team NAMES not IDs to match FPL to our DB
Run: python fixplayers_final.py
"""
import sqlite3
import requests

DB_PATH = "premier_league.db"
FPL_API = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_POSITIONS = {1:"GK", 2:"DEF", 3:"MID", 4:"FWD"}

# Map FPL team NAME -> our DB team NAME
FPL_NAME_TO_DB = {
    "Arsenal":          "Arsenal",
    "Aston Villa":      "Aston Villa",
    "Bournemouth":      "Bournemouth",
    "Brentford":        "Brentford",
    "Brighton":         "Brighton",
    "Burnley":          "Burnley",
    "Chelsea":          "Chelsea",
    "Crystal Palace":   "Crystal Palace",
    "Everton":          "Everton",
    "Fulham":           "Fulham",
    "Leeds":            "Leeds",
    "Liverpool":        "Liverpool",
    "Man City":         "Man City",
    "Man Utd":          "Man United",
    "Newcastle":        "Newcastle",
    "Nott'm Forest":    "Nottingham Forest",
    "Spurs":            "Tottenham",
    "Sunderland":       "Sunderland",
    "West Ham":         "West Ham",
    "Wolves":           "Wolves",
}

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys = OFF")

# Fetch FPL data
print("Fetching FPL API...", end=" ", flush=True)
resp     = requests.get(FPL_API, headers={"User-Agent":"Mozilla/5.0"}, timeout=20)
data     = resp.json()
fpl_teams= {t["id"]: t["name"] for t in data.get("teams",[])}
players  = data.get("elements",[])
print(f"{len(players)} players")

# Build lookup: DB team name -> DB team ID
db_team_ids = {}
for row in conn.execute("SELECT id, name FROM teams").fetchall():
    db_team_ids[row[1]] = row[0]

print("\nFPL->DB team mapping:")
for fpl_id, fpl_name in sorted(fpl_teams.items()):
    db_name = FPL_NAME_TO_DB.get(fpl_name, "NOT MAPPED")
    db_id   = db_team_ids.get(db_name, "NOT FOUND")
    print(f"  FPL {fpl_id:>2} {fpl_name:<20} -> DB {str(db_id):>3} {db_name}")

# Rebuild player tables cleanly
print("\nRebuilding player tables...")
conn.executescript("""
    DROP TABLE IF EXISTS player_predictions;
    DROP TABLE IF EXISTS player_season_stats;
    DROP TABLE IF EXISTS players;

    CREATE TABLE players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        team_name TEXT,
        team_id INTEGER,
        fpl_team_name TEXT,
        position TEXT,
        fpl_id INTEGER UNIQUE,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE player_season_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER REFERENCES players(id),
        season_label TEXT,
        team_name TEXT,
        position TEXT,
        appearances INTEGER DEFAULT 0,
        minutes INTEGER DEFAULT 0,
        goals INTEGER DEFAULT 0,
        assists INTEGER DEFAULT 0,
        goals_per90 REAL DEFAULT 0,
        assists_per90 REAL DEFAULT 0,
        shots_per90 REAL DEFAULT 0,
        yellow_cards INTEGER DEFAULT 0,
        red_cards INTEGER DEFAULT 0,
        yellows_per90 REAL DEFAULT 0,
        xg REAL DEFAULT 0,
        xa REAL DEFAULT 0,
        xg_per90 REAL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(player_id, season_label)
    );

    CREATE TABLE player_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        player_id INTEGER,
        player_name TEXT,
        team_name TEXT,
        position TEXT,
        score_prob REAL DEFAULT 0,
        assist_prob REAL DEFAULT 0,
        yellow_prob REAL DEFAULT 0,
        predicted_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(match_id, player_id)
    );
""")
conn.commit()

saved = 0
skipped = 0
for p in players:
    mins = int(p.get("minutes", 0))
    if mins < 1200:
        skipped += 1
        continue

    first        = p.get("first_name",  "").strip()
    last         = p.get("second_name", "").strip()
    name         = f"{first} {last}".strip()
    fpl_id       = p.get("id")
    fpl_team_id  = p.get("team")
    fpl_team_name= fpl_teams.get(fpl_team_id, "Unknown")

    # Use NAME-based mapping — this is the key fix
    db_team_name = FPL_NAME_TO_DB.get(fpl_team_name, fpl_team_name)
    db_team_id   = db_team_ids.get(db_team_name)

    position = FPL_POSITIONS.get(p.get("element_type", 3), "MID")
    goals    = int(p.get("goals_scored", 0))
    assists  = int(p.get("assists",      0))
    yellows  = int(p.get("yellow_cards", 0))
    reds     = int(p.get("red_cards",    0))
    starts   = int(p.get("starts",       0))
    apps     = starts if starts > 0 else max(mins//70, 1)
    xg       = float(p.get("expected_goals",  0) or 0)
    xa       = float(p.get("expected_assists", 0) or 0)

    mins90   = max(mins/90, 0.1)
    g90      = round(goals   / mins90, 3)
    a90      = round(assists / mins90, 3)
    y90      = round(yellows / mins90, 3)
    xg90     = round(xg      / mins90, 3)
    sh90     = round(goals * 3.5 / mins90, 3)

    try:
        conn.execute("""
            INSERT OR IGNORE INTO players
            (name, team_name, team_id, fpl_team_name, position, fpl_id)
            VALUES (?,?,?,?,?,?)
        """, (name, db_team_name, db_team_id, fpl_team_name, position, fpl_id))

        pid = conn.execute(
            "SELECT id FROM players WHERE fpl_id=?", (fpl_id,)
        ).fetchone()
        if not pid: continue

        conn.execute("""
            INSERT OR REPLACE INTO player_season_stats (
                player_id, season_label, team_name, position,
                appearances, minutes, goals, assists,
                goals_per90, assists_per90, shots_per90,
                yellow_cards, red_cards, yellows_per90,
                xg, xa, xg_per90
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pid[0], "2025/2026", db_team_name, position,
            apps, mins, goals, assists,
            g90, a90, sh90,
            yellows, reds, y90,
            round(xg,3), round(xa,3), xg90
        ))
        saved += 1
    except Exception as e:
        continue

conn.commit()
print(f"\nSaved {saved} players")

# Verify Man City and Man United
print("\nVerification:")
for team_name in ["Man City", "Man United", "Liverpool", "Arsenal"]:
    db_id = db_team_ids.get(team_name)
    players_in_team = conn.execute("""
        SELECT p.name, pss.goals, pss.minutes
        FROM players p
        JOIN player_season_stats pss ON pss.player_id = p.id
        WHERE p.team_id=?
        ORDER BY pss.goals DESC LIMIT 4
    """, (db_id,)).fetchall()
    print(f"\n  {team_name} (DB ID {db_id}):")
    for r in players_in_team:
        print(f"    {r[0]:<30} G:{r[1]:>3} Mins:{r[2]:>5}")

conn.close()
print("\nDone! Now run:")
print("  python playerstats.py --predict")
print("  python site.py")
input("\nPress Enter to close...")
