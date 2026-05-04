"""
Player Stats — 2024/25 season data + known 25/26 transfers
===========================================================
Uses complete 2024/25 FPL stats (full season, reliable)
and applies known summer 2025 transfers so teams are correct.

When the 2025/26 season starts (August), switch AUTO_SEASON to True
and it will automatically use live data instead.

Run: python playerstats.py --both
"""

import sqlite3
import requests
import csv
import io
import json
import numpy as np
import argparse
from pathlib import Path
from datetime import datetime

DB_PATH = "premier_league.db"

# 2025/26 season is live — using live FPL API
AUTO_SEASON = True

FPL_LIVE_API = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_2425_CSV = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/2024-25/players_raw.csv"
FPL_TEAMS_CSV= "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/2024-25/teams.csv"

HEADERS_HTTP  = {"User-Agent": "Mozilla/5.0"}
FPL_POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# ── Known summer 2025 transfers ───────────────────────────────────────────────
# Format: "Player Name Fragment" -> "New Team Name (must match your DB)"
# Add any transfers you know about here
KNOWN_TRANSFERS_2025 = {
    "Eberechi Eze":         "Arsenal",
    "Bryan Mbeumo":         "Man United",
    "João Pedro":           "Chelsea",
    "Antoine Semenyo":      "Man City",       # if confirmed
    "Viktor Gyokeres":      "Arsenal",
    "Viktor Gyökeres":      "Arsenal",
    "Benjamin Sesko":       "Man City",
    "Hugo Ekitike":         "Liverpool",
    "Hugo Ekitiké":         "Liverpool",
    "Callum Wilson":        "West Ham",
    "Dominic Calvert-Lewin":"Leeds",
    # Add more here as you find out:
    # "Player Name":        "New Team",
}

# Players to remove entirely (retired, left PL, etc.)
REMOVE_PLAYERS = [
    "Rio Ngumoha",
    "Max Dowman",
    "Harrison Reed",      # if no longer playing regular minutes
]


def init_player_tables(conn):
    conn.executescript("""
        DROP TABLE IF EXISTS player_predictions;
        DROP TABLE IF EXISTS player_season_stats;
        DROP TABLE IF EXISTS players;

        CREATE TABLE players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            team_name TEXT,
            team_id INTEGER,
            position TEXT,
            fpl_id INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name)
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
            shots INTEGER DEFAULT 0,
            shots_on_target INTEGER DEFAULT 0,
            shots_per90 REAL DEFAULT 0,
            yellow_cards INTEGER DEFAULT 0,
            red_cards INTEGER DEFAULT 0,
            yellows_per90 REAL DEFAULT 0,
            xg REAL DEFAULT 0,
            xa REAL DEFAULT 0,
            xg_per90 REAL DEFAULT 0,
            bonus_points INTEGER DEFAULT 0,
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
    print("[DB] Player tables ready")


FPL_NAME_TO_DB = {
    "Arsenal":"Arsenal","Aston Villa":"Aston Villa",
    "Bournemouth":"Bournemouth","Brentford":"Brentford",
    "Brighton":"Brighton","Burnley":"Burnley",
    "Chelsea":"Chelsea","Crystal Palace":"Crystal Palace",
    "Everton":"Everton","Fulham":"Fulham",
    "Leeds":"Leeds","Liverpool":"Liverpool",
    "Man City":"Man City","Man Utd":"Man United",
    "Newcastle":"Newcastle","Nott'm Forest":"Nottingham Forest",
    "Spurs":"Tottenham","Sunderland":"Sunderland",
    "West Ham":"West Ham","Wolves":"Wolves",
}

def match_db_team(conn, fpl_team_name):
    db_name = FPL_NAME_TO_DB.get(fpl_team_name, fpl_team_name)
    row = conn.execute("SELECT id, name FROM teams WHERE name=? LIMIT 1", (db_name,)).fetchone()
    return (row[0], row[1]) if row else (None, db_name)


def fetch_2425_csv():
    """Fetch 2024/25 full season data from GitHub CSV."""
    print(f"Fetching 2024/25 season data...", end=" ", flush=True)
    try:
        # Get team mapping
        t_resp = requests.get(FPL_TEAMS_CSV, headers=HEADERS_HTTP, timeout=15)
        t_resp.raise_for_status()
        team_map = {}
        for row in csv.DictReader(io.StringIO(t_resp.text)):
            team_map[int(row["id"])] = row["name"]

        # Get player stats
        p_resp = requests.get(FPL_2425_CSV, headers=HEADERS_HTTP, timeout=15)
        p_resp.raise_for_status()
        players = list(csv.DictReader(io.StringIO(p_resp.text)))
        print(f"{len(players)} players")
        return players, team_map
    except Exception as e:
        print(f"FAILED: {e}")
        return [], {}


def fetch_live_fpl():
    """Fetch live FPL API data for current season."""
    print(f"Fetching live FPL data...", end=" ", flush=True)
    try:
        resp = requests.get(FPL_LIVE_API, headers=HEADERS_HTTP, timeout=20)
        resp.raise_for_status()
        data     = resp.json()
        players  = data.get("elements", [])
        team_map = {t["id"]: t["name"] for t in data.get("teams", [])}
        print(f"{len(players)} players")
        return players, team_map, True
    except Exception as e:
        print(f"FAILED: {e}")
        return [], {}, False


def save_from_csv(conn, players, team_map, season_label):
    """Save players from 2024/25 CSV format."""
    saved = 0
    for p in players:
        try:
            first = p.get("first_name", "").strip()
            last  = p.get("second_name", p.get("last_name", "")).strip()
            name  = f"{first} {last}".strip()
            if not name:
                continue

            fpl_team_id = int(p.get("team", 0))
            fpl_team    = team_map.get(fpl_team_id, "Unknown")
            pos_code    = int(p.get("element_type", p.get("position", 3)))
            position    = FPL_POSITIONS.get(pos_code, "MID")

            mins    = int(p.get("minutes",       0))
            goals   = int(p.get("goals_scored",  0))
            assists = int(p.get("assists",        0))
            yellows = int(p.get("yellow_cards",  0))
            reds    = int(p.get("red_cards",      0))
            starts  = int(p.get("starts",         max(mins // 75, 0)))
            bonus   = int(p.get("bonus",          0))
            apps    = starts if starts > 0 else max(mins // 70, 1) if mins > 0 else 0

            xg = float(p.get("expected_goals",   goals * 0.85) or 0)
            xa = float(p.get("expected_assists",  assists * 0.8) or 0)

            # Only include players with meaningful minutes
            if mins < 90:
                continue

            mins90 = max(mins / 90, 0.1)
            g90    = round(goals   / mins90, 3)
            a90    = round(assists / mins90, 3)
            y90    = round(yellows / mins90, 3)
            xg90   = round(xg      / mins90, 3)
            sh90   = round(goals * 3.5 / mins90, 3)

            db_team_id, db_team_name = match_db_team(conn, fpl_team)

            conn.execute("""
                INSERT OR IGNORE INTO players (name, team_name, team_id, position, fpl_id)
                VALUES (?,?,?,?,?)
            """, (name, db_team_name, db_team_id, position, fpl_team_id))
            conn.execute("""
                UPDATE players SET team_name=?, team_id=?, position=?
                WHERE name=?
            """, (db_team_name, db_team_id, position, name))

            pid = conn.execute("SELECT id FROM players WHERE name=?", (name,)).fetchone()
            if not pid:
                continue

            conn.execute("""
                INSERT OR REPLACE INTO player_season_stats (
                    player_id, season_label, team_name, position,
                    appearances, minutes, goals, assists,
                    goals_per90, assists_per90,
                    shots, shots_on_target, shots_per90,
                    yellow_cards, red_cards, yellows_per90,
                    xg, xa, xg_per90, bonus_points
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                pid[0], season_label, db_team_name, position,
                apps, mins, goals, assists,
                g90, a90,
                int(goals * 3.5), int(goals * 2), sh90,
                yellows, reds, y90,
                round(xg, 3), round(xa, 3), xg90, bonus
            ))
            saved += 1
        except:
            continue

    conn.commit()
    return saved


def apply_transfers(conn):
    """Move players to their new clubs for 2025/26."""
    print("\nApplying 2025 summer transfers...")
    moved = 0
    for name_fragment, new_team in KNOWN_TRANSFERS_2025.items():
        player = conn.execute("""
            SELECT id, name, team_name FROM players
            WHERE name LIKE ? LIMIT 1
        """, (f"%{name_fragment}%",)).fetchone()

        if not player:
            continue

        pid, pname, old_team = player
        team = conn.execute(
            "SELECT id, name FROM teams WHERE name=? OR name LIKE ? LIMIT 1",
            (new_team, f"%{new_team.split()[0]}%")
        ).fetchone()

        if not team:
            print(f"  Team not found: {new_team}")
            continue

        conn.execute("UPDATE players SET team_name=?, team_id=? WHERE id=?",
                     (team[1], team[0], pid))
        conn.execute("UPDATE player_season_stats SET team_name=? WHERE player_id=?",
                     (team[1], pid))
        conn.commit()

        if old_team != team[1]:
            print(f"  {pname}: {old_team} → {team[1]}")
            moved += 1

    print(f"  Applied {moved} transfers")


def remove_players(conn):
    """Remove players who've left the PL."""
    removed = 0
    for name in REMOVE_PLAYERS:
        player = conn.execute(
            "SELECT id, name FROM players WHERE name LIKE ? LIMIT 1",
            (f"%{name}%",)
        ).fetchone()
        if player:
            conn.execute("DELETE FROM player_season_stats WHERE player_id=?", (player[0],))
            conn.execute("DELETE FROM players WHERE id=?", (player[0],))
            conn.commit()
            print(f"  Removed: {player[1]}")
            removed += 1
    if removed:
        print(f"  Removed {removed} players")


def scrape(conn):
    init_player_tables(conn)

    if AUTO_SEASON:
        # Use live FPL API
        fpl_players, team_map, ok = fetch_live_fpl()
        if not ok or not fpl_players:
            print("Live API failed, falling back to 2024/25...")
            AUTO_SEASON_fallback = True
        else:
            # Check if enough gameweeks played (min 900 mins for top players)
            top_mins = max(int(p.get("minutes", 0)) for p in fpl_players)
            if top_mins < 900:
                print(f"Season just started (max {top_mins} mins) — using 2024/25 data instead")
                AUTO_SEASON_fallback = True
            else:
                season_label = "2025/2026"
                saved = save_from_csv(conn, fpl_players, team_map, season_label)
                print(f"Saved {saved} players (2025/26 live)")
                AUTO_SEASON_fallback = False

        if AUTO_SEASON_fallback:
            players, team_map = fetch_2425_csv()
            season_label = "2024/2025"
            saved = save_from_csv(conn, players, team_map, season_label)
            print(f"Saved {saved} players (2024/25 fallback)")
    else:
        # Use 2024/25 historical data
        players, team_map = fetch_2425_csv()
        if not players:
            print("Could not fetch data.")
            return False
        season_label = "2024/2025"
        saved = save_from_csv(conn, players, team_map, season_label)
        print(f"Saved {saved} players (2024/25 season)")

    # Apply transfers and cleanup
    apply_transfers(conn)
    remove_players(conn)

    # Show top scorers
    sample = conn.execute("""
        SELECT p.name, p.team_name, p.position,
               pss.goals, pss.assists, pss.yellow_cards,
               pss.xg, pss.goals_per90, pss.appearances
        FROM players p
        JOIN player_season_stats pss ON pss.player_id = p.id
        WHERE pss.goals >= 5 AND pss.minutes >= 900
        ORDER BY pss.goals DESC LIMIT 15
    """).fetchall()

    if sample:
        print(f"\nTop scorers loaded:")
        print(f"  {'Player':<25} {'Team':<20} {'Pos':>3} {'G':>3} {'A':>3} {'Y':>3} {'xG':>5} {'G/90':>5} Apps")
        print(f"  {'-'*80}")
        for r in sample:
            print(f"  {r[0]:<25} {r[1]:<20} {r[2]:>3} {r[3]:>3} {r[4]:>3} {r[5]:>3} {r[6]:>5.1f} {r[7]:>5.2f} {r[8]:>4}")

    return True


def predict_players(conn):
    total = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    if total == 0:
        print("No player data. Run: python playerstats.py --scrape first")
        return

    fixtures = conn.execute("""
        SELECT mf.match_id, mf.utc_date, mf.home_team_id, mf.away_team_id,
               ht.name, at.name, mf.home_position, mf.away_position
        FROM match_features mf
        JOIN teams ht ON ht.id = mf.home_team_id
        JOIN teams at ON at.id = mf.away_team_id
        WHERE mf.result IS NULL
        ORDER BY mf.utc_date
    """).fetchall()

    if not fixtures:
        print("No upcoming fixtures. Run: python live_fixtures.py")
        return

    print("\n" + "="*78)
    print("PLAYER PREDICTIONS")
    print("="*78)

    all_preds = []

    for mid, date, htid, atid, home_team, away_team, home_pos, away_pos in fixtures:
        home_str = (20 - int(home_pos or 10)) / 20
        away_str = (20 - int(away_pos or 10)) / 20

        print(f"\n{'='*78}")
        print(f"  {date[:10]}  |  {home_team}  vs  {away_team}")
        print(f"{'='*78}")

        fix_pred = {
            "fixture": f"{home_team} vs {away_team}",
            "date":    date[:10],
            "players": []
        }

        for team_name, team_id, is_home, opp_str in [
            (home_team, htid, True,  away_str),
            (away_team, atid, False, home_str),
        ]:
            players = conn.execute("""
                SELECT p.id, p.name, p.position,
                       pss.goals_per90, pss.assists_per90,
                       pss.shots_per90, pss.yellows_per90,
                       pss.xg_per90, pss.appearances, pss.minutes
                FROM players p
                JOIN player_season_stats pss ON pss.player_id = p.id
                WHERE p.team_id=?
                  AND pss.minutes >= 1200
                ORDER BY pss.xg_per90 DESC
            """, (team_id,)).fetchall()

            if not players:
                # Fall back to lower threshold if team has few qualifying players
                players = conn.execute("""
                    SELECT p.id, p.name, p.position,
                           pss.goals_per90, pss.assists_per90,
                           pss.shots_per90, pss.yellows_per90,
                           pss.xg_per90, pss.appearances, pss.minutes
                    FROM players p
                    JOIN player_season_stats pss ON pss.player_id = p.id
                    WHERE p.team_id=?
                      AND pss.minutes >= 270
                    ORDER BY pss.xg_per90 DESC
                """, (team_id,)).fetchall()

            if not players:
                print(f"\n  {team_name}: No player data")
                continue

            hb       = 1.12 if is_home else 0.90
            cb       = 0.93 if is_home else 1.07
            att_mod  = 1 - opp_str * 0.15
            card_mod = 1 + opp_str * 0.10

            print(f"\n  {team_name} ({'Home' if is_home else 'Away'}) — {len(players)} players")
            print(f"  {'Player':<26} {'Pos':>3} {'Score%':>7} {'Assist%':>8} {'Yellow%':>8} {'xG/90':>7}")
            print(f"  {'-'*66}")

            team_preds = []
            for pid, pname, pos, g90, a90, sh90, y90, xg90, apps, mins in players:
                g90  = float(g90  or 0)
                a90  = float(a90  or 0)
                y90  = float(y90  or 0)
                xg90 = float(xg90 or 0)

                rate_g = max(xg90, g90) * hb * att_mod
                rate_a = a90 * hb * att_mod
                rate_y = y90 * cb * card_mod

                sp = float(np.clip(1 - np.exp(-rate_g), 0.01, 0.85))
                ap = float(np.clip(1 - np.exp(-rate_a), 0.01, 0.70))
                yp = float(np.clip(1 - np.exp(-rate_y), 0.02, 0.65))

                team_preds.append({
                    "name":        pname,
                    "position":    pos or "?",
                    "team":        team_name,
                    "score_prob":  round(sp, 3),
                    "assist_prob": round(ap, 3),
                    "yellow_prob": round(yp, 3),
                    "xg_per90":    round(xg90, 3),
                })

                conn.execute("""
                    INSERT OR REPLACE INTO player_predictions
                    (match_id, player_id, player_name, team_name, position,
                     score_prob, assist_prob, yellow_prob)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (mid, pid, pname, team_name, pos or "?", sp, ap, yp))

            conn.commit()
            team_preds.sort(key=lambda x: x["score_prob"], reverse=True)
            for pl in team_preds[:8]:
                print(f"  {pl['name']:<26} {pl['position']:>3} {pl['score_prob']:>6.1%} {pl['assist_prob']:>7.1%} {pl['yellow_prob']:>7.1%} {pl['xg_per90']:>6.3f}")

            fix_pred["players"].extend(team_preds)

        all_preds.append(fix_pred)

    print(f"\n{'='*78}")
    print("TOP 20 SCORER CANDIDATES")
    print(f"{'='*78}")
    print(f"  {'Player':<26} {'Team':<20} {'Pos':>3} {'Score%':>7} {'Assist%':>8} {'Yellow%':>8}")
    print(f"  {'-'*76}")

    all_p = []
    for f in all_preds:
        all_p.extend(f["players"])
    all_p.sort(key=lambda x: x["score_prob"], reverse=True)

    seen, shown = set(), 0
    for p in all_p:
        if p["name"] not in seen and shown < 20:
            print(f"  {p['name']:<26} {p['team']:<20} {p['position']:>3} {p['score_prob']:>6.1%} {p['assist_prob']:>7.1%} {p['yellow_prob']:>7.1%}")
            seen.add(p["name"])
            shown += 1

    out = f"player_preds_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_preds, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scrape",  action="store_true")
    parser.add_argument("--predict", action="store_true")
    parser.add_argument("--both",    action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")

    if args.scrape or args.both:
        scrape(conn)
    if args.predict or args.both:
        predict_players(conn)
    if not args.scrape and not args.predict and not args.both:
        print("Usage:")
        print("  python playerstats.py --scrape")
        print("  python playerstats.py --predict")
        print("  python playerstats.py --both")

    conn.close()
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
