"""
Extra Data Fetcher
===================
Fetches and computes:
  - Head to head history
  - Form strips (last 5 results)
  - Corners & cards historical averages
  - Player vs defence matchups
  - Odds movement snapshots

Run: python extradata.py
"""

import sqlite3
import json
import os
import glob
from datetime import datetime
from collections import defaultdict

DB_PATH = "premier_league.db"


def get_form_strip(conn, team_id, n=5):
    """Get last N results for a team as a list of W/D/L."""
    rows = conn.execute("""
        SELECT winner, home_team_id FROM matches
        WHERE (home_team_id=? OR away_team_id=?)
        AND status='FINISHED'
        ORDER BY utc_date DESC LIMIT ?
    """, (team_id, team_id, n)).fetchall()

    strip = []
    for winner, home_id in rows:
        if winner == "HOME_TEAM":
            strip.append("W" if home_id == team_id else "L")
        elif winner == "AWAY_TEAM":
            strip.append("L" if home_id == team_id else "W")
        else:
            strip.append("D")
    return strip


def get_h2h(conn, home_id, away_id, n=5):
    """Get last N H2H matches between two teams."""
    rows = conn.execute("""
        SELECT utc_date, home_team_id, away_team_id,
               home_score_ft, away_score_ft, winner
        FROM matches
        WHERE ((home_team_id=? AND away_team_id=?)
            OR (home_team_id=? AND away_team_id=?))
        AND status='FINISHED'
        ORDER BY utc_date DESC LIMIT ?
    """, (home_id, away_id, away_id, home_id, n)).fetchall()

    h2h = []
    home_wins = draw = away_wins = 0
    for date, htid, atid, hg, ag, winner in rows:
        if winner == "HOME_TEAM":
            result = "HOME"
            if htid == home_id: home_wins += 1
            else: away_wins += 1
        elif winner == "AWAY_TEAM":
            result = "AWAY"
            if atid == away_id: away_wins += 1
            else: home_wins += 1
        else:
            result = "DRAW"
            draw += 1

        h2h.append({
            "date":   date[:10],
            "home_id": htid,
            "away_id": atid,
            "home_goals": hg,
            "away_goals": ag,
            "result": result,
        })

    return h2h, home_wins, draw, away_wins


def get_corners_cards(conn, team_id, n=10):
    """
    Get average corners and cards for a team.
    Uses referee_stats table for card averages.
    Corners estimated from shots/attacking play.
    """
    # Get recent goals/shots as proxy for corners
    rows = conn.execute("""
        SELECT
            CASE WHEN home_team_id=? THEN home_score_ft ELSE away_score_ft END as gf,
            CASE WHEN home_team_id=? THEN away_score_ft ELSE home_score_ft END as ga
        FROM matches
        WHERE (home_team_id=? OR away_team_id=?)
        AND status='FINISHED'
        ORDER BY utc_date DESC LIMIT ?
    """, (team_id,team_id,team_id,team_id,n)).fetchall()

    if not rows:
        return {"corners_for": 5.5, "corners_against": 5.5,
                "yellows": 1.8, "reds": 0.1, "games": 0}

    avg_gf = sum(r[0] or 0 for r in rows) / len(rows)
    avg_ga = sum(r[1] or 0 for r in rows) / len(rows)

    # Rough corners model: each goal ~ 4 corners for attacking team
    # Plus base rate of 3 corners per team per half
    corners_for     = round(3.2 + avg_gf * 1.8, 1)
    corners_against = round(3.2 + avg_ga * 1.8, 1)

    return {
        "corners_for":     corners_for,
        "corners_against": corners_against,
        "avg_gf":          round(avg_gf, 2),
        "avg_ga":          round(avg_ga, 2),
        "games":           len(rows),
    }


def get_player_vs_defence(conn, player_name, team_id, opponent_id):
    """
    Get how well a player performs against weak/strong defences.
    Returns goals scored vs teams with similar defensive strength.
    """
    # Get opponent defensive strength (goals conceded per game)
    opp_rows = conn.execute("""
        SELECT AVG(
            CASE WHEN home_team_id=? THEN home_score_ft
                 ELSE away_score_ft END
        )
        FROM matches
        WHERE (home_team_id=? OR away_team_id=?)
        AND status='FINISHED'
        ORDER BY utc_date DESC LIMIT 10
    """, (opponent_id, opponent_id, opponent_id)).fetchone()

    opp_gf = float(opp_rows[0] or 1.5)  # Opponent's attack (not relevant)

    opp_def = conn.execute("""
        SELECT AVG(
            CASE WHEN away_team_id=? THEN home_score_ft
                 ELSE away_score_ft END
        )
        FROM matches
        WHERE (home_team_id=? OR away_team_id=?)
        AND status='FINISHED'
        ORDER BY utc_date DESC LIMIT 10
    """, (opponent_id, opponent_id, opponent_id)).fetchone()

    opp_concede = float(opp_def[0] or 1.2)

    return {"opp_goals_conceded_pg": round(opp_concede, 2)}


def save_odds_snapshot(predictions):
    """Save current odds as a snapshot for movement tracking."""
    snapshots_file = "odds_snapshots.json"
    snapshots = []
    if os.path.exists(snapshots_file):
        with open(snapshots_file) as f:
            snapshots = json.load(f)

    timestamp = datetime.now().isoformat()
    for pred in predictions:
        snapshots.append({
            "timestamp":  timestamp,
            "fixture":    pred.get("fixture"),
            "date":       pred.get("date"),
            "home_odds":  pred.get("implied_home_odds"),
            "draw_odds":  pred.get("implied_draw_odds"),
            "away_odds":  pred.get("implied_away_odds"),
        })

    # Keep only last 7 days
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    snapshots = [s for s in snapshots if s["timestamp"] > cutoff]

    with open(snapshots_file, "w") as f:
        json.dump(snapshots, f, indent=2)

    return snapshots


def get_odds_movement(fixture, snapshots):
    """Get opening vs current odds movement for a fixture."""
    fix_snaps = [s for s in snapshots if s["fixture"] == fixture]
    if len(fix_snaps) < 2:
        return None

    first = fix_snaps[0]
    last  = fix_snaps[-1]

    return {
        "home_open":  first["home_odds"],
        "home_now":   last["home_odds"],
        "draw_open":  first["draw_odds"],
        "draw_now":   last["draw_odds"],
        "away_open":  first["away_odds"],
        "away_now":   last["away_odds"],
        "home_move":  round((last["home_odds"] or 0) - (first["home_odds"] or 0), 2),
        "draw_move":  round((last["draw_odds"] or 0) - (first["draw_odds"] or 0), 2),
        "away_move":  round((last["away_odds"] or 0) - (first["away_odds"] or 0), 2),
    }


def build_extra_data():
    """Build all extra data and save to extra_data.json."""
    conn = sqlite3.connect(DB_PATH)

    # Load latest predictions
    pred_files = glob.glob("predictions_*.json")
    if not pred_files:
        print("No predictions found. Run pl.py --predict first.")
        return {}

    with open(max(pred_files, key=os.path.getmtime), encoding="utf-8") as f:
        predictions = json.load(f)

    # Load player predictions
    player_files = glob.glob("player_preds_*.json")
    player_preds = []
    if player_files:
        with open(max(player_files, key=os.path.getmtime), encoding="utf-8") as f:
            player_preds = json.load(f)

    player_map = {}
    for fp in player_preds:
        player_map[fp.get("fixture","").lower()] = fp.get("players", [])

    # Load odds snapshots
    snapshots = []
    if os.path.exists("odds_snapshots.json"):
        with open("odds_snapshots.json") as f:
            snapshots = json.load(f)

    # Save new snapshot
    save_odds_snapshot(predictions)

    extra = {}
    print(f"Building extra data for {len(predictions)} fixtures...")

    for pred in predictions:
        fixture = pred.get("fixture","")
        parts   = fixture.split(" vs ")
        if len(parts) != 2:
            continue

        home_name = parts[0]
        away_name = parts[1]

        # Get team IDs
        h_row = conn.execute("SELECT id FROM teams WHERE name=? LIMIT 1", (home_name,)).fetchone()
        a_row = conn.execute("SELECT id FROM teams WHERE name=? LIMIT 1", (away_name,)).fetchone()
        if not h_row or not a_row:
            continue

        htid = h_row[0]
        atid = a_row[0]

        # Form strips
        h_form = get_form_strip(conn, htid)
        a_form = get_form_strip(conn, atid)

        # H2H
        h2h_matches, h2h_hw, h2h_d, h2h_aw = get_h2h(conn, htid, atid)

        # Corners & cards
        h_cc = get_corners_cards(conn, htid)
        a_cc = get_corners_cards(conn, atid)
        total_corners = round(h_cc["corners_for"] + a_cc["corners_for"], 1)
        pred_corners  = round((h_cc["corners_for"] + a_cc["corners_against"] +
                               a_cc["corners_for"] + h_cc["corners_against"]) / 2, 1)

        # Odds movement
        movement = get_odds_movement(fixture, snapshots)

        # Player vs defence matchups
        players = player_map.get(fixture.lower(), [])
        matchups = []
        for p in sorted(players, key=lambda x: x.get("score_prob",0), reverse=True)[:5]:
            pdef = get_player_vs_defence(conn, p["name"],
                   htid if p.get("team")==home_name else atid,
                   atid if p.get("team")==home_name else htid)
            matchups.append({
                "name":          p["name"],
                "team":          p.get("team",""),
                "position":      p.get("position",""),
                "score_prob":    p.get("score_prob",0),
                "assist_prob":   p.get("assist_prob",0),
                "yellow_prob":   p.get("yellow_prob",0),
                "xg_per90":      p.get("xg_per90",0),
                "opp_concede":   pdef["opp_goals_conceded_pg"],
                "opp_name":      away_name if p.get("team")==home_name else home_name,
            })

        extra[fixture] = {
            "fixture":       fixture,
            "date":          pred.get("date",""),
            "home_form":     h_form,
            "away_form":     a_form,
            "h2h":           h2h_matches,
            "h2h_home_wins": h2h_hw,
            "h2h_draws":     h2h_d,
            "h2h_away_wins": h2h_aw,
            "home_corners":  h_cc,
            "away_corners":  a_cc,
            "pred_corners":  pred_corners,
            "total_corners": total_corners,
            "odds_movement": movement,
            "matchups":      matchups,
            # Pass through prediction data
            "home_win_prob": pred.get("home_win_prob",0),
            "draw_prob":     pred.get("draw_prob",0),
            "away_win_prob": pred.get("away_win_prob",0),
            "over_2_5_prob": pred.get("over_2_5_prob",0),
            "btts_prob":     pred.get("btts_prob",0),
            "home_elo":      pred.get("home_elo",0),
            "away_elo":      pred.get("away_elo",0),
            "home_key_out":  pred.get("home_key_out",0),
            "away_key_out":  pred.get("away_key_out",0),
            "implied_home_odds": pred.get("implied_home_odds",0),
            "implied_draw_odds": pred.get("implied_draw_odds",0),
            "implied_away_odds": pred.get("implied_away_odds",0),
        }

    conn.close()

    # Save
    with open("extra_data.json", "w", encoding="utf-8") as f:
        json.dump(extra, f, indent=2, ensure_ascii=False)

    print(f"Saved extra data for {len(extra)} fixtures to extra_data.json")
    return extra


if __name__ == "__main__":
    build_extra_data()
    input("\nPress Enter to close...")
