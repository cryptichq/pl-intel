"""
Enhanced Premier League Data Downloader
========================================
Downloads match stats from football-data.co.uk (free):
  - Shots, shots on target (home & away)
  - Corners (home & away)
  - Yellow & red cards (home & away)
  - Fouls (home & away)

Player-level stats (scorers, assists, cards) via football-data.org API.

Run: python download_stats.py
"""

import requests
import sqlite3
import csv
import io
import os
import time
from datetime import datetime

DB_PATH = "premier_league.db"
API_KEY = open("api_key.txt").read().strip() if os.path.exists("api_key.txt") else os.getenv("FOOTBALL_DATA_API_KEY", "")
BASE_URL = "https://api.football-data.org/v4"
HEADERS  = {"X-Auth-Token": API_KEY}

SEASONS = {
    2000:"0001",2001:"0102",2002:"0203",2003:"0304",
    2004:"0405",2005:"0506",2006:"0607",2007:"0708",
    2008:"0809",2009:"0910",2010:"1011",2011:"1112",
    2012:"1213",2013:"1314",2014:"1415",2015:"1516",
    2016:"1617",2017:"1718",2018:"1819",2019:"1920",
    2020:"2021",2021:"2122",2022:"2223",2023:"2324",
}

CSV_URL = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"


def init_extra_tables(conn):
    """Add new tables for extended stats."""
    conn.executescript("""
        -- Per-match team stats (shots, corners, cards)
        CREATE TABLE IF NOT EXISTS match_stats (
            match_id INTEGER PRIMARY KEY REFERENCES matches(id),
            home_shots INTEGER,
            away_shots INTEGER,
            home_shots_on_target INTEGER,
            away_shots_on_target INTEGER,
            home_corners INTEGER,
            away_corners INTEGER,
            home_fouls INTEGER,
            away_fouls INTEGER,
            home_yellow_cards INTEGER,
            away_yellow_cards INTEGER,
            home_red_cards INTEGER,
            away_red_cards INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Players
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY,
            name TEXT,
            nationality TEXT,
            position TEXT,
            team_id INTEGER REFERENCES teams(id),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Player match events (goals, assists, cards)
        CREATE TABLE IF NOT EXISTS player_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER REFERENCES matches(id),
            player_id INTEGER REFERENCES players(id),
            player_name TEXT,
            team_id INTEGER REFERENCES teams(id),
            event_type TEXT,   -- GOAL, ASSIST, YELLOW_CARD, RED_CARD, SUBSTITUTION
            minute INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(match_id, player_id, event_type, minute)
        );

        -- Player season aggregates (for NN features)
        CREATE TABLE IF NOT EXISTS player_season_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER REFERENCES players(id),
            player_name TEXT,
            team_id INTEGER REFERENCES teams(id),
            season_id INTEGER REFERENCES seasons(id),
            appearances INTEGER DEFAULT 0,
            goals INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            yellow_cards INTEGER DEFAULT 0,
            red_cards INTEGER DEFAULT 0,
            goals_per_game REAL DEFAULT 0,
            assists_per_game REAL DEFAULT 0,
            cards_per_game REAL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(player_id, season_id)
        );

        -- Extended match features (adds stats to existing match_features)
        CREATE TABLE IF NOT EXISTS match_features_extended (
            match_id INTEGER PRIMARY KEY REFERENCES matches(id),

            -- Shot stats
            home_shots_avg_l5 REAL DEFAULT 0,
            away_shots_avg_l5 REAL DEFAULT 0,
            home_sot_avg_l5 REAL DEFAULT 0,
            away_sot_avg_l5 REAL DEFAULT 0,
            home_shot_accuracy_l5 REAL DEFAULT 0,
            away_shot_accuracy_l5 REAL DEFAULT 0,

            -- Corners
            home_corners_avg_l5 REAL DEFAULT 0,
            away_corners_avg_l5 REAL DEFAULT 0,

            -- Discipline
            home_yellows_avg_l5 REAL DEFAULT 0,
            away_yellows_avg_l5 REAL DEFAULT 0,
            home_reds_avg_l5 REAL DEFAULT 0,
            away_reds_avg_l5 REAL DEFAULT 0,

            -- Key players (top scorer goals per game going into match)
            home_top_scorer_gpg REAL DEFAULT 0,
            away_top_scorer_gpg REAL DEFAULT 0,
            home_top_assist_apg REAL DEFAULT 0,
            away_top_assist_apg REAL DEFAULT 0,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    print("[DB] Extended tables ready")


def get_team_id(conn, name):
    name = name.strip()
    row = conn.execute("SELECT id FROM teams WHERE name=?", (name,)).fetchone()
    if row:
        return row[0]
    # Fuzzy match
    row = conn.execute("SELECT id FROM teams WHERE name LIKE ? LIMIT 1", (f"%{name}%",)).fetchone()
    return row[0] if row else None


def get_match_id(conn, season_id, home_id, away_id):
    row = conn.execute("""
        SELECT id FROM matches
        WHERE season_id=? AND home_team_id=? AND away_team_id=?
        LIMIT 1
    """, (season_id, home_id, away_id)).fetchone()
    return row[0] if row else None


def download_match_stats(conn, year, code):
    """Download shot/corner/card stats from football-data.co.uk CSVs."""
    url = CSV_URL.format(code=code)
    print(f"  Fetching stats {year}/{year+1}... ", end="", flush=True)

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"FAILED ({e})")
        return 0

    season_id = conn.execute("SELECT id FROM seasons WHERE year=?", (year,)).fetchone()
    if not season_id:
        print(f"SKIP (season {year} not in DB)")
        return 0
    season_id = season_id[0]

    content = resp.content.decode("latin-1")
    reader  = csv.DictReader(io.StringIO(content))
    updated = 0

    for row in reader:
        home = row.get("HomeTeam","").strip()
        away = row.get("AwayTeam","").strip()
        if not home or not away:
            continue

        home_id = get_team_id(conn, home)
        away_id = get_team_id(conn, away)
        if not home_id or not away_id:
            continue

        match_id = get_match_id(conn, season_id, home_id, away_id)
        if not match_id:
            continue

        def safe_int(val):
            try: return int(val) if val and val.strip() else None
            except: return None

        conn.execute("""
            INSERT OR REPLACE INTO match_stats (
                match_id,
                home_shots, away_shots,
                home_shots_on_target, away_shots_on_target,
                home_corners, away_corners,
                home_fouls, away_fouls,
                home_yellow_cards, away_yellow_cards,
                home_red_cards, away_red_cards
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            match_id,
            safe_int(row.get("HS")),  safe_int(row.get("AS")),
            safe_int(row.get("HST")), safe_int(row.get("AST")),
            safe_int(row.get("HC")),  safe_int(row.get("AC")),
            safe_int(row.get("HF")),  safe_int(row.get("AF")),
            safe_int(row.get("HY")),  safe_int(row.get("AY")),
            safe_int(row.get("HR")),  safe_int(row.get("AR")),
        ))
        updated += 1

    conn.commit()
    print(f"{updated} matches")
    return updated


def fetch_player_events(conn, season_year):
    """
    Fetch player-level events (goals, cards) from the live API.
    Only works for recent seasons on the free tier.
    """
    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        print("  [SKIP] No API key — skipping player events")
        return

    season_id = conn.execute("SELECT id FROM seasons WHERE year=?", (season_year,)).fetchone()
    if not season_id:
        return
    season_id = season_id[0]

    print(f"  Fetching player events for {season_year}/{season_year+1}...")

    # Get finished matches for this season
    matches = conn.execute("""
        SELECT id FROM matches WHERE season_id=? AND status='FINISHED'
        ORDER BY matchday LIMIT 50
    """, (season_id,)).fetchall()

    fetched = 0
    for (match_id,) in matches:
        # Check if we already have events for this match
        existing = conn.execute(
            "SELECT COUNT(*) FROM player_events WHERE match_id=?", (match_id,)
        ).fetchone()[0]
        if existing > 0:
            continue

        resp = requests.get(f"{BASE_URL}/matches/{match_id}", headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            time.sleep(6)
            continue

        data  = resp.json()
        goals = data.get("goals", [])
        bookings = data.get("bookings", [])

        for g in goals:
            scorer  = g.get("scorer", {})
            assister= g.get("assist", {})
            team    = g.get("team", {})
            team_id = get_team_id(conn, team.get("name","")) if team else None

            if scorer and scorer.get("id"):
                conn.execute("""
                    INSERT OR IGNORE INTO player_events
                    (match_id, player_id, player_name, team_id, event_type, minute)
                    VALUES (?,?,?,?,?,?)
                """, (match_id, scorer["id"], scorer.get("name",""),
                      team_id, "GOAL", g.get("minute")))

            if assister and assister.get("id"):
                conn.execute("""
                    INSERT OR IGNORE INTO player_events
                    (match_id, player_id, player_name, team_id, event_type, minute)
                    VALUES (?,?,?,?,?,?)
                """, (match_id, assister["id"], assister.get("name",""),
                      team_id, "ASSIST", g.get("minute")))

        for b in bookings:
            player = b.get("player", {})
            team   = b.get("team", {})
            team_id= get_team_id(conn, team.get("name","")) if team else None
            card   = "RED_CARD" if b.get("card") == "RED" else "YELLOW_CARD"

            if player and player.get("id"):
                conn.execute("""
                    INSERT OR IGNORE INTO player_events
                    (match_id, player_id, player_name, team_id, event_type, minute)
                    VALUES (?,?,?,?,?,?)
                """, (match_id, player["id"], player.get("name",""),
                      team_id, card, b.get("minute")))

        conn.commit()
        fetched += 1
        time.sleep(6.5)  # rate limit

    print(f"  Fetched events for {fetched} matches")


def compute_player_season_stats(conn):
    """Aggregate player events into per-season stats."""
    conn.execute("DELETE FROM player_season_stats")

    rows = conn.execute("""
        SELECT
            pe.player_id, pe.player_name, pe.team_id,
            m.season_id,
            SUM(CASE WHEN pe.event_type='GOAL'   THEN 1 ELSE 0 END) AS goals,
            SUM(CASE WHEN pe.event_type='ASSIST'  THEN 1 ELSE 0 END) AS assists,
            SUM(CASE WHEN pe.event_type='YELLOW_CARD' THEN 1 ELSE 0 END) AS yellows,
            SUM(CASE WHEN pe.event_type='RED_CARD'    THEN 1 ELSE 0 END) AS reds,
            COUNT(DISTINCT pe.match_id) AS appearances
        FROM player_events pe
        JOIN matches m ON m.id = pe.match_id
        WHERE pe.player_id IS NOT NULL
        GROUP BY pe.player_id, m.season_id
    """).fetchall()

    for r in rows:
        pid, pname, tid, sid, goals, assists, yellows, reds, apps = r
        gpg = round(goals/apps, 3) if apps else 0
        apg = round(assists/apps, 3) if apps else 0
        cpg = round((yellows + reds*2)/apps, 3) if apps else 0

        conn.execute("""
            INSERT OR REPLACE INTO player_season_stats
            (player_id, player_name, team_id, season_id,
             appearances, goals, assists, yellow_cards, red_cards,
             goals_per_game, assists_per_game, cards_per_game)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pid, pname, tid, sid, apps, goals, assists, yellows, reds, gpg, apg, cpg))

    conn.commit()
    print(f"[DB] Computed stats for {len(rows)} player-season records")


def build_extended_features(conn):
    """
    Build match_features_extended table with rolling averages
    for shots, corners, cards going into each match.
    """
    c = conn.cursor()

    matches = c.execute("""
        SELECT m.id, m.season_id, m.matchday, m.home_team_id, m.away_team_id
        FROM matches m
        WHERE m.status='FINISHED'
        ORDER BY m.season_id, m.matchday
    """).fetchall()

    def rolling_stats(team_id, season_id, matchday, n=5):
        """Get average stats over last N matches for a team."""
        rows = c.execute("""
            SELECT
                CASE WHEN m.home_team_id=? THEN ms.home_shots ELSE ms.away_shots END,
                CASE WHEN m.home_team_id=? THEN ms.home_shots_on_target ELSE ms.away_shots_on_target END,
                CASE WHEN m.home_team_id=? THEN ms.home_corners ELSE ms.away_corners END,
                CASE WHEN m.home_team_id=? THEN ms.home_yellow_cards ELSE ms.away_yellow_cards END,
                CASE WHEN m.home_team_id=? THEN ms.home_red_cards ELSE ms.away_red_cards END
            FROM matches m
            JOIN match_stats ms ON ms.match_id = m.id
            WHERE m.season_id=?
              AND (m.home_team_id=? OR m.away_team_id=?)
              AND m.matchday < ?
              AND m.status='FINISHED'
            ORDER BY m.matchday DESC
            LIMIT ?
        """, (team_id,team_id,team_id,team_id,team_id,
              season_id,team_id,team_id,matchday,n)).fetchall()

        if not rows:
            return 0,0,0,0,0,0

        shots   = [r[0] or 0 for r in rows]
        sot     = [r[1] or 0 for r in rows]
        corners = [r[2] or 0 for r in rows]
        yellows = [r[3] or 0 for r in rows]
        reds    = [r[4] or 0 for r in rows]

        avg_shots   = sum(shots)/len(shots)
        avg_sot     = sum(sot)/len(sot)
        avg_acc     = (sum(sot)/sum(shots)) if sum(shots) > 0 else 0
        avg_corners = sum(corners)/len(corners)
        avg_yellows = sum(yellows)/len(yellows)
        avg_reds    = sum(reds)/len(reds)

        return avg_shots, avg_sot, avg_acc, avg_corners, avg_yellows, avg_reds

    def top_player_stat(team_id, season_id, stat):
        """Get the top player's per-game stat for a team going into this season."""
        row = c.execute(f"""
            SELECT {stat} FROM player_season_stats
            WHERE team_id=? AND season_id=?
            ORDER BY {stat} DESC LIMIT 1
        """, (team_id, season_id)).fetchone()
        return float(row[0]) if row else 0.0

    updated = 0
    for mid, sid, md, htid, atid in matches:
        hs = rolling_stats(htid, sid, md)
        as_ = rolling_stats(atid, sid, md)

        h_gpg = top_player_stat(htid, sid, "goals_per_game")
        a_gpg = top_player_stat(atid, sid, "goals_per_game")
        h_apg = top_player_stat(htid, sid, "assists_per_game")
        a_apg = top_player_stat(atid, sid, "assists_per_game")

        c.execute("""
            INSERT OR REPLACE INTO match_features_extended (
                match_id,
                home_shots_avg_l5, away_shots_avg_l5,
                home_sot_avg_l5, away_sot_avg_l5,
                home_shot_accuracy_l5, away_shot_accuracy_l5,
                home_corners_avg_l5, away_corners_avg_l5,
                home_yellows_avg_l5, away_yellows_avg_l5,
                home_reds_avg_l5, away_reds_avg_l5,
                home_top_scorer_gpg, away_top_scorer_gpg,
                home_top_assist_apg, away_top_assist_apg
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            mid,
            hs[0], as_[0],
            hs[1], as_[1],
            hs[2], as_[2],
            hs[3], as_[3],
            hs[4], as_[4],
            hs[5], as_[5],
            h_gpg, a_gpg,
            h_apg, a_apg,
        ))
        updated += 1

    conn.commit()
    print(f"[DB] Built extended features for {updated} matches")


def print_summary(conn):
    print("\n" + "="*55)
    print("EXTENDED STATS SUMMARY")
    print("="*55)
    tables = ["match_stats", "players", "player_events",
              "player_season_stats", "match_features_extended"]
    for t in tables:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:<35} {n:>6} rows")
        except:
            print(f"  {t:<35}  (not found)")

    # Sample shot stats
    sample = conn.execute("""
        SELECT ht.name, at.name,
               ms.home_shots, ms.away_shots,
               ms.home_shots_on_target, ms.away_shots_on_target,
               ms.home_corners, ms.away_corners,
               ms.home_yellow_cards, ms.away_yellow_cards
        FROM match_stats ms
        JOIN matches m ON m.id = ms.match_id
        JOIN teams ht ON ht.id = m.home_team_id
        JOIN teams at ON at.id = m.away_team_id
        WHERE ms.home_shots IS NOT NULL
        ORDER BY RANDOM() LIMIT 3
    """).fetchall()

    if sample:
        print("\nSample match stats:")
        print(f"  {'Fixture':<30} {'Shots':>8} {'SOT':>6} {'Corners':>8} {'Yellows':>8}")
        for r in sample:
            fixture = f"{r[0]} v {r[1]}"[:29]
            print(f"  {fixture:<30} {str(r[2])+'-'+str(r[3]):>8} {str(r[4])+'-'+str(r[5]):>6} {str(r[6])+'-'+str(r[7]):>8} {str(r[8])+'-'+str(r[9]):>8}")
    print("="*55)


def main():
    print("="*55)
    print("ENHANCED STATS DOWNLOADER")
    print("="*55)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # Check DB has base data
    match_count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    if match_count == 0:
        print("ERROR: No matches found. Run download_history.py first.")
        input("Press Enter to close...")
        return

    print(f"Found {match_count} matches in database")

    init_extra_tables(conn)

    # Get seasons in DB
    seasons = conn.execute("SELECT id, year FROM seasons ORDER BY year").fetchall()
    print(f"\nFound {len(seasons)} seasons in DB")

    print("\nStep 1: Downloading shot/corner/card stats from football-data.co.uk...")
    for sid, year in seasons:
        if year in SEASONS:
            download_match_stats(conn, year, SEASONS[year])

    print("\nStep 2: Fetching player events from live API (recent seasons only)...")
    if False:
        for sid, year in seasons[-3:]:  # Only last 3 seasons on free tier
            fetch_player_events(conn, year)
        compute_player_season_stats(conn)
    else:
        print("  [SKIP] No API key found — create api_key.txt to enable player stats")

    print("\nStep 3: Building extended match features...")
    build_extended_features(conn)

    print_summary(conn)

    print("\nDone! Now retrain with extended features:")
    print("  python pl_extended.py --both")

    conn.close()
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
