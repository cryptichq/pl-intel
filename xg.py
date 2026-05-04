"""
xG Fetcher
===========
Gets real xG data using multiple sources:
1. Understat.com (best source, sometimes blocked)
2. Calculated xG from goals/shots in our DB (always works)
3. Team attack/defence ratings as proxy

Run: python xg.py
"""

import sqlite3
import requests
import json
import re
import time
from datetime import datetime

DB_PATH = "premier_league.db"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Current season team xG from whoscored/sofascore public data
# These are approximate 2025/26 season averages - updated manually when needed
FALLBACK_XG = {
    "Arsenal":          {"xg_for": 2.21, "xg_against": 0.89},
    "Liverpool":        {"xg_for": 2.35, "xg_against": 0.95},
    "Man City":         {"xg_for": 2.18, "xg_against": 1.02},
    "Chelsea":          {"xg_for": 1.98, "xg_against": 1.15},
    "Tottenham":        {"xg_for": 1.85, "xg_against": 1.42},
    "Man United":       {"xg_for": 1.72, "xg_against": 1.38},
    "Newcastle":        {"xg_for": 1.68, "xg_against": 1.21},
    "Aston Villa":      {"xg_for": 1.55, "xg_against": 1.28},
    "Brighton":         {"xg_for": 1.62, "xg_against": 1.31},
    "West Ham":         {"xg_for": 1.35, "xg_against": 1.52},
    "Brentford":        {"xg_for": 1.71, "xg_against": 1.44},
    "Fulham":           {"xg_for": 1.42, "xg_against": 1.38},
    "Crystal Palace":   {"xg_for": 1.28, "xg_against": 1.35},
    "Everton":          {"xg_for": 1.31, "xg_against": 1.48},
    "Bournemouth":      {"xg_for": 1.45, "xg_against": 1.41},
    "Wolves":           {"xg_for": 1.18, "xg_against": 1.55},
    "Leeds":            {"xg_for": 1.38, "xg_against": 1.62},
    "Burnley":          {"xg_for": 1.15, "xg_against": 1.71},
    "Sunderland":       {"xg_for": 1.22, "xg_against": 1.58},
    "Nottingham Forest":{"xg_for": 1.19, "xg_against": 1.45},
    "Brighton":         {"xg_for": 1.62, "xg_against": 1.31},
    "Leeds":            {"xg_for": 1.38, "xg_against": 1.62},
    "Sunderland":       {"xg_for": 1.22, "xg_against": 1.58},
    "Burnley":          {"xg_for": 1.15, "xg_against": 1.71},
}


def try_understat(season="2025"):
    """Try to fetch xG from Understat."""
    print(f"  Trying Understat (season {season})...", end=" ", flush=True)
    try:
        url  = f"https://understat.com/league/EPL/{season}"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            print(f"blocked ({resp.status_code})")
            return {}

        html    = resp.text
        pattern = r"var teamsData\s*=\s*JSON\.parse\('(.+?)'\)"
        match   = re.search(pattern, html)
        if not match:
            print("data not found")
            return {}

        raw = match.group(1)
        try:
            raw = raw.encode("raw_unicode_escape").decode("unicode_escape")
        except:
            pass

        teams_data = json.loads(raw)
        xg_data    = {}

        for team_id, team_info in teams_data.items():
            name = team_info.get("title","")
            h    = team_info.get("history", [])
            if not h:
                continue

            # Average over last 5 games
            recent = h[-5:] if len(h)>=5 else h
            xg_for = sum(float(g.get("xG",0)) for g in recent) / len(recent)
            xg_ag  = sum(float(g.get("xGA",0)) for g in recent) / len(recent)
            xg_data[name] = {
                "xg_for":     round(xg_for, 3),
                "xg_against": round(xg_ag,  3),
                "games":      len(h),
            }

        print(f"got {len(xg_data)} teams")
        time.sleep(2)
        return xg_data

    except Exception as e:
        print(f"failed ({e})")
        return {}


def calculate_xg_from_db(conn):
    """
    Calculate proxy xG from our historical match data.
    Uses goals scored/conceded over last 10 PL matches per team
    adjusted by average goals in the league (a simple but effective proxy).
    """
    print("  Calculating xG from historical data...")

    # Get league average goals per game this season
    avg = conn.execute("""
        SELECT AVG(home_score_ft + away_score_ft)
        FROM matches
        WHERE status='FINISHED'
        AND season_id=(SELECT MAX(id) FROM seasons)
    """).fetchone()[0] or 2.7

    teams = conn.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
    xg_data = {}

    for tid, name in teams:
        # Current season only (last 10 matches)
        # Use most recent season with 300+ finished matches (current PL teams)
        current_season = conn.execute("""
            SELECT season_id FROM matches
            WHERE status='FINISHED'
            GROUP BY season_id
            HAVING COUNT(*) >= 300
            ORDER BY MAX(utc_date) DESC LIMIT 1
        """).fetchone()[0]

        recent = conn.execute("""
            SELECT
                CASE WHEN home_team_id=? THEN home_score_ft ELSE away_score_ft END as gf,
                CASE WHEN home_team_id=? THEN away_score_ft ELSE home_score_ft END as ga
            FROM matches
            WHERE (home_team_id=? OR away_team_id=?)
            AND status='FINISHED'
            AND season_id=?
            ORDER BY utc_date DESC LIMIT 10
        """, (tid,tid,tid,tid,current_season)).fetchall()

        if len(recent) < 3:
            continue

        avg_gf = sum(r[0] or 0 for r in recent) / len(recent)
        avg_ga = sum(r[1] or 0 for r in recent) / len(recent)

        # Apply slight regression to league mean (xG tends to be closer to mean than goals)
        REGRESS = 0.25
        xg_for     = round(avg_gf * (1-REGRESS) + (avg/2) * REGRESS, 3)
        xg_against = round(avg_ga * (1-REGRESS) + (avg/2) * REGRESS, 3)

        xg_data[name] = {
            "xg_for":     xg_for,
            "xg_against": xg_against,
            "source":     "calculated",
            "games":      len(recent),
        }

    print(f"  Calculated xG for {len(xg_data)} teams")
    return xg_data


def save_xg_to_db(conn, xg_data):
    """Save xG data to team_xg table and update fixture_enrichment."""

    # Create table if needed
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_xg (
            team_id     INTEGER PRIMARY KEY,
            team_name   TEXT,
            xg_for      REAL DEFAULT 1.2,
            xg_against  REAL DEFAULT 1.2,
            source      TEXT DEFAULT 'calculated',
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    saved = 0
    for team_name, data in xg_data.items():
        # Find team in DB
        row = conn.execute(
            "SELECT id FROM teams WHERE name=? OR name LIKE ? LIMIT 1",
            (team_name, f"%{team_name.split()[0]}%")
        ).fetchone()
        if not row:
            continue

        conn.execute("""
            INSERT OR REPLACE INTO team_xg
            (team_id, team_name, xg_for, xg_against, source)
            VALUES (?,?,?,?,?)
        """, (
            row[0], team_name,
            data["xg_for"], data["xg_against"],
            data.get("source","understat")
        ))
        saved += 1

    conn.commit()
    print(f"  Saved xG for {saved} teams")

    # Update fixture_enrichment for upcoming matches
    upcoming = conn.execute("""
        SELECT m.id, m.home_team_id, m.away_team_id
        FROM matches m
        WHERE m.status IN ('TIMED','SCHEDULED')
    """).fetchall()

    for mid, htid, atid in upcoming:
        h_xg = conn.execute("SELECT xg_for, xg_against FROM team_xg WHERE team_id=?", (htid,)).fetchone()
        a_xg = conn.execute("SELECT xg_for, xg_against FROM team_xg WHERE team_id=?", (atid,)).fetchone()

        h_xgf = h_xg[0] if h_xg else 1.2
        h_xga = h_xg[1] if h_xg else 1.2
        a_xgf = a_xg[0] if a_xg else 1.2
        a_xga = a_xg[1] if a_xg else 1.2

        # xG for home team = their attack vs away team's defence
        home_xg_pred = round((h_xgf + a_xga) / 2, 3)
        away_xg_pred = round((a_xgf + h_xga) / 2, 3)

        conn.execute("""
            INSERT OR REPLACE INTO fixture_enrichment
            (match_id, home_xg_avg_l5, away_xg_avg_l5,
             home_xga_avg_l5, away_xga_avg_l5,
             home_xg_diff_l5, away_xg_diff_l5)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET
                home_xg_avg_l5=excluded.home_xg_avg_l5,
                away_xg_avg_l5=excluded.away_xg_avg_l5,
                home_xga_avg_l5=excluded.home_xga_avg_l5,
                away_xga_avg_l5=excluded.away_xga_avg_l5,
                home_xg_diff_l5=excluded.home_xg_diff_l5,
                away_xg_diff_l5=excluded.away_xg_diff_l5
        """, (mid, home_xg_pred, away_xg_pred,
              h_xga, a_xga,
              round(h_xgf - h_xga, 3), round(a_xgf - a_xga, 3)))

    conn.commit()
    print(f"  Updated xG for {len(upcoming)} upcoming fixtures")


def print_xg_table(xg_data):
    """Print xG table sorted by attacking threat."""
    print(f"\n{'='*60}")
    print(f"TEAM xG RATINGS (2025/26 Season)")
    print(f"{'='*60}")
    print(f"{'Team':<25} {'xG For':>8} {'xG Against':>11} {'xG Diff':>9} {'Source'}")
    print(f"{'-'*60}")

    for name, d in sorted(xg_data.items(), key=lambda x: -x[1]["xg_for"]):
        diff = d["xg_for"] - d["xg_against"]
        src  = d.get("source","?")[:10]
        print(f"{name:<25} {d['xg_for']:>8.2f} {d['xg_against']:>11.2f} {diff:>+9.2f}  {src}")

    print(f"{'='*60}")


def main():
    conn = sqlite3.connect(DB_PATH)

    print("="*55)
    print("xG FETCHER")
    print("="*55)

    # Try Understat first (best data)
    print("\n[1] Trying Understat...")
    xg_data = try_understat("2025")

    # Fall back to DB calculation
    if not xg_data:
        print("\n[2] Understat unavailable — calculating from match history...")
        xg_data = calculate_xg_from_db(conn)

    # Merge with fallback data for any missing teams
    print("\n[3] Filling gaps with current season estimates...")
    # Only add estimates for teams actually in current season
    current_team_names = {r[1] for r in conn.execute("""
        SELECT DISTINCT t.id, t.name FROM matches m
        JOIN teams t ON t.id=m.home_team_id OR t.id=m.away_team_id
        WHERE m.season_id=2404
    """).fetchall()}
    for team, data in FALLBACK_XG.items():
        if team not in xg_data and team in current_team_names:
            xg_data[team] = {**data, "source": "estimate"}
            print(f"  Added estimate for {team}")

    # Remove relegated/wrong teams and fix known bad values
    NOT_IN_PL = {"Luton", "Sheffield United", "Ipswich", "Leicester"}
    for team in NOT_IN_PL:
        xg_data.pop(team, None)

    # Brighton calculated wrong due to defensive style confusing goal proxy
    # They create good chances but score less - use estimate
    if "Brighton" in xg_data and xg_data["Brighton"]["xg_for"] < 1.2:
        xg_data["Brighton"] = {"xg_for": 1.62, "xg_against": 1.31, "source": "estimate"}
        print("  Fixed Brighton xG (calculated value unreliable)")

    # Nottingham Forest duplicate - remove the estimate if calculated exists
    if "Nottingham Forest" in xg_data and "Nott'm Forest" in xg_data:
        xg_data.pop("Nottingham Forest", None)

    # Save to DB
    print("\n[4] Saving to database...")
    save_xg_to_db(conn, xg_data)

    # Show table
    print_xg_table(xg_data)

    conn.close()
    print("\nDone! xG data is now live in your predictions.")
    print("Run: python pl.py --predict && python site.py")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
