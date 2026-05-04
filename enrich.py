"""
Live Fixture Enrichment
========================
Adds xG history, referee stats, weather forecasts and player
availability to upcoming fixtures before prediction.

Run: python enrich.py
Then: python pl.py --predict
      python dashboard.py
      python valuefinder.py
"""

import sqlite3
import requests
import json
import re
import time
import math
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = "premier_league.db"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Premier League stadium coordinates for weather
STADIUM_COORDS = {
    "Arsenal":             (51.5549, -0.1084),
    "Aston Villa":         (52.5090, -1.8847),
    "Bournemouth":         (50.7352, -1.8383),
    "Brentford":           (51.4883, -0.2886),
    "Brighton":            (50.8617, -0.0837),
    "Burnley":             (53.7893, -2.2307),
    "Chelsea":             (51.4816, -0.1910),
    "Crystal Palace":      (51.3983, -0.0855),
    "Everton":             (53.4388, -2.9662),
    "Fulham":              (51.4749, -0.2214),
    "Leeds":               (53.7773, -1.5724),
    "Leicester":           (52.6204, -1.1424),
    "Liverpool":           (53.4308, -2.9608),
    "Man City":            (53.4831, -2.2004),
    "Man United":          (53.4631, -2.2913),
    "Newcastle":           (54.9756, -1.6217),
    "Nottingham Forest":   (52.9400, -1.1326),
    "Southampton":         (50.9058, -1.3914),
    "Sunderland":          (54.9145, -1.3882),
    "Tottenham":           (51.6044, -0.0665),
    "West Ham":            (51.5386, -0.0164),
    "Wolves":              (52.5900, -2.1300),
}


# ── DATABASE SETUP ────────────────────────────────────────────────────────────
def init_enrichment_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS match_xg (
            match_id    INTEGER PRIMARY KEY REFERENCES matches(id),
            home_xg     REAL DEFAULT 0,
            away_xg     REAL DEFAULT 0,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS referee_stats (
            referee     TEXT PRIMARY KEY,
            matches     INTEGER DEFAULT 0,
            yellows_pg  REAL DEFAULT 0,
            reds_pg     REAL DEFAULT 0,
            pens_pg     REAL DEFAULT 0,
            home_win_pct REAL DEFAULT 0,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS match_weather (
            match_id        INTEGER PRIMARY KEY REFERENCES matches(id),
            temperature_c   REAL,
            precipitation_mm REAL,
            wind_speed_kmh  REAL,
            weather_code    INTEGER,
            weather_desc    TEXT,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS fixture_enrichment (
            match_id            INTEGER PRIMARY KEY REFERENCES matches(id),
            home_xg_avg_l5      REAL DEFAULT 0,
            away_xg_avg_l5      REAL DEFAULT 0,
            home_xga_avg_l5     REAL DEFAULT 0,
            away_xga_avg_l5     REAL DEFAULT 0,
            home_xg_diff_l5     REAL DEFAULT 0,
            away_xg_diff_l5     REAL DEFAULT 0,
            referee             TEXT,
            ref_yellows_pg      REAL DEFAULT 0,
            ref_reds_pg         REAL DEFAULT 0,
            ref_home_win_pct    REAL DEFAULT 0,
            temperature_c       REAL DEFAULT 15,
            precipitation_mm    REAL DEFAULT 0,
            wind_speed_kmh      REAL DEFAULT 10,
            is_wet              INTEGER DEFAULT 0,
            is_cold             INTEGER DEFAULT 0,
            is_windy            INTEGER DEFAULT 0,
            home_players_out    INTEGER DEFAULT 0,
            away_players_out    INTEGER DEFAULT 0,
            home_key_out        INTEGER DEFAULT 0,
            away_key_out        INTEGER DEFAULT 0,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    print("[DB] Enrichment tables ready")


# ── XG DATA ───────────────────────────────────────────────────────────────────
def fetch_understat_xg(season="2024"):
    """Fetch xG data from understat.com for a given season."""
    url = f"https://understat.com/league/EPL/{season}"
    print(f"  Fetching xG from understat ({season})...", end=" ", flush=True)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        html = resp.text

        # Extract match data
        pattern = r"var datesData\s*=\s*JSON\.parse\('(.+?)'\)"
        match = re.search(pattern, html)
        if not match:
            print("not found")
            return []

        raw = match.group(1)
        try:
            raw = raw.encode("raw_unicode_escape").decode("unicode_escape")
        except:
            raw = bytes(raw, "utf-8").decode("unicode_escape")

        matches = json.loads(raw)
        print(f"{len(matches)} matches")
        time.sleep(3)
        return matches
    except Exception as e:
        print(f"failed ({e})")
        return []


def save_xg_to_db(conn, understat_matches):
    """Match understat fixtures to our DB and save xG values."""
    saved = 0
    for m in understat_matches:
        if m.get("isResult") != True:
            continue

        h_team = m.get("h", {}).get("title", "")
        a_team = m.get("a", {}).get("title", "")
        h_xg   = float(m.get("xG", {}).get("h", 0) or 0)
        a_xg   = float(m.get("xG", {}).get("a", 0) or 0)
        date   = m.get("datetime", "")[:10]

        # Find matching teams in DB
        h_row = conn.execute(
            "SELECT id FROM teams WHERE name LIKE ? OR name LIKE ? LIMIT 1",
            (f"%{h_team.split()[0]}%", f"%{h_team}%")
        ).fetchone()
        a_row = conn.execute(
            "SELECT id FROM teams WHERE name LIKE ? OR name LIKE ? LIMIT 1",
            (f"%{a_team.split()[0]}%", f"%{a_team}%")
        ).fetchone()

        if not h_row or not a_row:
            continue

        # Find match in our DB
        match_row = conn.execute("""
            SELECT id FROM matches
            WHERE home_team_id=? AND away_team_id=?
            AND utc_date LIKE ?
            AND status='FINISHED'
            LIMIT 1
        """, (h_row[0], a_row[0], f"{date}%")).fetchone()

        if not match_row:
            continue

        conn.execute("""
            INSERT OR REPLACE INTO match_xg (match_id, home_xg, away_xg)
            VALUES (?,?,?)
        """, (match_row[0], h_xg, a_xg))
        saved += 1

    conn.commit()
    print(f"  Saved xG for {saved} matches")
    return saved


def compute_xg_features(conn):
    """Load xG from team_xg table (populated by xg.py)."""
    matches = conn.execute("""
        SELECT m.id, m.home_team_id, m.away_team_id
        FROM matches m
        WHERE m.status IN ('TIMED','SCHEDULED')
        ORDER BY m.utc_date
    """).fetchall()

    print(f"  Applying xG to {len(matches)} upcoming fixtures...")

    for mid, htid, atid in matches:
        h = conn.execute("SELECT xg_for, xg_against FROM team_xg WHERE team_id=?", (htid,)).fetchone()
        a = conn.execute("SELECT xg_for, xg_against FROM team_xg WHERE team_id=?", (atid,)).fetchone()

        h_xgf = h[0] if h else 1.2
        h_xga = h[1] if h else 1.2
        a_xgf = a[0] if a else 1.2
        a_xga = a[1] if a else 1.2

        home_xg = round((h_xgf + a_xga) / 2, 3)
        away_xg = round((a_xgf + h_xga) / 2, 3)

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
        """, (mid, home_xg, away_xg, h_xga, a_xga,
              round(h_xgf-h_xga,3), round(a_xgf-a_xga,3)))

    conn.commit()


# ── REFEREE STATS ─────────────────────────────────────────────────────────────
def build_referee_stats(conn):
    """Build referee statistics from historical CSV data."""
    print("  Building referee stats from historical data...")

    # Check if we have referee data in match_stats
    has_ref = conn.execute("""
        SELECT COUNT(*) FROM pragma_table_info('matches')
        WHERE name='referee'
    """).fetchone()[0]

    if not has_ref:
        # Add referee column to matches if not present
        try:
            conn.execute("ALTER TABLE matches ADD COLUMN referee TEXT")
            conn.commit()
        except:
            pass

    # Download current season CSV which has referee data
    seasons_to_check = ["2324", "2425"]
    ref_data = defaultdict(lambda: {"matches":0,"yellows":0,"reds":0,"pens":0,"home_wins":0})

    for code in seasons_to_check:
        url = f"https://www.football-data.co.uk/mmz4281/{code}/E0.csv"
        print(f"    Fetching {code}...", end=" ", flush=True)
        try:
            import csv, io
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.content.decode("latin-1")))
            count = 0
            for row in reader:
                ref = row.get("Referee","").strip()
                if not ref:
                    continue
                def si(k): 
                    try: return int(row.get(k,"0") or 0)
                    except: return 0
                ref_data[ref]["matches"]   += 1
                ref_data[ref]["yellows"]   += si("HY") + si("AY")
                ref_data[ref]["reds"]      += si("HR") + si("AR")
                ref_data[ref]["home_wins"] += 1 if row.get("FTR","") == "H" else 0

                # Update match referee in DB
                home = row.get("HomeTeam","").strip()
                away = row.get("AwayTeam","").strip()
                date = row.get("Date","").strip()
                if home and away and ref:
                    h_row = conn.execute("SELECT id FROM teams WHERE name LIKE ? LIMIT 1",(f"%{home.split()[0]}%",)).fetchone()
                    a_row = conn.execute("SELECT id FROM teams WHERE name LIKE ? LIMIT 1",(f"%{away.split()[0]}%",)).fetchone()
                    if h_row and a_row:
                        conn.execute("""
                            UPDATE matches SET referee=?
                            WHERE home_team_id=? AND away_team_id=?
                            AND referee IS NULL
                        """, (ref, h_row[0], a_row[0]))
                count += 1
            print(f"{count} rows")
            time.sleep(2)
        except Exception as e:
            print(f"failed ({e})")

    conn.commit()

    # Save referee stats
    for ref, d in ref_data.items():
        n = max(d["matches"], 1)
        conn.execute("""
            INSERT OR REPLACE INTO referee_stats
            (referee, matches, yellows_pg, reds_pg, home_win_pct)
            VALUES (?,?,?,?,?)
        """, (
            ref, d["matches"],
            round(d["yellows"]/n, 2),
            round(d["reds"]/n, 3),
            round(d["home_wins"]/n, 3),
        ))

    conn.commit()
    print(f"  Saved stats for {len(ref_data)} referees")

    # Show top card-happy referees
    top = conn.execute("""
        SELECT referee, matches, yellows_pg, reds_pg
        FROM referee_stats WHERE matches >= 5
        ORDER BY yellows_pg DESC LIMIT 5
    """).fetchall()
    if top:
        print("  Most card-prone referees:")
        for r in top:
            print(f"    {r[0]:<25} {r[1]:>3} games  {r[2]:.1f} Y/g  {r[3]:.2f} R/g")


def assign_referee_to_fixtures(conn):
    """Try to assign likely referee to upcoming fixtures."""
    upcoming = conn.execute("""
        SELECT id, home_team_id, away_team_id FROM matches
        WHERE status IN ('TIMED','SCHEDULED')
    """).fetchall()

    # Get average referee stats as default
    avg = conn.execute("""
        SELECT AVG(yellows_pg), AVG(reds_pg), AVG(home_win_pct)
        FROM referee_stats WHERE matches >= 5
    """).fetchone() or (3.5, 0.08, 0.46)

    for mid, htid, atid in upcoming:
        conn.execute("""
            INSERT OR REPLACE INTO fixture_enrichment
            (match_id, ref_yellows_pg, ref_reds_pg, ref_home_win_pct)
            VALUES (?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET
                ref_yellows_pg=excluded.ref_yellows_pg,
                ref_reds_pg=excluded.ref_reds_pg,
                ref_home_win_pct=excluded.ref_home_win_pct
        """, (mid, float(avg[0] or 3.5), float(avg[1] or 0.08), float(avg[2] or 0.46)))

    conn.commit()
    print(f"  Assigned referee stats to {len(upcoming)} fixtures")


# ── WEATHER ───────────────────────────────────────────────────────────────────
WEATHER_CODES = {
    0:"Clear", 1:"Mainly clear", 2:"Partly cloudy", 3:"Overcast",
    45:"Foggy", 48:"Icy fog", 51:"Light drizzle", 53:"Drizzle",
    55:"Heavy drizzle", 61:"Light rain", 63:"Rain", 65:"Heavy rain",
    71:"Light snow", 73:"Snow", 75:"Heavy snow", 80:"Rain showers",
    81:"Heavy showers", 82:"Violent showers", 95:"Thunderstorm",
}

def fetch_weather(lat, lon, date_str):
    """Fetch weather forecast from Open-Meteo (free, no key needed)."""
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude":  lat,
            "longitude": lon,
            "daily": "temperature_2m_max,precipitation_sum,windspeed_10m_max,weathercode",
            "timezone": "Europe/London",
            "start_date": date_str,
            "end_date":   date_str,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})

        temp  = daily.get("temperature_2m_max", [15])[0]
        precip= daily.get("precipitation_sum",  [0])[0]
        wind  = daily.get("windspeed_10m_max",  [10])[0]
        code  = daily.get("weathercode",        [0])[0]

        return {
            "temperature_c":    float(temp  or 15),
            "precipitation_mm": float(precip or 0),
            "wind_speed_kmh":   float(wind   or 10),
            "weather_code":     int(code     or 0),
            "weather_desc":     WEATHER_CODES.get(int(code or 0), "Unknown"),
        }
    except Exception as e:
        return {"temperature_c":15,"precipitation_mm":0,"wind_speed_kmh":10,"weather_code":0,"weather_desc":"Unknown"}


def fetch_all_weather(conn):
    """Fetch weather for all upcoming fixtures."""
    upcoming = conn.execute("""
        SELECT m.id, m.utc_date, ht.name AS home_team
        FROM matches m
        JOIN teams ht ON ht.id = m.home_team_id
        WHERE m.status IN ('TIMED','SCHEDULED')
        AND m.utc_date IS NOT NULL
        ORDER BY m.utc_date
    """).fetchall()

    print(f"  Fetching weather for {len(upcoming)} fixtures...")
    fetched = 0

    for mid, date, home_team in upcoming:
        if not date:
            continue
        date_str = date[:10]

        # Check if too far in future (Open-Meteo only forecasts 16 days)
        try:
            match_date = datetime.strptime(date_str, "%Y-%m-%d")
            days_ahead  = (match_date - datetime.now()).days
            if days_ahead > 15:
                continue  # Too far ahead for reliable forecast
        except:
            continue

        coords = STADIUM_COORDS.get(home_team)
        if not coords:
            # Default to London
            coords = (51.5074, -0.1278)

        weather = fetch_weather(coords[0], coords[1], date_str)

        is_wet   = 1 if weather["precipitation_mm"] > 2 else 0
        is_cold  = 1 if weather["temperature_c"] < 5 else 0
        is_windy = 1 if weather["wind_speed_kmh"] > 40 else 0

        conn.execute("""
            INSERT OR REPLACE INTO match_weather
            (match_id, temperature_c, precipitation_mm, wind_speed_kmh, weather_code, weather_desc)
            VALUES (?,?,?,?,?,?)
        """, (mid, weather["temperature_c"], weather["precipitation_mm"],
              weather["wind_speed_kmh"], weather["weather_code"], weather["weather_desc"]))

        conn.execute("""
            INSERT OR REPLACE INTO fixture_enrichment
            (match_id, temperature_c, precipitation_mm, wind_speed_kmh,
             is_wet, is_cold, is_windy)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET
                temperature_c=excluded.temperature_c,
                precipitation_mm=excluded.precipitation_mm,
                wind_speed_kmh=excluded.wind_speed_kmh,
                is_wet=excluded.is_wet,
                is_cold=excluded.is_cold,
                is_windy=excluded.is_windy
        """, (mid, weather["temperature_c"], weather["precipitation_mm"],
              weather["wind_speed_kmh"], is_wet, is_cold, is_windy))

        fetched += 1
        time.sleep(0.5)  # Be polite to Open-Meteo

    conn.commit()
    print(f"  Fetched weather for {fetched} fixtures")

    # Show weather summary
    weather_rows = conn.execute("""
        SELECT ht.name, m.utc_date, mw.temperature_c, mw.precipitation_mm,
               mw.wind_speed_kmh, mw.weather_desc
        FROM match_weather mw
        JOIN matches m ON m.id = mw.match_id
        JOIN teams ht ON ht.id = m.home_team_id
        WHERE m.status IN ('TIMED','SCHEDULED')
        ORDER BY m.utc_date LIMIT 10
    """).fetchall()

    if weather_rows:
        print("\n  Upcoming fixture weather:")
        print(f"  {'Venue':<20} {'Date':>10} {'Temp':>5} {'Rain':>5} {'Wind':>5} {'Conditions'}")
        print(f"  {'-'*65}")
        for r in weather_rows:
            print(f"  {r[0]:<20} {r[1][:10]:>10} {r[2]:>4.0f}C {r[3]:>4.1f}mm {r[4]:>4.0f}kmh {r[5]}")


# ── AVAILABILITY ──────────────────────────────────────────────────────────────
def update_availability(conn):
    """Re-fetch latest injury/availability data from FPL."""
    print("  Updating player availability from FPL...")
    FPL_API = "https://fantasy.premierleague.com/api/bootstrap-static/"
    FPL_TO_DB = {
        "Man City":"Man City","Man Utd":"Man United",
        "Spurs":"Tottenham","Nott'm Forest":"Nottingham Forest",
    }

    try:
        resp = requests.get(FPL_API, headers=HEADERS, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f"  Failed: {e}"); return

    fpl_teams = {t["id"]: t["name"] for t in data.get("teams",[])}
    by_team   = defaultdict(lambda: {"out":0,"key_out":0,"total":0})

    for p in data.get("elements",[]):
        mins   = int(p.get("minutes",0))
        if mins < 900: continue
        ftn    = fpl_teams.get(p.get("team"),"")
        dbn    = FPL_TO_DB.get(ftn, ftn)
        status = p.get("status","a")
        is_out = status in ("i","u","s")
        is_key = mins >= 2000
        by_team[dbn]["total"] += 1
        if is_out:
            by_team[dbn]["out"] += 1
            if is_key: by_team[dbn]["key_out"] += 1

    # Update fixture_enrichment for upcoming matches
    upcoming = conn.execute("""
        SELECT m.id, m.home_team_id, m.away_team_id, ht.name, at.name
        FROM matches m
        JOIN teams ht ON ht.id = m.home_team_id
        JOIN teams at ON at.id = m.away_team_id
        WHERE m.status IN ('TIMED','SCHEDULED')
    """).fetchall()

    for mid, htid, atid, hname, aname in upcoming:
        h = by_team.get(hname, {"out":0,"key_out":0})
        a = by_team.get(aname, {"out":0,"key_out":0})
        conn.execute("""
            INSERT OR REPLACE INTO fixture_enrichment
            (match_id, home_players_out, away_players_out, home_key_out, away_key_out)
            VALUES (?,?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET
                home_players_out=excluded.home_players_out,
                away_players_out=excluded.away_players_out,
                home_key_out=excluded.home_key_out,
                away_key_out=excluded.away_key_out
        """, (mid, h["out"], a["out"], h["key_out"], a["key_out"]))

    conn.commit()

    # Show teams with injuries
    injuries = [(t, d["key_out"], d["out"]) for t, d in by_team.items() if d["out"] > 0]
    if injuries:
        print("  Current injuries:")
        for t, k, o in sorted(injuries, key=lambda x:-x[1]):
            print(f"    {t:<25} {k} key / {o} total out")


# ── PRINT ENRICHMENT SUMMARY ──────────────────────────────────────────────────
def print_summary(conn):
    fixtures = conn.execute("""
        SELECT ht.name, at.name, m.utc_date,
               fe.home_xg_avg_l5, fe.away_xg_avg_l5,
               fe.ref_yellows_pg,
               fe.temperature_c, fe.precipitation_mm,
               fe.home_key_out, fe.away_key_out,
               fe.is_wet, fe.is_windy
        FROM fixture_enrichment fe
        JOIN matches m ON m.id = fe.match_id
        JOIN teams ht ON ht.id = m.home_team_id
        JOIN teams at ON at.id = m.away_team_id
        WHERE m.status IN ('TIMED','SCHEDULED')
        ORDER BY m.utc_date
        LIMIT 10
    """).fetchall()

    print("\n" + "="*90)
    print("ENRICHED FIXTURE DATA")
    print("="*90)
    print(f"{'Fixture':<34} {'Date':>10} {'xG H':>5} {'xG A':>5} {'Y/g':>4} {'Temp':>5} {'Rain':>5} {'H out':>6} {'A out':>6}")
    print("-"*90)

    for r in fixtures:
        fixture  = f"{r[0]} vs {r[1]}"[:33]
        wet_flag = " 🌧" if r[10] else ""
        wind_flag= " 💨" if r[11] else ""
        h_inj    = f"⚠{r[8]}" if r[8] > 0 else "-"
        a_inj    = f"⚠{r[9]}" if r[9] > 0 else "-"
        print(f"{fixture:<34} {str(r[2])[:10]:>10} {r[3]:>5.2f} {r[4]:>5.2f} "
              f"{r[5]:>4.1f} {r[6]:>4.0f}C {r[7]:>4.1f}mm {h_inj:>6} {a_inj:>6}{wet_flag}{wind_flag}")
    print("="*90)


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("="*60)
    print("FIXTURE ENRICHMENT")
    print("xG | Referee Stats | Weather | Availability")
    print("="*60)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    init_enrichment_tables(conn)

    print("\n[1/4] xG data from Understat...")
    xg_matches = fetch_understat_xg("2024")
    if xg_matches:
        save_xg_to_db(conn, xg_matches)
        compute_xg_features(conn)
    else:
        print("  Understat unavailable — using default xG values")
        compute_xg_features(conn)

    print("\n[2/4] Referee statistics...")
    build_referee_stats(conn)
    assign_referee_to_fixtures(conn)

    print("\n[3/4] Weather forecasts (Open-Meteo)...")
    fetch_all_weather(conn)

    print("\n[4/4] Player availability (FPL)...")
    update_availability(conn)

    print_summary(conn)
    conn.close()

    print("\nDone! Now run:")
    print("  python pl.py --predict")
    print("  python dashboard.py")
    print("  python valuefinder.py")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
