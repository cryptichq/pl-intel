"""
PL Intel - Results Tracker
===========================
Logs your predictions vs actual results each week.
Tracks accuracy, profit/loss on value bets, and player pick strike rate.

Run after results come in:
    python tracker.py --update          Pull latest results and compare
    python tracker.py --report          Show full performance report
    python tracker.py --both            Update then show report
"""

import sqlite3
import requests
import json
import glob
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH  = "premier_league.db"
LOG_FILE = "results_log.json"
API_KEY  = open("api_key.txt").read().strip() if os.path.exists("api_key.txt") else os.getenv("FOOTBALL_DATA_API_KEY","")
BASE_URL = "https://api.football-data.org/v4"
HEADERS  = {"X-Auth-Token": API_KEY}


# ── LOAD / SAVE LOG ───────────────────────────────────────────────────────────
def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            return json.load(f)
    return {"matches": [], "players": [], "value_bets": [], "summary": {}}

def save_log(log):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


# ── FETCH RESULTS ─────────────────────────────────────────────────────────────
def fetch_recent_results():
    """Fetch finished PL matches from last 14 days."""
    today     = datetime.now()
    two_weeks = today - timedelta(days=14)
    params    = {
        "dateFrom": two_weeks.strftime("%Y-%m-%d"),
        "dateTo":   today.strftime("%Y-%m-%d"),
        "status":   "FINISHED",
    }
    try:
        resp = requests.get(f"{BASE_URL}/competitions/PL/matches",
                           headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("matches", [])
    except Exception as e:
        print(f"[API] Could not fetch results: {e}")
        return []


def normalize(name):
    name = name.strip().lower()
    # Strip FC, AFC, etc
    for suffix in [" fc"," afc"," united fc"," city fc"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    maps = {
        "manchester city":"man city",
        "manchester united":"man united",
        "man utd":"man united",
        "tottenham hotspur":"tottenham",
        "spurs":"tottenham",
        "nottingham forest":"nottingham forest",
        "nott'm forest":"nottingham forest",
        "newcastle united":"newcastle",
        "west ham united":"west ham",
        "wolverhampton wanderers":"wolves",
        "afc bournemouth":"bournemouth",
        "brighton & hove albion":"brighton",
        "brighton and hove albion":"brighton",
        "leeds united":"leeds",
        "sheffield united":"sheffield united",
        "leicester city":"leicester",
        "luton town":"luton",
    }
    return maps.get(name, name)


# ── COMPARE PREDICTIONS ───────────────────────────────────────────────────────
def compare_predictions(log, results):
    """Match prediction JSONs against actual results."""
    pred_files = glob.glob("predictions_*.json")
    if not pred_files:
        print("No prediction files found.")
        return 0

    # Load all recent predictions
    all_preds = []
    for f in pred_files:
        with open(f) as fp:
            preds = json.load(fp)
        for p in preds:
            p["_source"] = f
        all_preds.extend(preds)

    # Already logged match IDs
    logged = {m["fixture"] + m["date"] for m in log["matches"]}

    new_entries = 0
    for result in results:
        home = result["homeTeam"]["name"]
        away = result["awayTeam"]["name"]
        score = result.get("score", {})
        ft    = score.get("fullTime", {})
        hg    = ft.get("home")
        ag    = ft.get("away")
        winner= score.get("winner","")
        date  = result.get("utcDate","")[:10]

        if hg is None or ag is None:
            continue

        actual_result = "HOME" if winner=="HOME_TEAM" else "AWAY" if winner=="AWAY_TEAM" else "DRAW"
        over25 = 1 if (hg+ag) > 2.5 else 0
        btts   = 1 if hg > 0 and ag > 0 else 0

        # Find matching prediction
        h_norm = normalize(home)
        a_norm = normalize(away)

        pred = None
        for p in all_preds:
            parts = p.get("fixture","").split(" vs ")
            if len(parts) == 2:
                if normalize(parts[0]) == h_norm and normalize(parts[1]) == a_norm:
                    pred = p
                    break

        if not pred:
            continue

        key = pred["fixture"] + date
        if key in logged:
            continue

        # Determine what model predicted
        hw = pred.get("home_win_prob",0)
        dr = pred.get("draw_prob",0)
        aw = pred.get("away_win_prob",0)
        best_prob = max(hw,dr,aw)
        if hw == best_prob:   predicted = "HOME"
        elif dr == best_prob: predicted = "DRAW"
        else:                 predicted = "AWAY"

        correct = predicted == actual_result

        entry = {
            "fixture":          pred["fixture"],
            "date":             date,
            "predicted":        predicted,
            "actual":           actual_result,
            "correct":          correct,
            "home_prob":        round(hw,3),
            "draw_prob":        round(dr,3),
            "away_prob":        round(aw,3),
            "score":            f"{hg}-{ag}",
            "over25_pred":      pred.get("over_2_5_prob",0) >= 0.55,
            "over25_actual":    over25,
            "btts_pred":        pred.get("btts_prob",0) >= 0.55,
            "btts_actual":      btts,
            "home_elo":         pred.get("home_elo",0),
            "away_elo":         pred.get("away_elo",0),
            "logged_at":        datetime.now().isoformat(),
        }

        log["matches"].append(entry)
        logged.add(key)
        new_entries += 1

        result_icon = "✅" if correct else "❌"
        print(f"  {result_icon} {pred['fixture']}: predicted {predicted}, actual {actual_result} ({hg}-{ag})")

    return new_entries


def compare_value_bets(log, results):
    """Check if value bets came in."""
    vf_files = glob.glob("value_finder_data_*.json")
    if not vf_files:
        return 0

    with open(max(vf_files, key=os.path.getmtime)) as f:
        value_bets = json.load(f)

    logged = {v["fixture"]+v.get("market","")+v.get("date","") for v in log["value_bets"]}
    new_entries = 0

    for vb in value_bets:
        fixture = vb.get("fixture","")
        market  = vb.get("market","")
        date    = vb.get("date","")
        key     = fixture + market + date

        if key in logged or vb.get("expected_value",99) > 5:
            continue

        # Find actual result
        parts  = fixture.split(" vs ")
        if len(parts) != 2: continue
        h_norm = normalize(parts[0])
        a_norm = normalize(parts[1])

        actual = None
        for r in results:
            if normalize(r["homeTeam"]["name"])==h_norm and normalize(r["awayTeam"]["name"])==a_norm:
                actual = r
                break

        if not actual: continue

        score = actual.get("score",{})
        ft    = score.get("fullTime",{})
        hg    = ft.get("home",0) or 0
        ag    = ft.get("away",0) or 0
        winner= score.get("winner","")

        # Check if bet won
        bet_label = vb.get("market","")
        won = False
        if "Home Win" in vb.get("market","") or parts[0] in vb.get("market",""):
            won = winner == "HOME_TEAM"
        elif "Away Win" in vb.get("market","") or parts[1] in vb.get("market",""):
            won = winner == "AWAY_TEAM"
        elif "Draw" in vb.get("market",""):
            won = winner == "DRAW"
        elif "Over 2.5" in vb.get("market",""):
            won = (hg + ag) > 2.5
        elif "BTTS" in vb.get("market",""):
            won = hg > 0 and ag > 0

        bm_odds = vb.get("bm_odds", 0)
        pnl     = round(bm_odds - 1, 2) if won else -1.0

        entry = {
            "fixture":    fixture,
            "date":       date,
            "market":     vb.get("market",""),
            "model_prob": vb.get("model_prob",0),
            "bm_odds":    bm_odds,
            "edge":       vb.get("edge",0),
            "won":        won,
            "pnl":        pnl,
            "score":      f"{hg}-{ag}",
            "logged_at":  datetime.now().isoformat(),
        }

        log["value_bets"].append(entry)
        logged.add(key)
        new_entries += 1

        icon = "✅" if won else "❌"
        print(f"  {icon} Value bet: {fixture} — {market} @ {bm_odds} → {'WON' if won else 'LOST'} (P&L: {pnl:+.2f})")

    return new_entries


# ── REPORT ────────────────────────────────────────────────────────────────────
def print_report(log):
    matches     = log["matches"]
    value_bets  = log["value_bets"]

    print("\n" + "="*65)
    print("PL INTEL — PERFORMANCE REPORT")
    print("="*65)

    if not matches:
        print("No results logged yet. Run --update after games finish.")
        return

    # Match result accuracy
    correct   = sum(1 for m in matches if m["correct"])
    total     = len(matches)
    acc       = correct/total if total else 0

    # By outcome
    home_preds = [m for m in matches if m["predicted"]=="HOME"]
    draw_preds = [m for m in matches if m["predicted"]=="DRAW"]
    away_preds = [m for m in matches if m["predicted"]=="AWAY"]

    home_acc  = sum(1 for m in home_preds if m["correct"])/len(home_preds) if home_preds else 0
    draw_acc  = sum(1 for m in draw_preds if m["correct"])/len(draw_preds) if draw_preds else 0
    away_acc  = sum(1 for m in away_preds if m["correct"])/len(away_preds) if away_preds else 0

    # Over 2.5
    o25_preds  = [m for m in matches if m.get("over25_pred")]
    o25_correct= sum(1 for m in o25_preds if m.get("over25_actual"))
    o25_acc    = o25_correct/len(o25_preds) if o25_preds else 0

    # BTTS
    bt_preds   = [m for m in matches if m.get("btts_pred")]
    bt_correct = sum(1 for m in bt_preds if m.get("btts_actual"))
    bt_acc     = bt_correct/len(bt_preds) if bt_preds else 0

    print(f"\n📊 MATCH RESULT ACCURACY")
    print(f"  Overall:    {correct}/{total} = {acc:.1%}  (random = 33%)")
    print(f"  Home Win:   {sum(1 for m in home_preds if m['correct'])}/{len(home_preds)} = {home_acc:.1%}")
    print(f"  Draw:       {sum(1 for m in draw_preds if m['correct'])}/{len(draw_preds)} = {draw_acc:.1%}")
    print(f"  Away Win:   {sum(1 for m in away_preds if m['correct'])}/{len(away_preds)} = {away_acc:.1%}")

    print(f"\n⚽ MARKETS")
    print(f"  Over 2.5:   {o25_correct}/{len(o25_preds)} = {o25_acc:.1%}")
    print(f"  BTTS:       {bt_correct}/{len(bt_preds)} = {bt_acc:.1%}")

    # Value bets P&L
    if value_bets:
        total_bets = len(value_bets)
        won_bets   = sum(1 for v in value_bets if v["won"])
        total_pnl  = sum(v["pnl"] for v in value_bets)
        pnl_icon   = "📈" if total_pnl > 0 else "📉"

        print(f"\n💰 VALUE BETS (£1 per bet)")
        print(f"  Record:     {won_bets}/{total_bets} won")
        print(f"  P&L:        {pnl_icon} {total_pnl:+.2f} units")
        print(f"  ROI:        {total_pnl/total_bets*100:+.1f}%")

        # By market
        by_market = {}
        for v in value_bets:
            m = v["market"]
            by_market.setdefault(m, {"w":0,"l":0,"pnl":0})
            if v["won"]: by_market[m]["w"] += 1
            else:        by_market[m]["l"] += 1
            by_market[m]["pnl"] += v["pnl"]

        print(f"\n  By market:")
        for mkt, d in sorted(by_market.items(), key=lambda x:-x[1]["pnl"]):
            total_m = d["w"]+d["l"]
            print(f"    {mkt:<20} {d['w']}/{total_m}  P&L: {d['pnl']:+.2f}")

    # Recent results
    print(f"\n📋 LAST 10 RESULTS")
    print(f"  {'Fixture':<32} {'Pred':>5} {'Act':>5} {'Score':>6} {'✓'}")
    print(f"  {'-'*55}")
    for m in sorted(matches, key=lambda x:x["date"], reverse=True)[:10]:
        icon = "✅" if m["correct"] else "❌"
        print(f"  {m['fixture'][:31]:<32} {m['predicted']:>5} {m['actual']:>5} {m['score']:>6} {icon}")

    # Calibration — do probabilities match outcomes?
    print(f"\n🎯 PROBABILITY CALIBRATION")
    print(f"  (When model says X%, does it win X% of the time?)")
    buckets = [(0,.4,"0-40%"),(0.4,.5,"40-50%"),(0.5,.6,"50-60%"),(0.6,.7,"60-70%"),(0.7,1,"70%+")]
    for lo, hi, label in buckets:
        in_bucket = [m for m in matches
                    if lo <= max(m["home_prob"],m["draw_prob"],m["away_prob"]) < hi]
        if not in_bucket: continue
        wins = sum(1 for m in in_bucket if m["correct"])
        print(f"  {label:<8} {wins}/{len(in_bucket)} = {wins/len(in_bucket):.0%} actual")

    print("="*65)


# ── UPDATE SITE ───────────────────────────────────────────────────────────────
def update_tracker_in_site(log):
    """Add a results section to the site HTML."""
    matches    = log["matches"]
    value_bets = log["value_bets"]

    if not matches:
        return

    correct = sum(1 for m in matches if m["correct"])
    total   = len(matches)
    acc     = correct/total if total else 0

    vb_pnl = sum(v["pnl"] for v in value_bets) if value_bets else 0
    vb_won = sum(1 for v in value_bets if v["won"]) if value_bets else 0
    vb_tot = len(value_bets)

    rows = ""
    for m in sorted(matches, key=lambda x:x["date"], reverse=True)[:15]:
        icon = "✅" if m["correct"] else "❌"
        rows += f"""<tr>
          <td>{m['fixture']}</td>
          <td class="tc">{m['date']}</td>
          <td class="tc pred">{m['predicted']}</td>
          <td class="tc act">{m['actual']}</td>
          <td class="tc score">{m['score']}</td>
          <td class="tc">{icon}</td>
        </tr>"""

    tracker_html = f"""
    <div class="tracker-stats">
      <div class="ts"><div class="ts-val {'green' if acc>0.5 else 'amber'}">{acc:.0%}</div><div class="ts-lbl">Match Accuracy</div></div>
      <div class="ts"><div class="ts-val">{correct}/{total}</div><div class="ts-lbl">Correct Results</div></div>
      <div class="ts"><div class="ts-val {'green' if vb_pnl>0 else 'red'}">{vb_pnl:+.1f}u</div><div class="ts-lbl">Value Bet P&L</div></div>
      <div class="ts"><div class="ts-val">{vb_won}/{vb_tot}</div><div class="ts-lbl">Value Bets Won</div></div>
    </div>
    <table class="results-table">
      <thead><tr><th>Fixture</th><th>Date</th><th>Predicted</th><th>Actual</th><th>Score</th><th></th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""

    # Inject into site if it exists
    if os.path.exists("pl_intel.html"):
        with open("pl_intel.html", encoding="utf-8") as f:
            html = f.read()

        # Add tracker styles and tab if not present
        if "tracker-stats" not in html:
            tracker_styles = """
    .tracker-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}
    .ts{background:var(--s2);border:1px solid var(--bd);border-radius:12px;padding:16px;text-align:center}
    .ts-val{font-family:var(--display);font-size:32px;line-height:1;color:#fff}
    .ts-val.green{color:var(--g)}.ts-val.amber{color:var(--go)}.ts-val.red{color:var(--r)}
    .ts-lbl{font-family:var(--mono);font-size:10px;text-transform:uppercase;color:var(--mu);margin-top:6px}
    .results-table{width:100%;border-collapse:collapse;font-size:13px}
    .results-table th{background:var(--s1);padding:10px 12px;text-align:left;color:var(--mu);font-weight:400;font-size:10px;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid var(--bd)}
    .results-table td{padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.03)}
    .tc{text-align:center}.pred{color:var(--b)}.act{color:var(--g)}.score{font-family:var(--mono)}
    @media(max-width:580px){.tracker-stats{grid-template-columns:1fr 1fr}}"""

            html = html.replace("</style>", tracker_styles + "\n</style>")

            # Add tab button
            html = html.replace(
                '<button class="tab" onclick="show(\'p4\',this)">',
                '<button class="tab" onclick="show(\'p5\',this)">Results Tracker</button>\n  <button class="tab" onclick="show(\'p4\',this)">'
            )

            # Add pane
            html = html.replace(
                '<footer>',
                f'<div id="p5" class="pane"><div class="day-label" style="margin-top:0">Performance since tracking started</div>{tracker_html}</div>\n<footer>'
            )
        else:
            # Update existing tracker content
            import re
            html = re.sub(
                r'<div class="tracker-stats">.*?</table>',
                tracker_html.strip(),
                html, flags=re.DOTALL
            )

        with open("pl_intel.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("[SITE] Results tracker added to pl_intel.html")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="Fetch results and log predictions")
    parser.add_argument("--report", action="store_true", help="Show performance report")
    parser.add_argument("--both",   action="store_true", help="Update then report")
    args = parser.parse_args()

    log = load_log()

    if args.update or args.both:
        print("Fetching recent results...")
        results = fetch_recent_results()

        if not results:
            print("No results fetched — check API key or internet connection")
        else:
            print(f"Found {len(results)} finished matches\n")
            print("Comparing match predictions:")
            n1 = compare_predictions(log, results)
            print(f"\nComparing value bets:")
            n2 = compare_value_bets(log, results)
            print(f"\nLogged {n1} match results, {n2} value bet results")
            save_log(log)
            update_tracker_in_site(log)
            print("\nRun: copy /y pl_intel.html index.html && git add index.html && git commit -m 'Update results' && git push origin master")

    if args.report or args.both:
        print_report(log)

    if not args.update and not args.report and not args.both:
        print("Usage:")
        print("  python tracker.py --update    Log this week's results")
        print("  python tracker.py --report    Show performance report")
        print("  python tracker.py --both      Update then report")

    input("\nPress Enter to close...")

if __name__ == "__main__":
    main()
