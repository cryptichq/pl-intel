"""
Injury & Availability Fetcher
==============================
Pulls detailed player availability from FPL including:
- Injury reason/news
- Chance of playing %
- Return date estimates
- Suspension reasons

Saves to injuries.json for site.py to use.
Run: python injuries.py
"""

import requests
import json
import sqlite3
import os
from datetime import datetime

DB_PATH  = "premier_league.db"
OUT_FILE = "injuries.json"
FPL_API  = "https://fantasy.premierleague.com/api/bootstrap-static/"

FPL_POSITIONS = {1:"GK", 2:"DEF", 3:"MID", 4:"FWD"}

STATUS_LABELS = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
    "n": "Not in squad",
}

STATUS_COLOURS = {
    "a": "green",
    "d": "amber",
    "i": "red",
    "s": "purple",
    "u": "red",
    "n": "grey",
}

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


def fetch_injuries():
    print("Fetching player availability from FPL API...", end=" ", flush=True)
    try:
        resp = requests.get(FPL_API, headers={"User-Agent":"Mozilla/5.0"}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Failed: {e}")
        return {}

    fpl_teams = {t["id"]: t["name"] for t in data.get("teams", [])}
    players   = data.get("elements", [])
    print(f"{len(players)} players")

    by_team = {}
    unavailable_count = 0

    for p in players:
        status = p.get("status", "a")
        chance = p.get("chance_of_playing_next_round")
        news   = p.get("news", "") or ""
        mins   = int(p.get("minutes", 0))

        # Only include players with meaningful minutes or who are notable
        if mins < 500 and status == "a":
            continue

        name     = f"{p.get('first_name','')} {p.get('second_name','')}".strip()
        fpl_team = fpl_teams.get(p.get("team"), "")
        db_team  = FPL_NAME_TO_DB.get(fpl_team, fpl_team)
        position = FPL_POSITIONS.get(p.get("element_type", 3), "MID")

        player_data = {
            "name":       name,
            "position":   position,
            "status":     status,
            "status_label": STATUS_LABELS.get(status, "Unknown"),
            "status_colour": STATUS_COLOURS.get(status, "grey"),
            "chance":     chance,
            "news":       news,
            "minutes":    mins,
            "is_key":     mins >= 1800,
        }

        if db_team not in by_team:
            by_team[db_team] = {"available": [], "unavailable": [], "doubtful": []}

        # Skip players on loan or permanently transferred - not relevant
        news_lower = news.lower()
        is_loan_or_transfer = any(x in news_lower for x in [
            "on loan", "permanently", "joined", "has joined"
        ])
        if is_loan_or_transfer:
            continue

        if status == "a":
            by_team[db_team]["available"].append(player_data)
        elif status == "d":
            by_team[db_team]["doubtful"].append(player_data)
            unavailable_count += 1
        else:
            by_team[db_team]["unavailable"].append(player_data)
            unavailable_count += 1

    print(f"Found {unavailable_count} unavailable/doubtful players")

    # Sort each team's lists by key players first
    for team in by_team:
        for cat in ["unavailable", "doubtful"]:
            by_team[team][cat].sort(key=lambda x: (-x["is_key"], x["name"]))

    return by_team


def print_summary(by_team):
    print("\n" + "="*60)
    print("INJURY & AVAILABILITY SUMMARY")
    print("="*60)

    for team in sorted(by_team.keys()):
        unavail = by_team[team]["unavailable"]
        doubt   = by_team[team]["doubtful"]
        if not unavail and not doubt:
            continue

        print(f"\n{team}:")
        for p in unavail:
            key_flag = " ⚠KEY" if p["is_key"] else ""
            print(f"  ❌ {p['name']:<25} {p['position']} — {p['status_label']}{key_flag}")
            if p["news"]:
                print(f"     {p['news']}")
        for p in doubt:
            pct = f" ({p['chance']}% chance)" if p["chance"] is not None else ""
            print(f"  ⚠️  {p['name']:<25} {p['position']} — Doubtful{pct}")
            if p["news"]:
                print(f"     {p['news']}")


def save_injuries(by_team):
    out = {
        "updated_at": datetime.now().isoformat(),
        "teams": by_team
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {OUT_FILE}")


def main():
    by_team = fetch_injuries()
    if not by_team:
        print("Could not fetch injury data")
        input("Press Enter..."); return

    print_summary(by_team)
    save_injuries(by_team)
    print("\nNow run: python site.py to update the website")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
