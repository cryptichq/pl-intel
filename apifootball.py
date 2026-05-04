"""
API-Football Integration
=========================
Fetches from api-football.com:
  - Line-ups (1hr before kickoff) -> feeds into player predictions
  - Live scores during matches
  - Goals and cards as they happen

Free tier: 100 calls/day
PL season uses ~3-5 calls per matchday

Run:
    python apifootball.py --lineups      Fetch line-ups for today's fixtures
    python apifootball.py --live         Fetch live scores right now
    python apifootball.py --fixtures     Fetch upcoming PL fixture IDs
    python apifootball.py --all          Lineups + live scores
"""

import requests
import json
import sqlite3
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH  = "premier_league.db"
KEY_FILE = "apifootball_key.txt"
BASE_URL = "https://v3.football.api-sports.io"
PL_ID    = 39   # Premier League ID in api-football
SEASON   = 2025 # 2025/26 season = 2025

# Load API key
if os.path.exists(KEY_FILE):
    API_KEY = open(KEY_FILE).read().strip()
else:
    API_KEY = "8723f0a33f1d63f19daad2dec90c5857"
    # Save for future use
    open(KEY_FILE, "w").write(API_KEY)

HEADERS = {"x-apisports-key": API_KEY}

# Team name mapping from api-football to our DB
API_TO_DB = {
    "Arsenal":                  "Arsenal",
    "Aston Villa":              "Aston Villa",
    "Bournemouth":              "Bournemouth",
    "Brentford":                "Brentford",
    "Brighton":                 "Brighton",
    "Burnley":                  "Burnley",
    "Chelsea":                  "Chelsea",
    "Crystal Palace":           "Crystal Palace",
    "Everton":                  "Everton",
    "Fulham":                   "Fulham",
    "Leeds":                    "Leeds",
    "Liverpool":                "Liverpool",
    "Manchester City":          "Man City",
    "Manchester United":        "Man United",
    "Newcastle United":         "Newcastle",
    "Nottingham Forest":        "Nottingham Forest",
    "Tottenham":                "Tottenham",
    "Sunderland":               "Sunderland",
    "West Ham":                 "West Ham",
    "Wolverhampton Wanderers":  "Wolves",
}


def api_get(endpoint, params={}):
    """Make API request with error handling."""
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("errors", {})
        if errors:
            print(f"  API error: {errors}")
            return []
        remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
        print(f"  [{remaining} calls remaining today]")
        return data.get("response", [])
    except Exception as e:
        print(f"  Request failed: {e}")
        return []


# ── FIXTURES ──────────────────────────────────────────────────────────────────
def fetch_pl_fixtures(days_ahead=14):
    """Fetch upcoming PL fixtures and save API fixture IDs to DB."""
    print(f"Fetching PL fixtures (next {days_ahead} days)...")
    today = datetime.now()
    end   = today + timedelta(days=days_ahead)

    fixtures = api_get("fixtures", {
        "league": PL_ID,
        "season": SEASON,
        "from":   today.strftime("%Y-%m-%d"),
        "to":     end.strftime("%Y-%m-%d"),
    })

    if not fixtures:
        print("  No fixtures found")
        return []

    conn = sqlite3.connect(DB_PATH)

    # Add api_fixture_id column if not present
    cols = [r[1] for r in conn.execute("PRAGMA table_info(matches)").fetchall()]
    if "api_fixture_id" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN api_fixture_id INTEGER")
        conn.commit()

    saved = 0
    print(f"\n  {'Fixture':<35} {'Date':>10} {'API ID':>8}")
    print(f"  {'-'*55}")

    for f in fixtures:
        home     = f["teams"]["home"]["name"]
        away     = f["teams"]["away"]["name"]
        date     = f["fixture"]["date"][:10]
        fix_id   = f["fixture"]["id"]
        status   = f["fixture"]["status"]["short"]

        home_db = API_TO_DB.get(home, home)
        away_db = API_TO_DB.get(away, away)

        # Find match in our DB
        row = conn.execute("""
            SELECT m.id FROM matches m
            JOIN teams ht ON ht.id = m.home_team_id
            JOIN teams at ON at.id = m.away_team_id
            WHERE ht.name=? AND at.name=?
            AND m.utc_date LIKE ?
        """, (home_db, away_db, f"{date}%")).fetchone()

        if row:
            conn.execute(
                "UPDATE matches SET api_fixture_id=? WHERE id=?",
                (fix_id, row[0])
            )
            saved += 1

        fix_str = f"{home_db} vs {away_db}"[:34]
        print(f"  {fix_str:<35} {date:>10} {fix_id:>8}")

    conn.commit()
    conn.close()
    print(f"\n  Saved API IDs for {saved} fixtures")
    return fixtures


# ── LINE-UPS ──────────────────────────────────────────────────────────────────
def fetch_lineups(fixture_id, fixture_label=""):
    """Fetch confirmed line-ups for a fixture."""
    print(f"  Fetching line-ups for {fixture_label} (ID: {fixture_id})...")
    lineups = api_get("fixtures/lineups", {"fixture": fixture_id})

    if not lineups:
        print("  No line-ups available yet (usually released 1hr before kickoff)")
        return None

    result = {}
    for team_data in lineups:
        team_name = team_data["team"]["name"]
        db_name   = API_TO_DB.get(team_name, team_name)
        formation = team_data.get("formation", "")
        coach     = team_data.get("coach", {}).get("name", "")

        starters = []
        for p in team_data.get("startXI", []):
            player = p.get("player", {})
            starters.append({
                "name":     player.get("name",""),
                "number":   player.get("number"),
                "pos":      player.get("pos",""),
                "grid":     player.get("grid",""),
            })

        subs = []
        for p in team_data.get("substitutes", []):
            player = p.get("player", {})
            subs.append({
                "name":   player.get("name",""),
                "number": player.get("number"),
                "pos":    player.get("pos",""),
            })

        result[db_name] = {
            "formation": formation,
            "coach":     coach,
            "starters":  starters,
            "subs":      subs,
        }

        print(f"\n  {db_name} ({formation}) — Coach: {coach}")
        print(f"  Starters:")
        for p in starters:
            print(f"    #{p['number']:<3} {p['name']:<25} {p['pos']}")
        print(f"  Subs: {', '.join(p['name'] for p in subs[:5])}")

    return result


def fetch_all_todays_lineups():
    """Fetch line-ups for all of today's PL fixtures."""
    print("\nFetching today's line-ups...")
    conn = sqlite3.connect(DB_PATH)
    today = datetime.now().strftime("%Y-%m-%d")

    fixtures = conn.execute("""
        SELECT m.id, m.api_fixture_id, ht.name, at.name, m.utc_date
        FROM matches m
        JOIN teams ht ON ht.id = m.home_team_id
        JOIN teams at ON at.id = m.away_team_id
        WHERE m.utc_date LIKE ?
        AND m.api_fixture_id IS NOT NULL
        AND m.status IN ('TIMED','SCHEDULED','IN_PLAY')
    """, (f"{today}%",)).fetchall()

    conn.close()

    if not fixtures:
        print("  No fixtures today with API IDs. Run --fixtures first.")
        return {}

    all_lineups = {}
    for mid, fix_id, home, away, date in fixtures:
        label = f"{home} vs {away}"
        lineup = fetch_lineups(fix_id, label)
        if lineup:
            all_lineups[label] = lineup

    # Save to file
    if all_lineups:
        with open("lineups.json", "w") as f:
            json.dump({
                "date":     today,
                "lineups":  all_lineups,
                "fetched_at": datetime.now().isoformat()
            }, f, indent=2)
        print(f"\n  Saved line-ups to lineups.json")

    return all_lineups


# ── LIVE SCORES ───────────────────────────────────────────────────────────────
def fetch_live_scores():
    """Fetch live PL scores right now."""
    print("Fetching live PL scores...")
    live = api_get("fixtures", {"league": PL_ID, "season": SEASON, "live": "all"})

    if not live:
        print("  No live matches right now")
        return []

    scores = []
    print(f"\n  {'Fixture':<35} {'Score':>7} {'Min':>5} {'Status'}")
    print(f"  {'-'*60}")

    for f in live:
        home    = API_TO_DB.get(f["teams"]["home"]["name"], f["teams"]["home"]["name"])
        away    = API_TO_DB.get(f["teams"]["away"]["name"], f["teams"]["away"]["name"])
        hg      = f["goals"]["home"] or 0
        ag      = f["goals"]["away"] or 0
        minute  = f["fixture"]["status"]["elapsed"] or 0
        status  = f["fixture"]["status"]["short"]
        fix_id  = f["fixture"]["id"]

        # Get events (goals, cards)
        events = fetch_events(fix_id)

        scores.append({
            "fixture":  f"{home} vs {away}",
            "home":     home,
            "away":     away,
            "home_goals": hg,
            "away_goals": ag,
            "minute":   minute,
            "status":   status,
            "events":   events,
        })

        print(f"  {home} vs {away:<20} {hg}-{ag:>2}    {minute}' {status}")
        for ev in events:
            print(f"    {ev['minute']}' {ev['type']}: {ev['player']} ({ev['team']})")

    # Save for site
    with open("live_scores.json", "w") as f:
        json.dump({
            "fetched_at": datetime.now().isoformat(),
            "scores": scores
        }, f, indent=2)
    print(f"\n  Saved to live_scores.json")
    return scores


def fetch_events(fixture_id):
    """Fetch goals and cards for a fixture."""
    events_raw = api_get("fixtures/events", {
        "fixture": fixture_id,
        "type":    "Goal,Card",
    })

    events = []
    for e in events_raw:
        events.append({
            "minute":  e.get("time", {}).get("elapsed", 0),
            "type":    e.get("type",""),
            "detail":  e.get("detail",""),
            "player":  e.get("player", {}).get("name",""),
            "team":    API_TO_DB.get(e.get("team",{}).get("name",""), ""),
        })
    return events


# ── LINEUP IMPACT ON PREDICTIONS ─────────────────────────────────────────────
def apply_lineups_to_predictions():
    """
    If line-ups are available, boost/reduce player probabilities
    based on whether they're in the starting XI.
    """
    if not os.path.exists("lineups.json"):
        return

    if not os.path.exists("player_preds_*.json"):
        return

    import glob
    pred_files = glob.glob("player_preds_*.json")
    if not pred_files:
        return

    with open("lineups.json") as f:
        lineup_data = json.load(f)

    with open(max(pred_files, key=os.path.getmtime)) as f:
        player_preds = json.load(f)

    lineups = lineup_data.get("lineups", {})
    modified = 0

    for fixture_preds in player_preds:
        fix = fixture_preds.get("fixture","")
        if fix not in lineups:
            continue

        lineup = lineups[fix]

        for p in fixture_preds.get("players", []):
            team    = p.get("team","")
            name    = p.get("name","")
            team_lu = lineup.get(team, {})
            starters= [s["name"].lower() for s in team_lu.get("starters",[])]
            subs    = [s["name"].lower() for s in team_lu.get("subs",[])]

            name_lower = name.lower()
            # Check if player name matches (partial match)
            is_starter = any(name_lower in s or s in name_lower for s in starters)
            is_sub     = any(name_lower in s or s in name_lower for s in subs)

            if is_starter:
                # Boost probability slightly - confirmed starter
                p["score_prob"]  = min(p.get("score_prob",0)  * 1.15, 0.99)
                p["assist_prob"] = min(p.get("assist_prob",0) * 1.15, 0.99)
                p["confirmed"]   = "starter"
                modified += 1
            elif is_sub:
                # Reduce probability - only coming off bench
                p["score_prob"]  = p.get("score_prob",0)  * 0.35
                p["assist_prob"] = p.get("assist_prob",0) * 0.35
                p["confirmed"]   = "sub"
                modified += 1
            else:
                # Not in squad - zero out
                p["score_prob"]  = 0
                p["assist_prob"] = 0
                p["confirmed"]   = "not_playing"
                modified += 1

    # Save updated predictions
    out = f"player_preds_lineup_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out, "w") as f:
        json.dump(player_preds, f, indent=2)
    print(f"Applied line-ups to {modified} players — saved to {out}")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", action="store_true", help="Fetch fixture IDs")
    parser.add_argument("--lineups",  action="store_true", help="Fetch today's line-ups")
    parser.add_argument("--live",     action="store_true", help="Fetch live scores")
    parser.add_argument("--apply",    action="store_true", help="Apply line-ups to predictions")
    parser.add_argument("--all",      action="store_true", help="Fixtures + lineups + live")
    args = parser.parse_args()

    print("="*55)
    print("API-FOOTBALL INTEGRATION")
    print(f"Key: {API_KEY[:8]}...  |  100 calls/day free")
    print("="*55)

    if args.fixtures or args.all:
        print("\n[FIXTURES]")
        fetch_pl_fixtures()

    if args.lineups or args.all:
        print("\n[LINE-UPS]")
        fetch_all_todays_lineups()

    if args.live or args.all:
        print("\n[LIVE SCORES]")
        fetch_live_scores()

    if args.apply:
        print("\n[APPLYING LINE-UPS TO PREDICTIONS]")
        apply_lineups_to_predictions()

    if not any([args.fixtures, args.lineups, args.live, args.apply, args.all]):
        print("\nUsage:")
        print("  python apifootball.py --fixtures   Fetch upcoming fixture IDs")
        print("  python apifootball.py --lineups    Fetch today's line-ups")
        print("  python apifootball.py --live       Live scores right now")
        print("  python apifootball.py --apply      Apply line-ups to predictions")
        print("  python apifootball.py --all        Everything")

    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
