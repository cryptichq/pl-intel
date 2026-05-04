"""
Value Finder — compares model implied odds vs bookmaker odds
============================================================
Fetches live odds from the-odds-api.com (free tier: 500 requests/month)
and compares against your model's implied odds to find value bets.

Get a free API key at: https://the-odds-api.com/
Free tier is plenty — you only need ~20 requests per week.

Run: python valuefinder.py
"""

import requests
import json
import sqlite3
import os
from datetime import datetime
from pathlib import Path

DB_PATH     = "premier_league.db"
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "YOUR_ODDS_API_KEY_HERE")
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"

# Minimum edge to flag as value (5% = model thinks probability is 5% higher than bookmaker implies)
MIN_EDGE = 0.05

# Bookmakers to include (the-odds-api free tier includes these)
BOOKMAKERS = "bet365,williamhill,betfair,paddypower,skybet,ladbrokes,coral"


def fetch_bookmaker_odds():
    """Fetch live Premier League odds from the-odds-api."""
    if "YOUR_ODDS_API_KEY" in ODDS_API_KEY:
        print("[!] No Odds API key set.")
        print("    Get a free key at: https://the-odds-api.com/")
        print("    Then set it: set ODDS_API_KEY=your_key_here")
        print("\n    Using demo mode with sample odds instead...\n")
        return demo_odds()

    params = {
        "apiKey":     ODDS_API_KEY,
        "regions":    "uk",
        "markets":    "h2h",
        "oddsFormat": "decimal",
        "bookmakers": BOOKMAKERS,
    }

    try:
        resp = requests.get(ODDS_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"[ODDS] Fetched {len(data)} fixtures ({remaining} API calls remaining this month)")
        return data
    except Exception as e:
        print(f"[ODDS] API error: {e}")
        return []


def demo_odds():
    """Return sample odds for demo purposes when no API key is set."""
    return [
        {
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "commence_time": "2026-05-18T14:00:00Z",
            "bookmakers": [{
                "title": "Bet365",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Arsenal", "price": 1.75},
                        {"name": "Draw",    "price": 3.60},
                        {"name": "Chelsea", "price": 4.50},
                    ]
                }]
            }]
        },
        {
            "home_team": "Man City",
            "away_team": "Brentford",
            "commence_time": "2026-05-09T14:00:00Z",
            "bookmakers": [{
                "title": "Bet365",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Man City",  "price": 1.30},
                        {"name": "Draw",      "price": 5.50},
                        {"name": "Brentford", "price": 9.00},
                    ]
                }]
            }]
        },
    ]


def get_best_odds(bookmakers):
    """Get the best available odds across all bookmakers for each outcome."""
    best = {}
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market.get("key") == "h2h":
                for outcome in market.get("outcomes", []):
                    name  = outcome["name"]
                    price = float(outcome["price"])
                    if name not in best or price > best[name]["price"]:
                        best[name] = {"price": price, "bookmaker": bm["title"]}
    return best


def load_model_predictions():
    """Load latest model predictions from JSON file."""
    import glob
    files = glob.glob("predictions_*.json")
    if not files:
        print("[!] No model predictions found. Run: python predict_final.py first")
        return []

    latest = max(files, key=os.path.getmtime)
    with open(latest) as f:
        preds = json.load(f)
    print(f"[MODEL] Loaded predictions from {latest}")
    return preds


def normalize_team_name(name):
    """Normalize team names for matching between model and bookmaker."""
    name = name.strip().lower()
    mappings = {
        "manchester city":      "man city",
        "manchester united":    "man united",
        "man utd":              "man united",
        "tottenham hotspur":    "tottenham",
        "spurs":                "tottenham",
        "nottingham forest":    "nottingham forest",
        "nott'm forest":        "nottingham forest",
        "newcastle united":     "newcastle",
        "west ham united":      "west ham",
        "wolverhampton wanderers": "wolves",
        "afc bournemouth":      "bournemouth",
        "brighton & hove albion": "brighton",
        "brighton and hove albion": "brighton",
        "leeds united":         "leeds",
        "leicester city":       "leicester",
        "crystal palace":       "crystal palace",
        "aston villa":          "aston villa",
    }
    return mappings.get(name, name)


def match_fixture(bm_home, bm_away, model_preds):
    """Find matching model prediction for a bookmaker fixture."""
    bm_h = normalize_team_name(bm_home)
    bm_a = normalize_team_name(bm_away)

    for pred in model_preds:
        fixture = pred.get("fixture", "")
        parts   = fixture.split(" vs ")
        if len(parts) != 2:
            continue
        m_h = normalize_team_name(parts[0])
        m_a = normalize_team_name(parts[1])

        if bm_h in m_h or m_h in bm_h:
            if bm_a in m_a or m_a in bm_a:
                return pred
    return None


def find_value(model_preds, bm_odds):
    """
    Compare model probabilities against bookmaker odds.
    Value exists when: model_prob > (1 / bm_odds) + MIN_EDGE
    """
    value_bets = []

    for fixture_odds in bm_odds:
        bm_home = fixture_odds.get("home_team", "")
        bm_away = fixture_odds.get("away_team", "")
        date    = fixture_odds.get("commence_time", "")[:10]

        model = match_fixture(bm_home, bm_away, model_preds)
        if not model:
            continue

        best_odds = get_best_odds(fixture_odds.get("bookmakers", []))
        if not best_odds:
            continue

        # Map outcomes
        home_name = bm_home
        away_name = bm_away

        outcome_map = [
            ("Home Win",  model.get("home_win_prob", 0), home_name),
            ("Draw",      model.get("draw_prob",     0), "Draw"),
            ("Away Win",  model.get("away_win_prob", 0), away_name),
        ]

        fixture_values = []

        for label, model_prob, bm_key in outcome_map:
            # Try to find matching bookmaker odds
            bm_data = None
            for k, v in best_odds.items():
                if normalize_team_name(k) == normalize_team_name(bm_key) or \
                   k.lower() == "draw" and label == "Draw":
                    bm_data = v
                    break

            if not bm_data:
                continue

            bm_price    = bm_data["price"]
            bm_prob     = 1 / bm_price
            edge        = model_prob - bm_prob
            expected_val= (model_prob * bm_price) - 1  # EV per £1 staked

            if edge >= MIN_EDGE:
                fixture_values.append({
                    "fixture":       f"{bm_home} vs {bm_away}",
                    "date":          date,
                    "market":        label,
                    "model_prob":    round(model_prob, 4),
                    "bm_odds":       bm_price,
                    "bm_prob":       round(bm_prob, 4),
                    "edge":          round(edge, 4),
                    "expected_value":round(expected_val, 4),
                    "bookmaker":     bm_data["bookmaker"],
                    "implied_odds":  round(1/model_prob, 2) if model_prob > 0 else 99,
                })

        value_bets.extend(fixture_values)

    return sorted(value_bets, key=lambda x: x["expected_value"], reverse=True)


def generate_value_html(value_bets, model_preds):
    """Generate a clean HTML value finder report."""
    generated_at = datetime.now().strftime("%d %B %Y, %H:%M")

    if not value_bets:
        value_rows = '<p style="color:#6b6b80;padding:2rem;text-align:center">No value bets found this week — model and bookmaker odds are closely aligned.</p>'
    else:
        value_rows = ""
        for v in value_bets:
            edge_pct  = v["edge"] * 100
            ev_pct    = v["expected_value"] * 100
            ev_color  = "#00ff87" if ev_pct > 0 else "#ff4757"
            edge_bar  = min(int(edge_pct * 8), 100)

            value_rows += f"""
            <div class="value-card">
                <div class="value-header">
                    <div class="fixture-name">{v['fixture']}</div>
                    <div class="value-date">{v['date']}</div>
                </div>
                <div class="value-body">
                    <div class="market-name">{v['market']}</div>
                    <div class="odds-compare">
                        <div class="odds-item">
                            <div class="odds-label">Model probability</div>
                            <div class="odds-val model">{v['model_prob']:.1%}</div>
                        </div>
                        <div class="odds-arrow">→</div>
                        <div class="odds-item">
                            <div class="odds-label">{v['bookmaker']} odds</div>
                            <div class="odds-val bookie">{v['bm_odds']}</div>
                        </div>
                        <div class="odds-item">
                            <div class="odds-label">Implied prob</div>
                            <div class="odds-val implied">{v['bm_prob']:.1%}</div>
                        </div>
                    </div>
                    <div class="edge-row">
                        <div class="edge-bar-wrap">
                            <div class="edge-bar" style="width:{edge_bar}%"></div>
                        </div>
                        <span class="edge-label">Edge: +{edge_pct:.1f}%</span>
                        <span class="ev-label" style="color:{ev_color}">EV: {ev_pct:+.1f}p per £1</span>
                    </div>
                </div>
            </div>"""

    # All fixtures summary table
    fixture_rows = ""
    for pred in model_preds:
        fixture = pred.get("fixture", "")
        date    = pred.get("date", "")
        hw      = pred.get("home_win_prob", 0)
        dr      = pred.get("draw_prob",     0)
        aw      = pred.get("away_win_prob", 0)
        iho     = pred.get("implied_home_odds", 0)
        idr     = pred.get("implied_draw_odds", 0)
        iaw     = pred.get("implied_away_odds", 0)

        best    = max(hw, dr, aw)
        hc      = "best" if hw == best else ""
        dc      = "best" if dr == best else ""
        ac      = "best" if aw == best else ""

        fixture_rows += f"""
        <tr>
            <td class="fix-name">{fixture}</td>
            <td class="fix-date">{date}</td>
            <td class="{hc}">{hw:.0%}<br><span class="sub-odds">{iho:.2f}</span></td>
            <td class="{dc}">{dr:.0%}<br><span class="sub-odds">{idr:.2f}</span></td>
            <td class="{ac}">{aw:.0%}<br><span class="sub-odds">{iaw:.2f}</span></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PL Value Finder</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --green:   #00ff87;
    --red:     #ff4757;
    --amber:   #ffa502;
    --bg:      #0a0a0f;
    --surface: #111118;
    --card:    #16161f;
    --border:  rgba(255,255,255,0.07);
    --text:    #e8e8f0;
    --muted:   #6b6b80;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'DM Sans', sans-serif; font-size: 14px; }}
  body::before {{ content: ''; position: fixed; inset: 0; background: radial-gradient(ellipse 80% 50% at 50% -10%, rgba(0,255,135,0.04) 0%, transparent 70%); pointer-events: none; z-index: 0; }}
  .page {{ position: relative; z-index: 1; max-width: 1000px; margin: 0 auto; padding: 40px 20px 80px; }}

  .header {{ display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 40px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }}
  .header h1 {{ font-family: 'Bebas Neue', sans-serif; font-size: 52px; letter-spacing: 2px; color: #fff; line-height: 1; }}
  .header h1 span {{ color: var(--green); }}
  .header p {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
  .header-right {{ text-align: right; color: var(--muted); font-size: 11px; line-height: 2; }}

  .section-title {{ font-family: 'Bebas Neue', sans-serif; font-size: 13px; letter-spacing: 3px; color: var(--muted); margin-bottom: 16px; text-transform: uppercase; }}

  /* Value cards */
  .value-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 12px; overflow: hidden; transition: border-color 0.2s; }}
  .value-card:hover {{ border-color: rgba(0,255,135,0.2); }}
  .value-header {{ display: flex; justify-content: space-between; align-items: center; padding: 14px 18px 10px; border-bottom: 1px solid var(--border); }}
  .fixture-name {{ font-weight: 500; font-size: 15px; color: #fff; }}
  .value-date {{ font-size: 11px; color: var(--muted); }}
  .value-body {{ padding: 14px 18px; }}
  .market-name {{ font-family: 'Bebas Neue', sans-serif; font-size: 20px; color: var(--green); letter-spacing: 1px; margin-bottom: 12px; }}

  .odds-compare {{ display: flex; align-items: center; gap: 16px; margin-bottom: 14px; flex-wrap: wrap; }}
  .odds-item {{ text-align: center; }}
  .odds-label {{ font-size: 10px; color: var(--muted); letter-spacing: 0.5px; text-transform: uppercase; margin-bottom: 4px; }}
  .odds-val {{ font-family: 'Bebas Neue', sans-serif; font-size: 26px; line-height: 1; }}
  .odds-val.model {{ color: var(--green); }}
  .odds-val.bookie {{ color: #fff; }}
  .odds-val.implied {{ color: var(--amber); }}
  .odds-arrow {{ font-size: 18px; color: var(--muted); }}

  .edge-row {{ display: flex; align-items: center; gap: 12px; }}
  .edge-bar-wrap {{ flex: 1; height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; max-width: 200px; }}
  .edge-bar {{ height: 100%; background: var(--green); border-radius: 2px; }}
  .edge-label {{ font-size: 12px; font-weight: 500; color: var(--green); }}
  .ev-label {{ font-size: 12px; font-weight: 500; }}

  /* Fixtures table */
  .table-wrap {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin-top: 40px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ padding: 10px 14px; text-align: left; color: var(--muted); font-weight: 400; font-size: 10px; letter-spacing: 1px; text-transform: uppercase; border-bottom: 1px solid var(--border); background: var(--surface); }}
  td {{ padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.03); vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  .fix-name {{ color: #fff; font-weight: 500; }}
  .fix-date {{ color: var(--muted); font-size: 11px; }}
  td.best {{ color: var(--green); font-weight: 500; }}
  .sub-odds {{ color: var(--muted); font-size: 10px; font-weight: 400; }}

  .no-key-notice {{ background: rgba(255,165,2,0.08); border: 1px solid rgba(255,165,2,0.2); border-radius: 10px; padding: 16px 20px; margin-bottom: 24px; font-size: 13px; line-height: 1.8; }}
  .no-key-notice strong {{ color: var(--amber); }}

  .footer {{ text-align: center; color: var(--muted); font-size: 11px; margin-top: 60px; padding-top: 24px; border-top: 1px solid var(--border); line-height: 2; }}

  .live-dot {{ display: inline-block; width: 6px; height: 6px; background: var(--green); border-radius: 50%; margin-right: 6px; animation: pulse 2s infinite; }}
  @keyframes pulse {{ 0%, 100% {{ opacity:1; }} 50% {{ opacity:0.3; }} }}
</style>
</head>
<body>
<div class="page">

  <div class="header">
    <div>
      <h1>VALUE <span>FINDER</span></h1>
      <p>Model implied odds vs bookmaker odds — edges highlighted</p>
    </div>
    <div class="header-right">
      <span class="live-dot"></span>Generated {generated_at}<br>
      Min edge threshold: {MIN_EDGE:.0%}
    </div>
  </div>

  {"" if ODDS_API_KEY != "YOUR_ODDS_API_KEY_HERE" else '''
  <div class="no-key-notice">
    <strong>Demo mode</strong> — showing sample data. To get real bookmaker odds:<br>
    1. Sign up free at <strong>the-odds-api.com</strong> (500 requests/month free)<br>
    2. In Command Prompt run: <strong>set ODDS_API_KEY=your_key_here</strong><br>
    3. Then run: <strong>python valuefinder.py</strong>
  </div>
  '''}

  <div class="section-title">Value bets — model edge over bookmaker odds</div>
  {value_rows}

  <div class="section-title" style="margin-top:40px">All fixture implied odds</div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Fixture</th>
          <th>Date</th>
          <th>Home Win</th>
          <th>Draw</th>
          <th>Away Win</th>
        </tr>
      </thead>
      <tbody>
        {fixture_rows}
      </tbody>
    </table>
  </div>

  <div class="footer">
    Value = model probability significantly exceeds bookmaker implied probability<br>
    Expected value shown per £1 staked · Always gamble responsibly · 18+
  </div>

</div>
</body>
</html>"""

    return html


def main():
    model_preds = load_model_predictions()
    if not model_preds:
        input("Press Enter to close...")
        return

    bm_odds = fetch_bookmaker_odds()
    value_bets = find_value(model_preds, bm_odds)

    print(f"\n{'='*60}")
    print(f"VALUE BETS FOUND: {len(value_bets)}")
    print(f"{'='*60}")

    if value_bets:
        print(f"\n{'Fixture':<35} {'Market':<12} {'Model':>7} {'BM Odds':>8} {'Edge':>7} {'EV':>8}")
        print(f"{'-'*80}")
        for v in value_bets:
            print(f"{v['fixture']:<35} {v['market']:<12} {v['model_prob']:>6.1%} "
                  f"{v['bm_odds']:>8.2f} {v['edge']:>+6.1%} {v['expected_value']:>+7.1%}")
    else:
        print("No value bets found this week.")

    # Generate HTML report
    html    = generate_value_html(value_bets, model_preds)
    outfile = "value_finder.html"
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nSaved to {outfile}")

    # Save value bets as JSON for site.py
    vf_data = f"value_finder_data_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(vf_data, "w") as f:
        json.dump(value_bets, f, indent=2)
    print(f"Saved value data to {vf_data}")

    import webbrowser
    try:
        webbrowser.open(f"file://{os.path.abspath(outfile)}")
        print("Opening in browser...")
    except:
        pass

    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
