"""
Match Page Generator
=====================
Generates individual HTML match analysis pages for each fixture.
Pages saved to matches/ folder and linked from the main site.

Run: python matchpages.py
Then: python site.py (links added automatically)
"""

import json, glob, os, math
from datetime import datetime

def load_latest(pattern):
    files = glob.glob(pattern)
    if not files: return []
    with open(max(files, key=os.path.getmtime), encoding="utf-8") as f:
        return json.load(f)

def load_extra():
    if os.path.exists("extra_data.json"):
        with open("extra_data.json", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_logos():
    if os.path.exists("logo_map.json"):
        with open("logo_map.json") as f:
            return json.load(f)
    return {}

def load_injuries():
    if os.path.exists("injuries.json"):
        with open("injuries.json", encoding="utf-8") as f:
            return json.load(f).get("teams", {})
    return {}


def fixture_slug(fixture):
    """Convert 'Arsenal vs Chelsea' to 'arsenal-vs-chelsea'."""
    return fixture.lower().replace(" ", "-").replace("'", "").replace(".", "")


def explain_prediction(m, ex, injuries):
    """
    Generate qualitative reasoning for the model's prediction.
    Returns a list of evidence strings.
    """
    parts  = m.get("fixture","").split(" vs ")
    home   = parts[0] if parts else ""
    away   = parts[1] if len(parts)>1 else ""
    hw     = m.get("home_win_prob",0)
    dr     = m.get("draw_prob",0)
    aw     = m.get("away_win_prob",0)
    o25    = m.get("over_2_5_prob",0)
    bt     = m.get("btts_prob",0)
    h_elo  = m.get("home_elo",1500)
    a_elo  = m.get("away_elo",1500)
    h_xg   = ex.get("home_corners",{}).get("avg_gf",1.3)
    a_xg   = ex.get("away_corners",{}).get("avg_gf",1.3)
    h_xga  = ex.get("home_corners",{}).get("avg_ga",1.3)
    a_xga  = ex.get("away_corners",{}).get("avg_ga",1.3)
    h_form = ex.get("home_form",[])
    a_form = ex.get("away_form",[])
    h2h    = ex.get("h2h",[])
    h2h_hw = ex.get("h2h_home_wins",0)
    h2h_d  = ex.get("h2h_draws",0)
    h2h_aw = ex.get("h2h_away_wins",0)
    h_inj  = injuries.get(home,{})
    a_inj  = injuries.get(away,{})

    reasons = []
    best    = max(hw,dr,aw)

    # ── RESULT REASONING ──
    if hw == best:
        reasons.append({"type":"result","icon":"🏠","title":f"{home} favoured at home",
            "text":f"The model gives {home} a {hw:.0%} chance of winning. Elo rating of {h_elo:.0f} vs {a_elo:.0f} suggests {home} are the stronger side. Home advantage is a significant factor in this prediction."})
    elif aw == best:
        reasons.append({"type":"result","icon":"✈️","title":f"{away} strong away form",
            "text":f"The model gives {away} a {aw:.0%} chance of winning away. Their Elo of {a_elo:.0f} significantly exceeds {home}'s {h_elo:.0f}, indicating {away} are the class side despite travelling."})
    else:
        reasons.append({"type":"result","icon":"⚖️","title":"Teams evenly matched",
            "text":f"Draw probability is {dr:.0%} — both teams are closely matched. Elo ratings ({h_elo:.0f} vs {a_elo:.0f}) show little to separate them, and neither side has significantly better recent form."})

    # ── ELO ──
    elo_diff = abs(h_elo - a_elo)
    stronger = home if h_elo > a_elo else away
    weaker   = away if h_elo > a_elo else home
    if elo_diff > 100:
        reasons.append({"type":"elo","icon":"📊","title":f"Elo advantage: {stronger}",
            "text":f"{stronger} hold a {elo_diff:.0f}-point Elo advantage over {weaker}. Elo is a rolling skill rating updated after every match — a gap this size reflects a consistent performance difference across the season."})
    elif elo_diff > 50:
        reasons.append({"type":"elo","icon":"📊","title":"Slight Elo edge",
            "text":f"A {elo_diff:.0f}-point Elo gap between the sides — a small but meaningful difference. The stronger-rated team wins about 55-58% of fixtures at this gap historically."})

    # ── FORM ──
    if h_form:
        h_wins = h_form.count("W"); h_losses = h_form.count("L")
        if h_wins >= 4:
            reasons.append({"type":"form","icon":"🔥","title":f"{home} in excellent form",
                "text":f"{home} have won {h_wins} of their last {len(h_form)} matches. This momentum is reflected in the model's probability — teams in good form tend to continue performing."})
        elif h_losses >= 3:
            reasons.append({"type":"form","icon":"📉","title":f"{home} struggling",
                "text":f"{home} have lost {h_losses} of their last {len(h_form)} matches. Poor form is a key signal the model uses — it adjusts probabilities down for teams in bad runs."})

    if a_form:
        a_wins = a_form.count("W"); a_losses = a_form.count("L")
        if a_wins >= 4:
            reasons.append({"type":"form","icon":"⚡","title":f"{away} firing on all cylinders",
                "text":f"{away} have won {a_wins} of their last {len(a_form)} away fixtures. The model weights recent form heavily — this run significantly boosts their win probability."})
        elif a_losses >= 3:
            reasons.append({"type":"form","icon":"😰","title":f"{away} out of form",
                "text":f"{away} have lost {a_losses} of their last {len(a_form)} matches. The model penalises poor-form teams, which suppresses {away}'s away win probability."})

    # ── GOALS ──
    if o25 >= 0.60:
        reasons.append({"type":"goals","icon":"⚽","title":"High-scoring game expected",
            "text":f"{o25:.0%} chance of Over 2.5 goals. {home} average {h_xg:.1f} goals scored per game while {away} concede {a_xga:.1f} per game — this creates the conditions for an open, high-scoring match."})
    elif o25 <= 0.40:
        reasons.append({"type":"goals","icon":"🛡️","title":"Tight, low-scoring game expected",
            "text":f"Only {o25:.0%} chance of Over 2.5 goals. Both teams' recent averages suggest a compact, defensive encounter. {home} concede {h_xga:.1f} per game and {away} score just {a_xg:.1f} per game."})

    if bt >= 0.60:
        reasons.append({"type":"btts","icon":"🎯","title":"Both teams likely to score",
            "text":f"{bt:.0%} BTTS probability. {home} score {h_xg:.1f} per game and {away} score {a_xg:.1f} per game — both sides have the attacking quality to trouble each other's defence."})

    # ── H2H ──
    if h2h:
        total_h2h = h2h_hw + h2h_d + h2h_aw
        if h2h_hw >= 3:
            reasons.append({"type":"h2h","icon":"📜","title":f"{home} dominate H2H",
                "text":f"{home} have won {h2h_hw} of the last {total_h2h} meetings between these sides. Historical H2H patterns are a supporting signal in the model — some rivalries consistently favour one team."})
        elif h2h_aw >= 3:
            reasons.append({"type":"h2h","icon":"📜","title":f"{away} have H2H edge",
                "text":f"{away} have won {h2h_aw} of the last {total_h2h} head-to-heads. Away sides that historically outperform at a venue tend to replicate this pattern."})
        elif h2h_d >= 3:
            reasons.append({"type":"h2h","icon":"📜","title":"These sides draw often",
                "text":f"{h2h_d} draws in {total_h2h} recent meetings. Some matchups are structurally balanced — tactically similar teams often cancel each other out, supporting the draw probability."})

    # ── INJURIES ──
    h_key = sum(1 for p in h_inj.get("unavailable",[]) if p.get("is_key"))
    a_key = sum(1 for p in a_inj.get("unavailable",[]) if p.get("is_key"))
    if h_key > 0:
        names = [p["name"] for p in h_inj.get("unavailable",[]) if p.get("is_key")]
        reasons.append({"type":"injury","icon":"🚑","title":f"{home} missing key players",
            "text":f"{', '.join(names[:2])} {'is' if len(names)==1 else 'are'} unavailable for {home}. Key player absences reduce the team's expected performance, suppressing their win probability."})
    if a_key > 0:
        names = [p["name"] for p in a_inj.get("unavailable",[]) if p.get("is_key")]
        reasons.append({"type":"injury","icon":"🚑","title":f"{away} missing key players",
            "text":f"{', '.join(names[:2])} {'is' if len(names)==1 else 'are'} unavailable for {away}. This is factored into the model's prediction — their probability is adjusted downward."})

    return reasons


def stat_bar(val, max_val, color="var(--g)"):
    pct = min(int(val/max_val*100), 100) if max_val > 0 else 0
    return f'<div class="sbar-wrap"><div class="sbar" style="width:{pct}%;background:{color}"></div></div>'


def generate_match_page(m, ex, players_for_fix, injuries, logos):
    parts  = m.get("fixture","").split(" vs ")
    home   = parts[0] if parts else "Home"
    away   = parts[1] if len(parts)>1 else "Away"
    date   = m.get("date","")
    hw,dr,aw = m.get("home_win_prob",0),m.get("draw_prob",0),m.get("away_win_prob",0)
    o25,bt   = m.get("over_2_5_prob",0),m.get("btts_prob",0)
    h_elo,a_elo = m.get("home_elo",1500),m.get("away_elo",1500)
    iho,idr,iaw = m.get("implied_home_odds",0),m.get("implied_draw_odds",0),m.get("implied_away_odds",0)
    h_form  = ex.get("home_form",[])
    a_form  = ex.get("away_form",[])
    h2h     = ex.get("h2h",[])
    h2h_hw  = ex.get("h2h_home_wins",0)
    h2h_d   = ex.get("h2h_draws",0)
    h2h_aw  = ex.get("h2h_away_wins",0)
    hcc     = ex.get("home_corners",{})
    acc     = ex.get("away_corners",{})
    pred_cor= ex.get("pred_corners",10.5)
    h_inj   = injuries.get(home,{})
    a_inj   = injuries.get(away,{})
    reasons = explain_prediction(m, ex, injuries)

    # Logo images
    def logo(team, size=64):
        url = logos.get(team,"")
        if url:
            # Use absolute path for GitHub Pages compatibility
            abs_url = url if url.startswith("http") else f"/pl-intel/{url}"
            return f'<img src="{abs_url}" class="mp-logo" width="{size}" height="{size}" alt="{team}">'
        return f'<div class="mp-logo-ph">{team[:3].upper()}</div>'

    # Form strip
    def form_strip(strip):
        if not strip: return '<span class="no-data">No data</span>'
        h = ""
        for r in strip:
            cls = "fw" if r=="W" else "fd" if r=="D" else "fl"
            h += f'<span class="fd-dot {cls}">{r}</span>'
        return h

    # H2H mini results
    h2h_rows = ""
    for match in h2h[:5]:
        hg = match.get("home_goals",0)
        ag = match.get("away_goals",0)
        result = match.get("result","")
        dt = match.get("date","")[:7]
        h2h_rows += f'<div class="h2h-row"><span class="h2h-dt">{dt}</span><span>{home}</span><span class="h2h-sc">{hg} - {ag}</span><span>{away}</span></div>'

    # Players
    home_players = [p for p in players_for_fix if p.get("team")==home][:6]
    away_players = [p for p in players_for_fix if p.get("team")==away][:6]

    def player_row(p):
        sp,ap,yp = p.get("score_prob",0),p.get("assist_prob",0),p.get("yellow_prob",0)
        pos = p.get("position","MID")
        return f'''<div class="mp-player">
  <div class="mp-player-top">
    <span class="mp-pos p{pos.lower()}">{pos}</span>
    <span class="mp-pname">{p.get("name","")}</span>
  </div>
  <div class="mp-stats">
    <div class="mp-stat"><div class="mp-sv {"sg" if sp>=0.45 else ""}">{sp:.0%}</div><div class="mp-sl">Score</div></div>
    <div class="mp-stat"><div class="mp-sv">{ap:.0%}</div><div class="mp-sl">Assist</div></div>
    <div class="mp-stat"><div class="mp-sv {"sy" if yp>=0.35 else ""}">{yp:.0%}</div><div class="mp-sl">Card</div></div>
  </div>
  <div class="mp-bars">
    {stat_bar(sp, 0.7)}
  </div>
</div>'''

    # Injury section
    def inj_section(team_name, inj_data):
        unavail = inj_data.get("unavailable",[])
        doubtful= inj_data.get("doubtful",[])
        if not unavail and not doubtful:
            return f'<div class="inj-clear">✅ No injury concerns reported</div>'
        rows = ""
        for p in unavail:
            rows += f'<div class="inj-item"><span class="inj-pos p{p["position"].lower()}">{p["position"]}</span><span class="inj-nm">{p["name"]}</span><span class="inj-st red">{p["status_label"]}</span><span class="inj-nw">{p.get("news","") or "No details"}</span></div>'
        for p in doubtful:
            rows += f'<div class="inj-item"><span class="inj-pos p{p["position"].lower()}">{p["position"]}</span><span class="inj-nm">{p["name"]}</span><span class="inj-st amber">Doubtful</span><span class="inj-nw">{p.get("news","") or "Being assessed"}</span></div>'
        return rows

    # Reasons HTML
    type_colors = {
        "result":"var(--g)","elo":"var(--b)","form":"var(--go)",
        "goals":"#ff6b9d","btts":"var(--pu)","h2h":"#4ecdc4",
        "injury":"var(--r)","weather":"#74b9ff",
    }
    reasons_html = ""
    for r in reasons:
        col = type_colors.get(r["type"],"var(--g)")
        reasons_html += f'''<div class="reason">
  <div class="reason-icon">{r["icon"]}</div>
  <div class="reason-body">
    <div class="reason-title" style="color:{col}">{r["title"]}</div>
    <div class="reason-text">{r["text"]}</div>
  </div>
</div>'''

    # Best bet call
    best_prob = max(hw,dr,aw,o25,bt)
    if hw == best_prob and hw >= 0.55:
        best_bet = f"{home} Win @ {iho:.2f}"
        best_conf = f"{hw:.0%} model probability"
    elif aw == best_prob and aw >= 0.55:
        best_bet = f"{away} Win @ {iaw:.2f}"
        best_conf = f"{aw:.0%} model probability"
    elif o25 >= 0.60:
        best_bet = f"Over 2.5 Goals"
        best_conf = f"{o25:.0%} model probability"
    elif bt >= 0.60:
        best_bet = "Both Teams to Score"
        best_conf = f"{bt:.0%} model probability"
    elif dr >= 0.40:
        best_bet = f"Draw @ {idr:.2f}"
        best_conf = f"{dr:.0%} model probability"
    else:
        best_bet = "No strong signal — skip this game"
        best_conf = "Low confidence across all markets"

    try:
        date_display = datetime.strptime(date, "%Y-%m-%d").strftime("%A %d %B %Y")
    except:
        date_display = date

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{home} vs {away} — PL Intel</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Barlow:wght@300;400;500;600&family=Barlow+Condensed:wght@500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
:root{{
  --bg:#060810;--s1:#0b0e16;--s2:#10141e;--s3:#151a26;
  --bd:rgba(255,255,255,.055);--bd2:rgba(255,255,255,.09);
  --g:#00ff87;--go:#ff9f00;--r:#ff3355;--b:#4488ff;--pu:#aa77ff;
  --tx:#dde4f4;--mu:#5a6480;
  --df:'Anton',sans-serif;--db:'Barlow',sans-serif;--dc:'Barlow Condensed',sans-serif;--dm:'JetBrains Mono',monospace;
}}
html{{scroll-behavior:smooth}}
body{{background:var(--bg);color:var(--tx);font-family:var(--db);font-size:14px;min-height:100vh}}

/* Atmospheric background */
body::after{{content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse 100% 50% at 50% -10%, rgba(0,255,135,.04) 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 10% 90%, rgba(68,136,255,.03) 0%, transparent 55%),
    radial-gradient(ellipse 60% 40% at 90% 90%, rgba(255,51,85,.02) 0%, transparent 55%);
}}

.wrap{{position:relative;z-index:1;max-width:1100px;margin:0 auto;padding:0 20px 80px}}

/* BACK BUTTON */
.back{{display:inline-flex;align-items:center;gap:8px;padding:10px 16px;background:var(--s2);border:1px solid var(--bd);border-radius:8px;color:var(--mu);font-family:var(--dm);font-size:10px;text-decoration:none;letter-spacing:1px;text-transform:uppercase;margin-top:24px;transition:all .2s}}
.back:hover{{color:var(--tx);border-color:var(--bd2)}}

/* HERO */
.hero{{padding:40px 0 32px;border-bottom:1px solid var(--bd);margin-bottom:40px}}
.hero-date{{font-family:var(--dm);font-size:10px;color:var(--mu);letter-spacing:3px;text-transform:uppercase;margin-bottom:20px}}
.hero-teams{{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:20px;margin-bottom:28px}}
.hero-team{{display:flex;flex-direction:column;align-items:center;gap:12px;text-align:center}}
.hero-team.away{{}}
.mp-logo{{object-fit:contain;filter:drop-shadow(0 4px 16px rgba(0,0,0,.6))}}
.mp-logo-ph{{width:64px;height:64px;background:var(--s3);border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:var(--dm);font-size:12px;color:var(--mu)}}
.hero-tname{{font-family:var(--df);font-size:32px;letter-spacing:2px;color:#fff;line-height:1}}
.hero-form{{display:flex;gap:4px;justify-content:center}}
.hero-mid{{text-align:center}}
.hero-vs{{font-family:var(--df);font-size:48px;color:var(--mu);letter-spacing:4px;display:block;line-height:1}}
.hero-elo{{font-family:var(--dm);font-size:10px;color:var(--mu);margin-top:6px}}

/* PROBABILITY BAR */
.prob-bar{{display:grid;grid-template-columns:1fr auto 1fr;gap:0;background:var(--s2);border:1px solid var(--bd);border-radius:12px;overflow:hidden;margin-bottom:28px}}
.pb-item{{padding:16px 20px;text-align:center}}
.pb-item.winner{{background:rgba(0,255,135,.06)}}
.pb-label{{font-family:var(--dm);font-size:9px;text-transform:uppercase;letter-spacing:1px;color:var(--mu);margin-bottom:6px}}
.pb-prob{{font-family:var(--df);font-size:42px;color:#fff;line-height:1}}
.pb-item.winner .pb-prob{{color:var(--g)}}
.pb-odds{{font-family:var(--dm);font-size:11px;color:var(--mu);margin-top:4px}}
.pb-div{{width:1px;background:var(--bd);margin:12px 0}}

/* BEST BET CALLOUT */
.best-bet{{background:linear-gradient(135deg,rgba(0,255,135,.08) 0%,rgba(0,255,135,.02) 100%);border:1px solid rgba(0,255,135,.2);border-radius:12px;padding:20px 24px;margin-bottom:32px;display:flex;align-items:center;gap:20px}}
.bb-icon{{font-size:32px}}
.bb-label{{font-family:var(--dm);font-size:9px;text-transform:uppercase;letter-spacing:2px;color:var(--mu);margin-bottom:4px}}
.bb-bet{{font-family:var(--df);font-size:28px;color:var(--g);letter-spacing:1px}}
.bb-conf{{font-family:var(--dm);font-size:11px;color:var(--mu);margin-top:3px}}

/* SECTION LAYOUT */
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}}
.grid3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px}}
.sec{{background:var(--s2);border:1px solid var(--bd);border-radius:12px;padding:20px}}
.sec-full{{background:var(--s2);border:1px solid var(--bd);border-radius:12px;padding:20px;margin-bottom:16px}}
.sec-h{{font-family:var(--dm);font-size:9px;text-transform:uppercase;letter-spacing:2px;color:var(--mu);margin-bottom:14px}}
.sec-title-big{{font-family:var(--df);font-size:22px;letter-spacing:2px;color:#fff;margin-bottom:16px}}

/* STAT BARS */
.stat-row{{display:flex;align-items:center;gap:10px;margin-bottom:10px}}
.stat-label{{font-size:12px;color:var(--mu);width:110px;flex-shrink:0}}
.sbar-wrap{{flex:1;height:5px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden}}
.sbar{{height:100%;border-radius:3px;transition:width .4s ease}}
.stat-val{{font-family:var(--dm);font-size:11px;color:var(--tx);width:36px;text-align:right;flex-shrink:0}}

/* MARKET PILLS */
.markets{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:24px}}
.mkt-pill{{display:flex;flex-direction:column;align-items:center;background:var(--s2);border:1px solid var(--bd);border-radius:10px;padding:12px 16px;min-width:90px}}
.mkt-pill.hot{{border-color:rgba(0,255,135,.25);background:rgba(0,255,135,.04)}}
.mkt-name{{font-family:var(--dm);font-size:9px;text-transform:uppercase;color:var(--mu);letter-spacing:1px;margin-bottom:5px}}
.mkt-prob{{font-family:var(--df);font-size:26px;line-height:1;color:#fff}}
.mkt-pill.hot .mkt-prob{{color:var(--g)}}
.mkt-odds{{font-family:var(--dm);font-size:10px;color:var(--mu);margin-top:3px}}

/* H2H */
.h2h-row{{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.03);font-size:12px}}
.h2h-row:last-child{{border-bottom:none}}
.h2h-dt{{font-family:var(--dm);font-size:9px;color:var(--mu)}}
.h2h-sc{{font-family:var(--df);font-size:16px;color:#fff;text-align:center}}

/* PLAYERS */
.mp-player{{background:var(--s1);border:1px solid var(--bd);border-radius:8px;padding:12px;margin-bottom:7px}}
.mp-player-top{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.mp-pos{{font-family:var(--dm);font-size:8px;padding:2px 5px;border-radius:3px;text-transform:uppercase}}
.pfwd{{background:rgba(255,51,85,.15);color:#ff6b7a}}
.pmid{{background:rgba(0,255,135,.1);color:var(--g)}}
.pdef{{background:rgba(68,136,255,.12);color:#6da8ff}}
.pgk{{background:rgba(255,159,0,.12);color:var(--go)}}
.mp-pname{{font-size:13px;font-weight:500;color:#fff}}
.mp-stats{{display:flex;gap:10px;margin-bottom:7px}}
.mp-stat{{text-align:center}}
.mp-sv{{font-family:var(--df);font-size:17px;line-height:1;color:var(--mu)}}
.mp-sv.sg{{color:var(--g)}}.mp-sv.sy{{color:var(--go)}}
.mp-sl{{font-family:var(--dm);font-size:8px;text-transform:uppercase;color:var(--mu);margin-top:1px}}
.mp-bars{{margin-top:5px}}

/* REASONS */
.reasons-grid{{display:grid;gap:10px}}
.reason{{display:flex;gap:16px;background:var(--s1);border:1px solid var(--bd);border-radius:10px;padding:16px}}
.reason-icon{{font-size:24px;flex-shrink:0;line-height:1;margin-top:2px}}
.reason-body{{flex:1}}
.reason-title{{font-family:var(--dc);font-size:14px;font-weight:600;letter-spacing:.5px;margin-bottom:5px}}
.reason-text{{font-size:13px;color:var(--mu);line-height:1.7}}

/* INJURIES */
.inj-item{{display:flex;align-items:flex-start;gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.03);flex-wrap:wrap}}
.inj-item:last-child{{border-bottom:none}}
.inj-pos{{font-family:var(--dm);font-size:8px;padding:2px 5px;border-radius:3px;text-transform:uppercase;flex-shrink:0}}
.inj-nm{{font-size:12px;font-weight:500;color:#fff;flex:1;min-width:120px}}
.inj-st{{font-family:var(--dm);font-size:9px;padding:2px 7px;border-radius:8px;flex-shrink:0}}
.inj-st.red{{background:rgba(255,51,85,.15);color:#ff6b7a}}
.inj-st.amber{{background:rgba(255,159,0,.15);color:var(--go)}}
.inj-nw{{font-size:11px;color:var(--mu);width:100%;padding-left:0;line-height:1.5}}
.inj-clear{{font-size:12px;color:var(--g);padding:8px 0}}

/* FORM DOTS */
.fd-dot{{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:5px;font-family:var(--dm);font-size:9px;font-weight:500;margin-right:3px}}
.fw{{background:rgba(0,255,135,.15);color:var(--g)}}
.fd{{background:rgba(255,159,0,.15);color:var(--go)}}
.fl{{background:rgba(255,51,85,.15);color:var(--r)}}
.no-data{{font-size:11px;color:var(--mu);font-style:italic}}

/* CORNER/CARD GRID */
.cc-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.cc-item{{background:var(--s1);border:1px solid var(--bd);border-radius:8px;padding:14px;text-align:center}}
.cc-val{{font-family:var(--df);font-size:32px;color:#fff;line-height:1}}
.cc-val.hot{{color:var(--g)}}
.cc-lbl{{font-family:var(--dm);font-size:9px;text-transform:uppercase;color:var(--mu);margin-top:4px;letter-spacing:1px}}
.cc-sub{{font-size:11px;color:var(--mu);margin-top:3px}}

footer{{text-align:center;color:var(--mu);font-family:var(--dm);font-size:9px;letter-spacing:1px;padding-top:24px;border-top:1px solid var(--bd);margin-top:60px;line-height:2.5}}

@media(max-width:640px){{
  .hero-teams{{grid-template-columns:1fr auto 1fr}}
  .hero-tname{{font-size:20px}}
  .hero-vs{{font-size:32px}}
  .prob-bar{{grid-template-columns:1fr 1fr 1fr}}
  .pb-prob{{font-size:28px}}
  .grid2{{grid-template-columns:1fr}}
  .grid3{{grid-template-columns:1fr 1fr}}
  .cc-grid{{grid-template-columns:1fr 1fr}}
}}
</style>
</head>
<body>
<div class="wrap">

<a href="../index.html" class="back">← Back to PL Intel</a>

<div class="hero">
  <div class="hero-date">{date_display} · Premier League</div>
  <div class="hero-teams">
    <div class="hero-team">
      {logo(home, 72)}
      <div class="hero-tname">{home}</div>
      <div class="hero-form">{form_strip(h_form)}</div>
    </div>
    <div class="hero-mid">
      <span class="hero-vs">VS</span>
      <div class="hero-elo">{h_elo:.0f} elo — {a_elo:.0f} elo</div>
    </div>
    <div class="hero-team away">
      {logo(away, 72)}
      <div class="hero-tname">{away}</div>
      <div class="hero-form">{form_strip(a_form)}</div>
    </div>
  </div>

  <div class="prob-bar">
    <div class="pb-item {'winner' if hw==max(hw,dr,aw) else ''}">
      <div class="pb-label">Home Win</div>
      <div class="pb-prob">{hw:.0%}</div>
      <div class="pb-odds">Fair odds: {iho:.2f}</div>
    </div>
    <div class="pb-div"></div>
    <div class="pb-item {'winner' if dr==max(hw,dr,aw) else ''}">
      <div class="pb-label">Draw</div>
      <div class="pb-prob">{dr:.0%}</div>
      <div class="pb-odds">Fair odds: {idr:.2f}</div>
    </div>
    <div class="pb-div"></div>
    <div class="pb-item {'winner' if aw==max(hw,dr,aw) else ''}">
      <div class="pb-label">Away Win</div>
      <div class="pb-prob">{aw:.0%}</div>
      <div class="pb-odds">Fair odds: {iaw:.2f}</div>
    </div>
  </div>

  <div class="best-bet">
    <div class="bb-icon">★</div>
    <div>
      <div class="bb-label">Model's best bet</div>
      <div class="bb-bet">{best_bet}</div>
      <div class="bb-conf">{best_conf} · Not financial advice</div>
    </div>
  </div>
</div>

<!-- MARKETS -->
<div class="sec-title-big">MARKETS</div>
<div class="markets">
  <div class="mkt-pill {'hot' if o25>=0.60 else ''}">
    <div class="mkt-name">Over 2.5</div>
    <div class="mkt-prob">{o25:.0%}</div>
    <div class="mkt-odds">{round(1/o25,2) if o25>0 else '—'}</div>
  </div>
  <div class="mkt-pill {'hot' if bt>=0.60 else ''}">
    <div class="mkt-name">BTTS</div>
    <div class="mkt-prob">{bt:.0%}</div>
    <div class="mkt-odds">{round(1/bt,2) if bt>0 else '—'}</div>
  </div>
  <div class="mkt-pill {'hot' if pred_cor>=10.5 else ''}">
    <div class="mkt-name">Corners</div>
    <div class="mkt-prob">{pred_cor:.1f}</div>
    <div class="mkt-odds">{'O10.5 ✓' if pred_cor>=10.5 else 'U10.5'}</div>
  </div>
  <div class="mkt-pill">
    <div class="mkt-name">Under 2.5</div>
    <div class="mkt-prob">{1-o25:.0%}</div>
    <div class="mkt-odds">{round(1/(1-o25),2) if o25<1 else '—'}</div>
  </div>
  <div class="mkt-pill">
    <div class="mkt-name">No BTTS</div>
    <div class="mkt-prob">{1-bt:.0%}</div>
    <div class="mkt-odds">{round(1/(1-bt),2) if bt<1 else '—'}</div>
  </div>
</div>

<!-- WHY THE MODEL THINKS THIS -->
<div class="sec-full">
  <div class="sec-h">Why the model predicts this</div>
  <div class="reasons-grid">{reasons_html}</div>
</div>

<!-- TEAM STATS -->
<div class="grid2">
  <div class="sec">
    <div class="sec-h">{home} — Attack & Defence</div>
    <div class="stat-row"><span class="stat-label">Goals scored/g</span>{stat_bar(hcc.get("avg_gf",1.3),3,"var(--g)")}<span class="stat-val">{hcc.get("avg_gf",1.3):.2f}</span></div>
    <div class="stat-row"><span class="stat-label">Goals conceded/g</span>{stat_bar(hcc.get("avg_ga",1.3),3,"var(--r)")}<span class="stat-val">{hcc.get("avg_ga",1.3):.2f}</span></div>
    <div class="stat-row"><span class="stat-label">Corners for/g</span>{stat_bar(hcc.get("corners_for",5.5),10,"var(--b)")}<span class="stat-val">{hcc.get("corners_for",5.5):.1f}</span></div>
    <div class="stat-row"><span class="stat-label">Corners ag/g</span>{stat_bar(hcc.get("corners_against",5.5),10,"var(--mu)")}<span class="stat-val">{hcc.get("corners_against",5.5):.1f}</span></div>
    <div class="stat-row"><span class="stat-label">Elo rating</span>{stat_bar(h_elo,2200,"var(--go)")}<span class="stat-val">{h_elo:.0f}</span></div>
  </div>
  <div class="sec">
    <div class="sec-h">{away} — Attack & Defence</div>
    <div class="stat-row"><span class="stat-label">Goals scored/g</span>{stat_bar(acc.get("avg_gf",1.3),3,"var(--g)")}<span class="stat-val">{acc.get("avg_gf",1.3):.2f}</span></div>
    <div class="stat-row"><span class="stat-label">Goals conceded/g</span>{stat_bar(acc.get("avg_ga",1.3),3,"var(--r)")}<span class="stat-val">{acc.get("avg_ga",1.3):.2f}</span></div>
    <div class="stat-row"><span class="stat-label">Corners for/g</span>{stat_bar(acc.get("corners_for",5.5),10,"var(--b)")}<span class="stat-val">{acc.get("corners_for",5.5):.1f}</span></div>
    <div class="stat-row"><span class="stat-label">Corners ag/g</span>{stat_bar(acc.get("corners_against",5.5),10,"var(--mu)")}<span class="stat-val">{acc.get("corners_against",5.5):.1f}</span></div>
    <div class="stat-row"><span class="stat-label">Elo rating</span>{stat_bar(a_elo,2200,"var(--go)")}<span class="stat-val">{a_elo:.0f}</span></div>
  </div>
</div>

<!-- PLAYERS -->
<div class="grid2">
  <div class="sec">
    <div class="sec-h">{home} — Player Picks</div>
    {"".join(player_row(p) for p in home_players) or '<div class="no-data">No player data</div>'}
  </div>
  <div class="sec">
    <div class="sec-h">{away} — Player Picks</div>
    {"".join(player_row(p) for p in away_players) or '<div class="no-data">No player data</div>'}
  </div>
</div>

<!-- CORNERS & CARDS -->
<div class="sec-full">
  <div class="sec-h">Corners &amp; Cards Breakdown</div>
  <div class="cc-grid">
    <div class="cc-item">
      <div class="cc-val {'hot' if pred_cor>=10.5 else ''}">{pred_cor:.1f}</div>
      <div class="cc-lbl">Predicted Corners</div>
      <div class="cc-sub">{'O10.5 expected ✓' if pred_cor>=10.5 else 'Under 10.5 expected'}</div>
    </div>
    <div class="cc-item">
      <div class="cc-val">{hcc.get("corners_for",5.5)+acc.get("corners_for",5.5):.1f}</div>
      <div class="cc-lbl">Combined For Avg</div>
      <div class="cc-sub">{home} {hcc.get("corners_for",5.5):.1f} + {away} {acc.get("corners_for",5.5):.1f}</div>
    </div>
  </div>
</div>

<!-- H2H -->
<div class="sec-full">
  <div class="sec-h">Head to Head — Last {len(h2h)} meetings</div>
  {'<div class="h2h-summary" style="display:flex;gap:10px;margin-bottom:14px"><span style="background:rgba(0,255,135,.1);color:var(--g);padding:4px 12px;border-radius:6px;font-family:var(--dm);font-size:11px">'+str(h2h_hw)+' '+home+' wins</span><span style="background:rgba(255,159,0,.1);color:var(--go);padding:4px 12px;border-radius:6px;font-family:var(--dm);font-size:11px">'+str(h2h_d)+' draws</span><span style="background:rgba(255,51,85,.1);color:var(--r);padding:4px 12px;border-radius:6px;font-family:var(--dm);font-size:11px">'+str(h2h_aw)+' '+away+' wins</span></div>' if h2h else ''}
  {h2h_rows or '<div class="no-data">No H2H data available</div>'}
</div>

<!-- INJURIES -->
<div class="grid2">
  <div class="sec">
    <div class="sec-h">{home} — Availability</div>
    {inj_section(home, h_inj)}
  </div>
  <div class="sec">
    <div class="sec-h">{away} — Availability</div>
    {inj_section(away, a_inj)}
  </div>
</div>

<footer>PL INTEL · NOT FINANCIAL ADVICE · GAMBLE RESPONSIBLY · 18+</footer>
</div>
</body>
</html>"""

    return html


def generate_all_match_pages():
    """Generate individual pages for all upcoming fixtures."""
    os.makedirs("matches", exist_ok=True)

    matches   = load_latest("predictions_*.json")
    extra     = load_extra()
    logos     = load_logos()
    injuries  = load_injuries()

    player_files = glob.glob("player_preds_*.json")
    all_players  = []
    if player_files:
        with open(max(player_files, key=os.path.getmtime), encoding="utf-8") as f:
            player_data = json.load(f)
        for fix in player_data:
            for p in fix.get("players",[]):
                p["_fixture"] = fix.get("fixture","")
                all_players.append(p)

    page_map = {}
    print(f"Generating {len(matches)} match pages...")

    for m in matches:
        fixture    = m.get("fixture","")
        slug       = fixture_slug(fixture)
        ex         = extra.get(fixture, {})
        fix_players= [p for p in all_players if p.get("_fixture","") == fixture]

        html = generate_match_page(m, ex, fix_players, injuries, logos)

        filepath = os.path.join("matches", f"{slug}.html")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        page_map[fixture] = f"matches/{slug}.html"
        print(f"  ✅ {fixture}")

    # Save page map for site.py to use
    with open("match_pages.json", "w") as f:
        json.dump(page_map, f, indent=2)

    print(f"\nGenerated {len(page_map)} match pages")
    print("Saved page map to match_pages.json")
    return page_map


if __name__ == "__main__":
    generate_all_match_pages()
    input("\nPress Enter to close...")
