"""
Live fixtures bridge script
============================
Pulls this week's upcoming fixtures from the live API and adds them
to the historical database, matching team names correctly.

Run: python live_fixtures.py
"""
import requests
import sqlite3
import os
import time
from datetime import datetime

DB_PATH = "premier_league.db"
API_KEY = open("api_key.txt").read().strip() if os.path.exists("api_key.txt") else os.getenv("FOOTBALL_DATA_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_KEY}

# Team name mapping — live API names to historical database names
# Add more here if you see mismatches
NAME_MAP = {
    "AFC Bournemouth": "Bournemouth",
    "Brighton & Hove Albion FC": "Brighton",
    "Brighton & Hove Albion": "Brighton",
    "Manchester City FC": "Man City",
    "Manchester United FC": "Man United",
    "Newcastle United FC": "Newcastle",
    "Nottingham Forest FC": "Nottingham Forest",
    "Tottenham Hotspur FC": "Tottenham",
    "Tottenham Hotspur": "Tottenham",
    "West Ham United FC": "West Ham",
    "Wolverhampton Wanderers FC": "Wolves",
    "Wolverhampton Wanderers": "Wolves",
    "Arsenal FC": "Arsenal",
    "Aston Villa FC": "Aston Villa",
    "Brentford FC": "Brentford",
    "Chelsea FC": "Chelsea",
    "Crystal Palace FC": "Crystal Palace",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Leicester City FC": "Leicester",
    "Leeds United FC": "Leeds",
    "Liverpool FC": "Liverpool",
    "Luton Town FC": "Luton",
    "Burnley FC": "Burnley",
    "Sheffield United FC": "Sheffield United",
    "Sunderland AFC": "Sunderland",
    "Ipswich Town FC": "Ipswich",
    "Southampton FC": "Southampton",
}


def normalize(name):
    """Try to normalize a team name to match the historical database."""
    name = name.strip()
    if name in NAME_MAP:
        return NAME_MAP[name]
    # Strip common suffixes
    for suffix in [" FC", " AFC", " United", " City", " Town", " Wanderers"]:
        if name.endswith(suffix):
            cleaned = name[:-len(suffix)].strip()
            if cleaned:
                return cleaned
    return name


def find_team_id(conn, api_name):
    """Find a team ID in the database by trying various name formats."""
    candidates = [
        api_name,
        normalize(api_name),
        api_name.replace(" FC", "").strip(),
        api_name.replace(" AFC", "").strip(),
    ]

    for name in candidates:
        row = conn.execute(
            "SELECT id, name FROM teams WHERE name LIKE ? LIMIT 1",
            (f"%{name}%",)
        ).fetchone()
        if row:
            return row[0], row[1]

    return None, None


def main():
    if "YOUR_API_KEY_HERE" in API_KEY:
        print("ERROR: API key not set.")
        print("Either:")
        print("  1. Create a file called api_key.txt in Downloads with your key")
        print("  2. Or set environment variable FOOTBALL_DATA_API_KEY")
        input("Press Enter to close...")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    print("Fetching upcoming fixtures from live API...")
    resp = requests.get(
        f"{BASE_URL}/competitions/PL/matches",
        headers=HEADERS,
        params={"status": "TIMED,SCHEDULED"}
    )

    if resp.status_code != 200:
        print(f"API error: {resp.status_code} - {resp.text[:200]}")
        input("Press Enter to close...")
        return

    data = resp.json()
    matches = data.get("matches", [])
    print(f"Found {len(matches)} upcoming fixtures")

    # Get or create a season entry for the live season
    season_info = data.get("matches", [{}])[0].get("season", {}) if matches else {}
    season_year = 2024  # current season start year

    conn.execute("""
        INSERT OR IGNORE INTO seasons (year, start_date, end_date, current_matchday)
        VALUES (?, ?, ?, ?)
    """, (season_year, "2024-08-01", "2025-05-31", 38))
    conn.commit()

    season_id = conn.execute(
        "SELECT id FROM seasons WHERE year=?", (season_year,)
    ).fetchone()[0]

    added = 0
    skipped = 0
    unmatched = []

    for m in matches:
        home_api = m["homeTeam"]["name"]
        away_api = m["awayTeam"]["name"]
        matchday = m.get("matchday", 0)
        utc_date = m.get("utcDate", "")

        home_id, home_matched = find_team_id(conn, home_api)
        away_id, away_matched = find_team_id(conn, away_api)

        if not home_id:
            unmatched.append(f"  NOT FOUND: '{home_api}'")
            skipped += 1
            continue
        if not away_id:
            unmatched.append(f"  NOT FOUND: '{away_api}'")
            skipped += 1
            continue

        # Insert match
        try:
            conn.execute("""
                INSERT OR IGNORE INTO matches (
                    season_id, matchday, status, utc_date,
                    home_team_id, away_team_id, winner
                ) VALUES (?, ?, 'TIMED', ?, ?, ?, NULL)
            """, (season_id, matchday, utc_date, home_id, away_id))
            added += 1
        except sqlite3.IntegrityError as e:
            skipped += 1

    conn.commit()

    print(f"\nAdded {added} upcoming fixtures to database")
    if skipped > 0:
        print(f"Skipped {skipped} (already exist or team not found)")
    if unmatched:
        print("\nUnmatched team names (add to NAME_MAP in script if needed):")
        for u in set(unmatched):
            print(u)

    # Now build features for upcoming matches
    print("\nBuilding features for upcoming fixtures...")

    upcoming = conn.execute("""
        SELECT m.id, m.matchday, m.utc_date, m.home_team_id, m.away_team_id
        FROM matches m
        WHERE m.season_id=? AND m.status='TIMED'
        AND m.id NOT IN (SELECT match_id FROM match_features)
    """, (season_id,)).fetchall()

    def get_form(team_id, matchday):
        # Look across ALL seasons for most recent form
        r = conn.execute("""
            SELECT last5_wins, last5_draws, last5_losses, last5_gf, last5_ga
            FROM team_form
            WHERE team_id=?
            ORDER BY season_id DESC, as_of_matchday DESC LIMIT 1
        """, (team_id,)).fetchone()
        return r or (0, 0, 0, 0, 0)

    def get_standing(team_id):
        r = conn.execute("""
            SELECT position, points, goal_difference
            FROM standings
            WHERE team_id=?
            ORDER BY season_id DESC, matchday DESC LIMIT 1
        """, (team_id,)).fetchone()
        return r or (10, 0, 0)

    def get_h2h(htid, atid):
        r = conn.execute("""
            SELECT home_wins, away_wins, draws FROM head_to_head
            WHERE team_a_id=? AND team_b_id=?
            ORDER BY season_id DESC LIMIT 1
        """, (htid, atid)).fetchone()
        return r or (0, 0, 0)

    feat_added = 0
    for mid, md, utc_date, htid, atid in upcoming:
        hf = get_form(htid, md)
        af = get_form(atid, md)
        hs = get_standing(htid)
        as_ = get_standing(atid)
        h2h = get_h2h(htid, atid)

        conn.execute("""
            INSERT OR IGNORE INTO match_features (
                match_id, season_id, matchday, utc_date,
                home_team_id, away_team_id,
                home_l5_wins, home_l5_draws, home_l5_losses, home_l5_gf, home_l5_ga, home_l5_pts,
                away_l5_wins, away_l5_draws, away_l5_losses, away_l5_gf, away_l5_ga, away_l5_pts,
                home_position, away_position, home_points, away_points, home_gd, away_gd,
                h2h_home_wins, h2h_away_wins, h2h_draws,
                result, home_goals, away_goals, over_2_5, btts
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL)
        """, (
            mid, season_id, md, utc_date,
            htid, atid,
            hf[0], hf[1], hf[2], hf[3], hf[4], hf[0]*3+hf[1],
            af[0], af[1], af[2], af[3], af[4], af[0]*3+af[1],
            hs[0], as_[0], hs[1], as_[1], hs[2], as_[2],
            h2h[0], h2h[1], h2h[2]
        ))
        feat_added += 1

    conn.commit()
    print(f"Built features for {feat_added} upcoming fixtures")

    # Show upcoming fixtures
    fixtures = conn.execute("""
        SELECT mf.utc_date, ht.name, at.name
        FROM match_features mf
        JOIN teams ht ON ht.id = mf.home_team_id
        JOIN teams at ON at.id = mf.away_team_id
        WHERE mf.result IS NULL
        ORDER BY mf.utc_date LIMIT 15
    """).fetchall()

    if fixtures:
        print(f"\nUpcoming fixtures ready to predict ({len(fixtures)} total):")
        for f in fixtures:
            print(f"  {f[0][:10]}  {f[1]} vs {f[2]}")
        print("\nNow run: python predict.py")
    else:
        print("\nNo upcoming fixtures found — the season may be complete.")

    conn.close()
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
