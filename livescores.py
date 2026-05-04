"""
Live Scores — football-data.org
=================================
Fetches live and today's PL scores.
Updates live_scores.json which site.py reads.

Run anytime:
    python livescores.py              Show today's scores
    python livescores.py --watch      Auto-refresh every 60 seconds

Free tier limits: 10 calls/minute — plenty for live updates.
"""

import requests
import json
import os
import time
import argparse
from datetime import datetime, date

API_KEY  = open("api_key.txt").read().strip() if os.path.exists("api_key.txt") else ""
BASE_URL = "https://api.football-data.org/v4"
HEADERS  = {"X-Auth-Token": API_KEY}

STATUS_LABELS = {
    "SCHEDULED":  "📅 Soon",
    "TIMED":      "📅 Soon",
    "IN_PLAY":    "🔴 LIVE",
    "PAUSED":     "⏸ HT",
    "FINISHED":   "✅ FT",
    "POSTPONED":  "⚠ PP",
    "SUSPENDED":  "⚠ SUS",
    "CANCELLED":  "❌ CAN",
}

NAME_MAP = {
    "Manchester City":          "Man City",
    "Manchester United":        "Man United",
    "Tottenham Hotspur":        "Tottenham",
    "Nottingham Forest":        "Nott'm Forest",
    "Newcastle United":         "Newcastle",
    "West Ham United":          "West Ham",
    "Wolverhampton Wanderers":  "Wolves",
    "Brighton & Hove Albion":   "Brighton",
    "AFC Bournemouth":          "Bournemouth",
    "Leeds United":             "Leeds",
    "Leicester City":           "Leicester",
    "Sheffield United":         "Sheffield Utd",
}

def shorten(name):
    return NAME_MAP.get(name, name)


def fetch_today():
    """Fetch all PL matches today."""
    today = date.today().isoformat()
    try:
        resp = requests.get(
            f"{BASE_URL}/competitions/PL/matches",
            headers=HEADERS,
            params={"dateFrom": today, "dateTo": today},
            timeout=15
        )
        resp.raise_for_status()
        return resp.json().get("matches", [])
    except Exception as e:
        print(f"Error fetching scores: {e}")
        return []


def fetch_live():
    """Fetch currently IN_PLAY PL matches."""
    try:
        resp = requests.get(
            f"{BASE_URL}/competitions/PL/matches",
            headers=HEADERS,
            params={"status": "IN_PLAY,PAUSED"},
            timeout=15
        )
        resp.raise_for_status()
        return resp.json().get("matches", [])
    except Exception as e:
        print(f"Error fetching live: {e}")
        return []


def fetch_recent(days=3):
    """Fetch recent finished matches."""
    from datetime import timedelta
    today   = date.today()
    past    = (today - timedelta(days=days)).isoformat()
    todaystr= today.isoformat()
    try:
        resp = requests.get(
            f"{BASE_URL}/competitions/PL/matches",
            headers=HEADERS,
            params={"dateFrom": past, "dateTo": todaystr, "status": "FINISHED"},
            timeout=15
        )
        resp.raise_for_status()
        return resp.json().get("matches", [])
    except Exception as e:
        return []


def format_match(m):
    """Format a single match for display."""
    home   = shorten(m["homeTeam"]["name"])
    away   = shorten(m["awayTeam"]["name"])
    status = m["status"]
    score  = m.get("score", {})
    ft     = score.get("fullTime", {})
    ht     = score.get("halfTime", {})
    hg     = ft.get("home")
    ag     = ft.get("away")
    minute = m.get("minute", "")
    utc    = m.get("utcDate","")

    # Format kickoff time
    try:
        ko = datetime.fromisoformat(utc.replace("Z","+00:00"))
        from datetime import timezone
        import datetime as dt
        ko_local = ko.astimezone(dt.timezone(dt.timedelta(hours=1)))  # BST
        ko_str   = ko_local.strftime("%H:%M")
    except:
        ko_str = ""

    status_label = STATUS_LABELS.get(status, status)

    if status in ("IN_PLAY", "PAUSED"):
        score_str = f"{hg} - {ag}"
        min_str   = f"{minute}'" if minute else ""
        return {
            "display":   f"{home} {hg}-{ag} {away}  {min_str}",
            "home":      home, "away": away,
            "home_goals":hg or 0, "away_goals": ag or 0,
            "status":    status_label, "minute": minute,
            "kickoff":   ko_str, "is_live": True,
        }
    elif status == "FINISHED":
        return {
            "display":   f"{home} {hg}-{ag} {away}  FT",
            "home":      home, "away": away,
            "home_goals":hg or 0, "away_goals": ag or 0,
            "status":    status_label, "minute": 90,
            "kickoff":   ko_str, "is_live": False,
            "is_finished": True,
        }
    else:
        return {
            "display":   f"{home} vs {away}  {ko_str}",
            "home":      home, "away": away,
            "home_goals":None, "away_goals": None,
            "status":    status_label, "minute": None,
            "kickoff":   ko_str, "is_live": False,
        }


def save_scores(matches):
    """Save to JSON for site.py to pick up."""
    formatted = [format_match(m) for m in matches]
    out = {
        "fetched_at": datetime.now().isoformat(),
        "date":       date.today().isoformat(),
        "matches":    formatted,
        "live_count": sum(1 for f in formatted if f.get("is_live")),
    }
    with open("live_scores.json", "w") as f:
        json.dump(out, f, indent=2)
    return formatted


def print_scores(formatted):
    """Print scores to terminal."""
    live    = [m for m in formatted if m.get("is_live")]
    finished= [m for m in formatted if m.get("is_finished")]
    upcoming= [m for m in formatted if not m.get("is_live") and not m.get("is_finished")]

    print(f"\n{'='*55}")
    print(f"PL SCORES — {date.today().strftime('%A %d %B')}")
    print(f"{'='*55}")

    if live:
        print(f"\n🔴 LIVE")
        for m in live:
            print(f"  {m['home']:<20} {m['home_goals']} - {m['away_goals']} {m['away']:<20} {m['minute']}'")

    if finished:
        print(f"\n✅ FINISHED")
        for m in finished:
            print(f"  {m['home']:<20} {m['home_goals']} - {m['away_goals']} {m['away']}")

    if upcoming:
        print(f"\n📅 TODAY")
        for m in upcoming:
            print(f"  {m['home']:<20} vs {m['away']:<20} {m['kickoff']}")

    if not live and not finished and not upcoming:
        print("\n  No PL matches today")

    print(f"\n{'='*55}")


def watch_mode():
    """Auto-refresh every 60 seconds while matches are live."""
    print("Watch mode — refreshing every 60 seconds. Press Ctrl+C to stop.\n")
    try:
        while True:
            os.system("cls" if os.name=="nt" else "clear")
            matches   = fetch_today()
            formatted = save_scores(matches)
            print_scores(formatted)
            live_count = sum(1 for m in formatted if m.get("is_live"))
            if live_count == 0:
                print("No live matches. Checking again in 60s...")
            else:
                print(f"{live_count} live match(es). Next refresh in 60s...")
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="Auto-refresh every 60s")
    args = parser.parse_args()

    if args.watch:
        watch_mode()
    else:
        matches   = fetch_today()
        # Also grab recent results if nothing today
        if not matches:
            matches = fetch_recent(days=3)
        formatted = save_scores(matches)
        print_scores(formatted)
        print(f"\nSaved to live_scores.json")
        input("Press Enter to close...")


if __name__ == "__main__":
    main()
