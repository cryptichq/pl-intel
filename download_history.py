"""
Historical Premier League Data Downloader
==========================================
Downloads free CSV data from football-data.co.uk
Covers Premier League seasons from 2000 to present.
No API key needed — completely free.

Run: python download_history.py
"""

import requests
import sqlite3
import csv
import io
import time
import os
from datetime import datetime

DB_PATH = "premier_league.db"

# football-data.co.uk season codes
# Format: season starting year → URL code
SEASONS = {
    2000: "0001", 2001: "0102", 2002: "0203", 2003: "0304",
    2004: "0405", 2005: "0506", 2006: "0607", 2007: "0708",
    2008: "0809", 2009: "0910", 2010: "1011", 2011: "1112",
    2012: "1213", 2013: "1314", 2014: "1415", 2015: "1516",
    2016: "1617", 2017: "1718", 2018: "1819", 2019: "1920",
    2020: "2021", 2021: "2122", 2022: "2223", 2023: "2324",
}

BASE_URL = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER UNIQUE,
            start_date TEXT,
            end_date TEXT,
            current_matchday INTEGER DEFAULT 38
        );

        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id INTEGER REFERENCES seasons(id),
            matchday INTEGER DEFAULT 0,
            status TEXT DEFAULT 'FINISHED',
            utc_date TEXT,
            home_team_id INTEGER REFERENCES teams(id),
            away_team_id INTEGER REFERENCES teams(id),
            home_score_ft INTEGER,
            away_score_ft INTEGER,
            home_score_ht INTEGER,
            away_score_ht INTEGER,
            winner TEXT,
            stage TEXT DEFAULT 'REGULAR_SEASON',
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(season_id, home_team_id, away_team_id)
        );

        CREATE TABLE IF NOT EXISTS standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id INTEGER REFERENCES seasons(id),
            matchday INTEGER,
            team_id INTEGER REFERENCES teams(id),
            position INTEGER,
            played_games INTEGER,
            won INTEGER,
            draw INTEGER,
            lost INTEGER,
            points INTEGER,
            goals_for INTEGER,
            goals_against INTEGER,
            goal_difference INTEGER,
            form TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(season_id, matchday, team_id)
        );

        CREATE TABLE IF NOT EXISTS head_to_head (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_a_id INTEGER REFERENCES teams(id),
            team_b_id INTEGER REFERENCES teams(id),
            season_id INTEGER REFERENCES seasons(id),
            home_wins INTEGER DEFAULT 0,
            away_wins INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            total_matches INTEGER DEFAULT 0,
            avg_goals_home REAL DEFAULT 0,
            avg_goals_away REAL DEFAULT 0,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_a_id, team_b_id, season_id)
        );

        CREATE TABLE IF NOT EXISTS team_form (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER REFERENCES teams(id),
            season_id INTEGER REFERENCES seasons(id),
            as_of_matchday INTEGER,
            last5_wins INTEGER DEFAULT 0,
            last5_draws INTEGER DEFAULT 0,
            last5_losses INTEGER DEFAULT 0,
            last5_gf INTEGER DEFAULT 0,
            last5_ga INTEGER DEFAULT 0,
            last10_wins INTEGER DEFAULT 0,
            last10_draws INTEGER DEFAULT 0,
            last10_losses INTEGER DEFAULT 0,
            last10_gf INTEGER DEFAULT 0,
            last10_ga INTEGER DEFAULT 0,
            home_last5_wins INTEGER DEFAULT 0,
            home_last5_gf INTEGER DEFAULT 0,
            home_last5_ga INTEGER DEFAULT 0,
            away_last5_wins INTEGER DEFAULT 0,
            away_last5_gf INTEGER DEFAULT 0,
            away_last5_ga INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_id, season_id, as_of_matchday)
        );

        CREATE TABLE IF NOT EXISTS match_features (
            match_id INTEGER PRIMARY KEY REFERENCES matches(id),
            season_id INTEGER,
            matchday INTEGER,
            utc_date TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_l5_wins INTEGER DEFAULT 0,
            home_l5_draws INTEGER DEFAULT 0,
            home_l5_losses INTEGER DEFAULT 0,
            home_l5_gf REAL DEFAULT 0,
            home_l5_ga REAL DEFAULT 0,
            home_l5_pts INTEGER DEFAULT 0,
            away_l5_wins INTEGER DEFAULT 0,
            away_l5_draws INTEGER DEFAULT 0,
            away_l5_losses INTEGER DEFAULT 0,
            away_l5_gf REAL DEFAULT 0,
            away_l5_ga REAL DEFAULT 0,
            away_l5_pts INTEGER DEFAULT 0,
            home_position INTEGER DEFAULT 10,
            away_position INTEGER DEFAULT 10,
            home_points INTEGER DEFAULT 0,
            away_points INTEGER DEFAULT 0,
            home_gd INTEGER DEFAULT 0,
            away_gd INTEGER DEFAULT 0,
            h2h_home_wins INTEGER DEFAULT 0,
            h2h_away_wins INTEGER DEFAULT 0,
            h2h_draws INTEGER DEFAULT 0,
            result TEXT,
            home_goals INTEGER,
            away_goals INTEGER,
            over_2_5 INTEGER,
            btts INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    return conn


def get_or_create_team(conn, name):
    name = name.strip()
    row = conn.execute("SELECT id FROM teams WHERE name=?", (name,)).fetchone()
    if row:
        return row[0]
    conn.execute("INSERT INTO teams (name) VALUES (?)", (name,))
    conn.commit()
    return conn.execute("SELECT id FROM teams WHERE name=?", (name,)).fetchone()[0]


def parse_date(date_str):
    """Parse dd/mm/yy or dd/mm/yyyy to ISO format."""
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def download_season(conn, year, code):
    url = BASE_URL.format(code=code)
    print(f"  Downloading {year}/{year+1}... ", end="", flush=True)

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"FAILED ({e})")
        return 0

    # Get or create season
    conn.execute("""
        INSERT OR IGNORE INTO seasons (year, start_date, end_date)
        VALUES (?, ?, ?)
    """, (year, f"{year}-08-01", f"{year+1}-05-31"))
    conn.commit()
    season_id = conn.execute("SELECT id FROM seasons WHERE year=?", (year,)).fetchone()[0]

    # Parse CSV
    content = resp.content.decode("latin-1")
    reader = csv.DictReader(io.StringIO(content))

    inserted = 0
    matches_data = []

    for row in reader:
        try:
            home = row.get("HomeTeam", "").strip()
            away = row.get("AwayTeam", "").strip()
            if not home or not away:
                continue

            fthg = row.get("FTHG", "").strip()
            ftag = row.get("FTAG", "").strip()
            hthg = row.get("HTHG", "").strip()
            htag = row.get("HTAG", "").strip()
            ftr  = row.get("FTR", "").strip()   # H, D, A
            date = parse_date(row.get("Date", ""))

            if not fthg or not ftag or not ftr:
                continue

            home_id = get_or_create_team(conn, home)
            away_id = get_or_create_team(conn, away)

            home_g = int(fthg)
            away_g = int(ftag)
            home_ht = int(hthg) if hthg else None
            away_ht = int(htag) if htag else None

            winner = "HOME_TEAM" if ftr == "H" else "AWAY_TEAM" if ftr == "A" else "DRAW"

            conn.execute("""
                INSERT OR IGNORE INTO matches (
                    season_id, status, utc_date,
                    home_team_id, away_team_id,
                    home_score_ft, away_score_ft,
                    home_score_ht, away_score_ht,
                    winner
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                season_id, "FINISHED", date,
                home_id, away_id,
                home_g, away_g,
                home_ht, away_ht,
                winner
            ))
            inserted += 1
            matches_data.append((home_id, away_id, home_g, away_g, winner))

        except (ValueError, KeyError):
            continue

    conn.commit()
    print(f"  {inserted} matches")
    return season_id, inserted


def assign_matchdays(conn, season_id):
    """
    Estimate matchdays by ordering matches chronologically
    and grouping into rounds of 10 (20 teams = 10 games per matchday).
    """
    matches = conn.execute("""
        SELECT id, utc_date, home_team_id, away_team_id
        FROM matches
        WHERE season_id=? AND status='FINISHED'
        ORDER BY utc_date
    """, (season_id,)).fetchall()

    # Group by date proximity into matchdays
    matchday = 1
    teams_played = set()

    for mid, date, htid, atid in matches:
        if htid in teams_played or atid in teams_played:
            matchday += 1
            teams_played = set()

        teams_played.add(htid)
        teams_played.add(atid)

        conn.execute("UPDATE matches SET matchday=? WHERE id=?", (matchday, mid))

    conn.commit()


def compute_standings(conn, season_id):
    """Build standings table from match results."""
    matches = conn.execute("""
        SELECT matchday, home_team_id, away_team_id,
               home_score_ft, away_score_ft, winner
        FROM matches
        WHERE season_id=? AND status='FINISHED'
        ORDER BY matchday
    """, (season_id,)).fetchall()

    # Running totals
    totals = {}

    for md, htid, atid, hg, ag, winner in matches:
        for tid in [htid, atid]:
            if tid not in totals:
                totals[tid] = {"w":0,"d":0,"l":0,"gf":0,"ga":0,"pts":0}

        if winner == "HOME_TEAM":
            totals[htid]["w"] += 1; totals[htid]["pts"] += 3
            totals[atid]["l"] += 1
        elif winner == "AWAY_TEAM":
            totals[atid]["w"] += 1; totals[atid]["pts"] += 3
            totals[htid]["l"] += 1
        else:
            totals[htid]["d"] += 1; totals[htid]["pts"] += 1
            totals[atid]["d"] += 1; totals[atid]["pts"] += 1

        totals[htid]["gf"] += hg or 0; totals[htid]["ga"] += ag or 0
        totals[atid]["gf"] += ag or 0; totals[atid]["ga"] += hg or 0

        # Snapshot standings at this matchday
        sorted_teams = sorted(
            totals.items(),
            key=lambda x: (-x[1]["pts"], -(x[1]["gf"]-x[1]["ga"]), -x[1]["gf"])
        )

        for pos, (tid, t) in enumerate(sorted_teams, 1):
            pg = t["w"] + t["d"] + t["l"]
            conn.execute("""
                INSERT OR REPLACE INTO standings (
                    season_id, matchday, team_id, position, played_games,
                    won, draw, lost, points, goals_for, goals_against, goal_difference
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                season_id, md, tid, pos, pg,
                t["w"], t["d"], t["l"], t["pts"],
                t["gf"], t["ga"], t["gf"] - t["ga"]
            ))

    conn.commit()


def compute_team_form(conn, season_id):
    c = conn.cursor()
    teams = c.execute("""
        SELECT DISTINCT home_team_id FROM matches
        WHERE season_id=? AND status='FINISHED'
    """, (season_id,)).fetchall()

    max_md = c.execute("""
        SELECT MAX(matchday) FROM matches
        WHERE season_id=? AND status='FINISHED'
    """, (season_id,)).fetchone()[0] or 0

    for (team_id,) in teams:
        for md in range(1, max_md + 1):
            past = c.execute("""
                SELECT
                    CASE WHEN home_team_id=? THEN home_score_ft ELSE away_score_ft END,
                    CASE WHEN home_team_id=? THEN away_score_ft ELSE home_score_ft END,
                    CASE WHEN home_team_id=? THEN 'home' ELSE 'away' END,
                    winner
                FROM matches
                WHERE season_id=? AND status='FINISHED'
                  AND (home_team_id=? OR away_team_id=?)
                  AND matchday < ?
                ORDER BY matchday DESC
            """, (team_id,team_id,team_id,season_id,team_id,team_id,md)).fetchall()

            def win(r):
                return (r[3]=="HOME_TEAM" and r[2]=="home") or (r[3]=="AWAY_TEAM" and r[2]=="away")

            def calc(rows, n, venue=None):
                s = [r for r in rows if venue is None or r[2]==venue][:n]
                w = sum(1 for r in s if win(r))
                d = sum(1 for r in s if r[3]=="DRAW")
                l = len(s)-w-d
                gf = sum(r[0] or 0 for r in s)
                ga = sum(r[1] or 0 for r in s)
                return w,d,l,gf,ga

            l5=calc(past,5); l10=calc(past,10)
            h5=calc(past,5,"home"); a5=calc(past,5,"away")

            c.execute("""
                INSERT OR REPLACE INTO team_form (
                    team_id,season_id,as_of_matchday,
                    last5_wins,last5_draws,last5_losses,last5_gf,last5_ga,
                    last10_wins,last10_draws,last10_losses,last10_gf,last10_ga,
                    home_last5_wins,home_last5_gf,home_last5_ga,
                    away_last5_wins,away_last5_gf,away_last5_ga
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (team_id,season_id,md,*l5,*l10,h5[0],h5[3],h5[4],a5[0],a5[3],a5[4]))

    conn.commit()


def compute_h2h(conn, season_id):
    c = conn.cursor()
    matches = c.execute("""
        SELECT home_team_id, away_team_id, home_score_ft, away_score_ft, winner
        FROM matches WHERE season_id=? AND status='FINISHED'
    """, (season_id,)).fetchall()

    h2h = {}
    for htid,atid,hg,ag,winner in matches:
        k=(htid,atid)
        if k not in h2h:
            h2h[k]={"hw":0,"aw":0,"d":0,"n":0,"hg":0,"ag":0}
        h2h[k]["n"]+=1; h2h[k]["hg"]+=hg or 0; h2h[k]["ag"]+=ag or 0
        if winner=="HOME_TEAM": h2h[k]["hw"]+=1
        elif winner=="AWAY_TEAM": h2h[k]["aw"]+=1
        else: h2h[k]["d"]+=1

    for (htid,atid),d in h2h.items():
        n=d["n"]
        c.execute("""
            INSERT OR REPLACE INTO head_to_head (
                team_a_id,team_b_id,season_id,
                home_wins,away_wins,draws,total_matches,
                avg_goals_home,avg_goals_away,last_updated
            ) VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """, (htid,atid,season_id,d["hw"],d["aw"],d["d"],n,
              d["hg"]/n if n else 0, d["ag"]/n if n else 0))
    conn.commit()


def build_match_features(conn, season_id):
    c = conn.cursor()
    matches = c.execute("""
        SELECT id,matchday,utc_date,home_team_id,away_team_id,
               home_score_ft,away_score_ft,winner
        FROM matches WHERE season_id=? AND status='FINISHED'
        ORDER BY matchday
    """, (season_id,)).fetchall()

    def get_form(tid, md):
        r=c.execute("""
            SELECT last5_wins,last5_draws,last5_losses,last5_gf,last5_ga
            FROM team_form WHERE team_id=? AND season_id=? AND as_of_matchday<=?
            ORDER BY as_of_matchday DESC LIMIT 1
        """, (tid,season_id,md)).fetchone()
        return r or (0,0,0,0,0)

    def get_standing(tid, md):
        r=c.execute("""
            SELECT position,points,goal_difference FROM standings
            WHERE team_id=? AND season_id=? AND matchday<=?
            ORDER BY matchday DESC LIMIT 1
        """, (tid,season_id,md)).fetchone()
        return r or (10,0,0)

    def get_h2h(htid, atid):
        r=c.execute("""
            SELECT home_wins,away_wins,draws FROM head_to_head
            WHERE team_a_id=? AND team_b_id=? AND season_id=?
        """, (htid,atid,season_id)).fetchone()
        return r or (0,0,0)

    upserted=0
    for mid,md,date,htid,atid,hg,ag,winner in matches:
        hf=get_form(htid,md); af=get_form(atid,md)
        hs=get_standing(htid,md-1); as_=get_standing(atid,md-1)
        h2h=get_h2h(htid,atid)

        result="HOME" if winner=="HOME_TEAM" else "AWAY" if winner=="AWAY_TEAM" else "DRAW"
        o25=1 if (hg or 0)+(ag or 0)>2.5 else 0
        btts=1 if (hg or 0)>0 and (ag or 0)>0 else 0

        c.execute("""
            INSERT OR REPLACE INTO match_features (
                match_id,season_id,matchday,utc_date,
                home_team_id,away_team_id,
                home_l5_wins,home_l5_draws,home_l5_losses,home_l5_gf,home_l5_ga,home_l5_pts,
                away_l5_wins,away_l5_draws,away_l5_losses,away_l5_gf,away_l5_ga,away_l5_pts,
                home_position,away_position,home_points,away_points,home_gd,away_gd,
                h2h_home_wins,h2h_away_wins,h2h_draws,
                result,home_goals,away_goals,over_2_5,btts
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            mid,season_id,md,date,htid,atid,
            hf[0],hf[1],hf[2],hf[3],hf[4],hf[0]*3+hf[1],
            af[0],af[1],af[2],af[3],af[4],af[0]*3+af[1],
            hs[0],as_[0],hs[1],as_[1],hs[2],as_[2],
            h2h[0],h2h[1],h2h[2],
            result,hg,ag,o25,btts
        ))
        upserted+=1

    conn.commit()
    return upserted


def main():
    print("="*60)
    print("PREMIER LEAGUE HISTORICAL DATA DOWNLOADER")
    print("Source: football-data.co.uk (free, no API key needed)")
    print("="*60)

    conn = init_db()

    # Ask which seasons to download
    print("\nWhich seasons do you want? (more = better model)")
    print("Options:")
    print("  1 - Last 5 seasons (2019-2024) — quick download")
    print("  2 - Last 10 seasons (2014-2024) — recommended")
    print("  3 - All available (2000-2024) — best model, slower")
    print("  4 - Custom range")

    choice = input("\nEnter 1, 2, 3 or 4: ").strip()

    if choice == "1":
        years = list(range(2019, 2024))
    elif choice == "2":
        years = list(range(2014, 2024))
    elif choice == "3":
        years = list(range(2000, 2024))
    elif choice == "4":
        start = int(input("Start year (e.g. 2010): "))
        end   = int(input("End year (e.g. 2023): "))
        years = list(range(start, end+1))
    else:
        years = list(range(2014, 2024))

    years = [y for y in years if y in SEASONS]
    print(f"\nDownloading {len(years)} seasons...\n")

    total_matches = 0
    processed_seasons = []

    for year in years:
        code = SEASONS[year]
        result = download_season(conn, year, code)
        if result:
            season_id, count = result
            total_matches += count
            processed_seasons.append(season_id)

    print(f"\nDownloaded {total_matches} matches across {len(processed_seasons)} seasons")
    print("\nProcessing matchdays and features (this takes a few minutes)...")

    for i, season_id in enumerate(processed_seasons, 1):
        year = conn.execute("SELECT year FROM seasons WHERE id=?", (season_id,)).fetchone()[0]
        print(f"  [{i}/{len(processed_seasons)}] Season {year}/{year+1}...", end=" ", flush=True)
        assign_matchdays(conn, season_id)
        compute_standings(conn, season_id)
        compute_h2h(conn, season_id)
        compute_team_form(conn, season_id)
        mf = build_match_features(conn, season_id)
        print(f"{mf} features built")

    # Summary
    total_mf = conn.execute("SELECT COUNT(*) FROM match_features WHERE result IS NOT NULL").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"DONE! {total_mf} match feature rows ready for training")
    print(f"{'='*60}")
    print(f"\nNext steps:")
    print(f"  1. Run: python train_fixed.py    (train the neural network)")
    print(f"  2. Run: python pl_data_collector.py --mode live  (get upcoming fixtures)")
    print(f"  3. Run: python predict.py        (predict this week's matches)")

    conn.close()
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
