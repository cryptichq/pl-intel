"""
PL Intel - Site Generator v3
Full dashboard with all tabs.
Run: python site.py
"""
import json, glob, os, math
from datetime import datetime
from extradata import build_extra_data

def load_latest(pattern):
    files = glob.glob(pattern)
    if not files: return []
    with open(max(files, key=os.path.getmtime), encoding="utf-8") as f:
        return json.load(f)

def load_injuries():
    if os.path.exists("injuries.json"):
        with open("injuries.json", encoding="utf-8") as f:
            return json.load(f).get("teams",{})
    return {}

def load_live_scores():
    if os.path.exists("live_scores.json"):
        with open("live_scores.json", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_match_pages():
    if os.path.exists("match_pages.json"):
        with open("match_pages.json") as f:
            return json.load(f)
    return {}

def load_logos():
    if os.path.exists("logo_map.json"):
        with open("logo_map.json") as f:
            return json.load(f)
    return {}

def logo_img(team, logos, size=32):
    url = logos.get(team,"")
    if not url: return f'<div class="logo-placeholder">{team[:3].upper()}</div>'
    return f'<img src="{url}" alt="{team}" class="team-logo" width="{size}" height="{size}">'

def date_fmt(d):
    try: return datetime.strptime(d,"%Y-%m-%d").strftime("%A %d %B")
    except: return d

def pc(p):
    if p>=0.60: return "g"
    if p>=0.45: return "a"
    return "m"

def form_html(strip):
    if not strip: return '<span style="color:var(--mu);font-size:11px">No data</span>'
    h = ""
    for r in strip:
        cls = "fw" if r=="W" else "fd" if r=="D" else "fl"
        h += f'<span class="form-dot {cls}">{r}</span>'
    return h

def stars(n):
    return "★"*n + '<span style="opacity:.2">★</span>'*(3-n)

def movement_arrow(diff):
    if diff is None: return ""
    if diff < -0.1: return f'<span class="mov-down">↓{abs(diff):.2f}</span>'
    if diff > 0.1:  return f'<span class="mov-up">↑{diff:.2f}</span>'
    return '<span class="mov-flat">—</span>'

def injury_dropdown(team_name, injuries):
    team_data = injuries.get(team_name, {})
    unavail   = team_data.get("unavailable", [])
    doubtful  = team_data.get("doubtful", [])
    if not unavail and not doubtful: return ""
    total    = len(unavail) + len(doubtful)
    key_out  = sum(1 for p in unavail+doubtful if p.get("is_key"))
    badge_cls= "inj-red" if key_out>0 else "inj-amber"
    key_text = f" ({key_out} key)" if key_out>0 else ""
    uid      = team_name.replace(" ","_").replace("'","")
    rows     = ""
    for p in unavail:
        news = p.get("news","") or "No details"
        kf   = '<span class="kf">KEY</span>' if p.get("is_key") else ""
        rows += f'<div class="ir"><div class="ir-l"><span class="ipos p{p["position"].lower()}">{p["position"]}</span><span class="in">{p["name"]}</span>{kf}</div><div class="ir-r"><span class="is red">{p["status_label"]}</span><span class="inews">{news}</span></div></div>'
    for p in doubtful:
        news  = p.get("news","") or "Being assessed"
        chance= f'<span class="ic">{p["chance"]}%</span>' if p.get("chance") is not None else ""
        kf    = '<span class="kf">KEY</span>' if p.get("is_key") else ""
        rows += f'<div class="ir"><div class="ir-l"><span class="ipos p{p["position"].lower()}">{p["position"]}</span><span class="in">{p["name"]}</span>{kf}</div><div class="ir-r"><span class="is amber">Doubtful</span>{chance}<span class="inews">{news}</span></div></div>'
    return f'<div class="inj-drop"><button class="inj-btn {badge_cls}" onclick="tog(\'{uid}\')"><span>⚠</span>{team_name}: {total} out{key_text}<span class="chev" id="c-{uid}">▾</span></button><div class="inj-panel" id="i-{uid}" style="display:none">{rows}</div></div>'

def generate_bets(matches, players, min_prob=0.50):
    bets = []
    for m in matches:
        parts = m.get("fixture","").split(" vs ")
        home  = parts[0] if parts else ""
        away  = parts[1] if len(parts)>1 else ""
        hw,dr,aw = m.get("home_win_prob",0),m.get("draw_prob",0),m.get("away_win_prob",0)
        o25,bt   = m.get("over_2_5_prob",0),m.get("btts_prob",0)
        for prob,label,mkt in [
            (hw,f"{home} Win","Match Result"),
            (dr,"Draw","Match Result"),
            (aw,f"{away} Win","Match Result"),
            (o25,"Over 2.5 Goals","Goals"),
            (bt,"Both Teams Score","BTTS"),
        ]:
            if prob < min_prob: continue
            s = 3 if prob>=0.65 else 2 if prob>=0.55 else 1
            bets.append({"fixture":m.get("fixture",""),"date":m.get("date",""),
                "market":mkt,"bet":label,"prob":round(prob,3),
                "fair_odds":round(1/prob,2) if prob>0 else 99,"stars":s})
    for fix in players:
        for p in fix.get("players",[]):
            sp,yp = p.get("score_prob",0),p.get("yellow_prob",0)
            if sp>=0.42:
                s = 3 if sp>=0.60 else 2
                bets.append({"fixture":fix.get("fixture",""),"date":fix.get("date",""),
                    "market":"Anytime Scorer","bet":f"{p['name']} to Score",
                    "prob":round(sp,3),"fair_odds":round(1/sp,2),"stars":s,"team":p.get("team","")})
            if yp>=0.45:
                bets.append({"fixture":fix.get("fixture",""),"date":fix.get("date",""),
                    "market":"Player Card","bet":f"{p['name']} Booked",
                    "prob":round(yp,3),"fair_odds":round(1/yp,2),"stars":2,"team":p.get("team","")})
    bets.sort(key=lambda x:(-x["stars"],-x["prob"]))
    return bets

def main():
    print("Building extra data...")
    extra = build_extra_data()
    if not extra and os.path.exists("extra_data.json"):
        with open("extra_data.json",encoding="utf-8") as f:
            extra = json.load(f)

    matches  = load_latest("predictions_*.json")
    players  = load_latest("player_preds_*.json")
    injuries = load_injuries()
    logos      = load_logos()
    match_pages= load_match_pages()
    live_data= load_live_scores()
    vb_raw   = load_latest("value_finder_data_*.json")
    vb_real  = [v for v in vb_raw if v.get("expected_value",99)<5] if vb_raw else []
    bets     = generate_bets(matches, players)

    if not matches:
        print("No predictions found. Run: python pl.py --predict")
        input("Press Enter..."); return

    generated_at = datetime.now().strftime("%d %b %Y · %H:%M")
    by_date = {}
    for m in matches:
        by_date.setdefault(m.get("date","?"),[]).append(m)

    all_players = []
    for f in players:
        for p in f.get("players",[]):
            p["_fix"]=f.get("fixture",""); p["_date"]=f.get("date","")
            all_players.append(p)

    live_matches = live_data.get("matches",[])
    live_count   = live_data.get("live_count",0)
    live_bar = ""
    if live_matches:
        items = ""
        for m in live_matches:
            if m.get("is_live"):
                items += f'<div class="ls live"><span class="ls-t">{m["home"]} <b>{m["home_goals"]}-{m["away_goals"]}</b> {m["away"]}</span><span class="ls-m">{m.get("minute","")}\'</span><span class="ls-dot"></span></div>'
            elif m.get("is_finished"):
                items += f'<div class="ls fin"><span class="ls-t">{m["home"]} <b>{m["home_goals"]}-{m["away_goals"]}</b> {m["away"]}</span><span class="ls-ft">FT</span></div>'
            else:
                items += f'<div class="ls"><span class="ls-t">{m["home"]} vs {m["away"]}</span><span class="ls-ko">{m.get("kickoff","")}</span></div>'
        ft = live_data.get("fetched_at","")[:16].replace("T"," ")
        live_bar = f'<div class="lbar"><div class="lb-lbl">{"🔴 LIVE" if live_count>0 else "📅 TODAY"}</div><div class="lb-scr">{items}</div><div class="lb-t">Updated {ft}</div></div>'

    # ── TAB 1: PREDICTIONS ──
    pred_html = ""
    for date in sorted(by_date.keys()):
        pred_html += f'<div class="day-label">{date_fmt(date)}</div><div class="day-grid">'
        for m in by_date[date]:
            parts = m.get("fixture","").split(" vs ")
            home  = parts[0] if parts else ""
            away  = parts[1] if len(parts)>1 else ""
            hw,dr,aw = m.get("home_win_prob",0),m.get("draw_prob",0),m.get("away_win_prob",0)
            iho,idr,iaw = m.get("implied_home_odds",0),m.get("implied_draw_odds",0),m.get("implied_away_odds",0)
            o25,bt = m.get("over_2_5_prob",0),m.get("btts_prob",0)
            he,ae  = m.get("home_elo",0),m.get("away_elo",0)
            best   = max(hw,dr,aw)
            hc="winner" if hw==best else ""
            dc="winner" if dr==best else ""
            ac="winner" if aw==best else ""
            ex  = extra.get(m.get("fixture",""),{})
            hf  = form_html(ex.get("home_form",[]))
            af  = form_html(ex.get("away_form",[]))
            h2h = ex.get("h2h",[])
            h2h_hw,h2h_d,h2h_aw2 = ex.get("h2h_home_wins",0),ex.get("h2h_draws",0),ex.get("h2h_away_wins",0)
            mov = ex.get("odds_movement")
            h2h_bar = ""
            if h2h:
                h2h_bar = f'<div class="h2h-bar"><span class="h2h-lbl">Last {len(h2h)} H2H</span><span class="h2h-res h2h-h">{h2h_hw}W</span><span class="h2h-res h2h-d">{h2h_d}D</span><span class="h2h-res h2h-a">{h2h_aw2}W</span></div>'
            mov_bar = ""
            if mov:
                mov_bar = f'<div class="mov-bar"><span class="mov-lbl">Odds movement</span>{movement_arrow(mov.get("home_move"))}<span class="mov-sep">/</span>{movement_arrow(mov.get("draw_move"))}<span class="mov-sep">/</span>{movement_arrow(mov.get("away_move"))}</div>'
            hinj = injury_dropdown(home, injuries)
            ainj = injury_dropdown(away, injuries)
            cor  = ex.get("pred_corners",0)
            hl = logo_img(home, logos, 36)
            al = logo_img(away, logos, 36)
            pred_html += f'''<div class="fcard">
  <div class="fhead">
    <div class="fteam"><div class="fteam-top">{hl}<div class="fname">{home}</div></div><div class="fform">{hf}</div></div>
    <div class="fmid"><span class="fvs">VS</span>{f'<div class="felo">{he:.0f} — {ae:.0f}</div>' if he else ''}</div>
    <div class="fteam right"><div class="fteam-top right">{al}<div class="fname">{away}</div></div><div class="fform">{af}</div></div>
  </div>
  {h2h_bar}{mov_bar}
  {hinj}{ainj}
  <div class="fodds">
    <div class="fodd {hc}"><div class="fl2">Home</div><div class="fp">{hw:.0%}</div><div class="fo">{iho:.2f}</div></div>
    <div class="fodd {dc}"><div class="fl2">Draw</div><div class="fp">{dr:.0%}</div><div class="fo">{idr:.2f}</div></div>
    <div class="fodd {ac}"><div class="fl2">Away</div><div class="fp">{aw:.0%}</div><div class="fo">{iaw:.2f}</div></div>
  </div>
  <div class="fmkts">
    <div class="fmkt {'fh' if o25>=0.60 else ''}">O2.5 <b>{o25:.0%}</b></div>
    <div class="fmkt {'fh' if bt>=0.60 else ''}">BTTS <b>{bt:.0%}</b></div>
    <div class="fmkt">Corners <b>{cor:.1f}</b></div>
    {f'<a href="{match_pages.get(m.get("fixture",""), "#")}" class="fmkt fanalysis">Full Analysis →</a>' if match_pages.get(m.get("fixture","")) else ''}
  </div>
</div>'''
        pred_html += '</div>'

    # ── TAB 2: VALUE FINDER ──
    if vb_real:
        vb_html = ""
        for v in vb_real[:20]:
            ev   = v.get("expected_value",0)*100
            edge = v.get("edge",0)*100
            ec   = "ev-p" if ev>0 else "ev-n"
            vb_html += f'<div class="vcard"><div class="vh"><div><div class="vf">{v.get("fixture","")}</div><div class="vd">{v.get("date","")}</div></div><div class="ev-tag {ec}">EV {ev:+.0f}p/£1</div></div><div class="vm">{v.get("market","")}</div><div class="vn"><div><div class="vv g">{v.get("model_prob",0):.1%}</div><div class="vl">Model</div></div><div class="varr">→</div><div><div class="vv w">{v.get("bm_odds",0):.2f}</div><div class="vl">{v.get("bookmaker","Bookie")}</div></div><div><div class="vv gold">+{edge:.1f}%</div><div class="vl">Edge</div></div></div></div>'
    else:
        vb_html = '<div class="empty">Run valuefinder.py to see live bookmaker comparisons here</div>'

    # ── TAB 3: PLAYERS ──
    top_sc = sorted(all_players, key=lambda x:x.get("score_prob",0), reverse=True)[:24]
    top_yw = sorted(all_players, key=lambda x:x.get("yellow_prob",0), reverse=True)[:12]
    sc_html = '<div class="pgrid">'
    for p in top_sc:
        sp,ap,yp = p.get("score_prob",0),p.get("assist_prob",0),p.get("yellow_prob",0)
        sc_html += f'<div class="pcard"><div class="ppos p{p.get("position","MID").lower()}">{p.get("position","?")}</div><div class="pname">{p.get("name","")}</div><div class="pteam">{p.get("team","")}</div><div class="pfix">{p.get("_fix","")[:28]}</div><div class="pst"><div><div class="psv {pc(sp)}">{sp:.0%}</div><div class="psl">Score</div></div><div><div class="psv">{ap:.0%}</div><div class="psl">Assist</div></div><div><div class="psv">{yp:.0%}</div><div class="psl">Card</div></div></div></div>'
    sc_html += '</div>'
    yw_html = '<div class="pgrid">'
    for p in top_yw:
        yp = p.get("yellow_prob",0)
        yw_html += f'<div class="pcard cr"><div class="ppos p{p.get("position","MID").lower()}">{p.get("position","?")}</div><div class="pname">{p.get("name","")}</div><div class="pteam">{p.get("team","")}</div><div class="pfix">{p.get("_fix","")[:28]}</div><div class="pst"><div><div class="psv {pc(yp)}">{yp:.0%}</div><div class="psl">Yellow</div></div></div></div>'
    yw_html += '</div>'

    # ── TAB 4: BET SUGGESTIONS ──
    high = [b for b in bets if b["stars"]==3]
    med  = [b for b in bets if b["stars"]==2]
    bet_html = ""
    if high:
        bet_html += f'<div class="btitle high">★★★ High Confidence — {len(high)} bets</div>'
        for b in high[:20]:
            bet_html += f'<div class="bcard high"><div class="btop"><div><div class="bname">{b["bet"]}</div><div class="bfix">{b["fixture"]} · {b["date"]}</div></div><div class="bright"><div class="bstars">{stars(b["stars"])}</div><div class="bmkt">{b["market"]}</div></div></div><div class="bst"><div><div class="bsv g">{b["prob"]:.0%}</div><div class="bsl">Probability</div></div><div><div class="bsv w">{b["fair_odds"]:.2f}</div><div class="bsl">Fair Odds</div></div></div></div>'
    if med:
        bet_html += f'<div class="btitle med">★★ Medium Confidence — {len(med)} bets</div>'
        for b in med[:20]:
            bet_html += f'<div class="bcard med"><div class="btop"><div><div class="bname">{b["bet"]}</div><div class="bfix">{b["fixture"]} · {b["date"]}</div></div><div class="bright"><div class="bstars">{stars(b["stars"])}</div><div class="bmkt">{b["market"]}</div></div></div><div class="bst"><div><div class="bsv g">{b["prob"]:.0%}</div><div class="bsl">Probability</div></div><div><div class="bsv w">{b["fair_odds"]:.2f}</div><div class="bsl">Fair Odds</div></div></div></div>'
    if not bet_html:
        bet_html = '<div class="empty">No high-confidence bets found this week.</div>'

    # ── TAB 5: CORNERS & CARDS ──
    cc_html = ""
    for date in sorted(by_date.keys()):
        cc_html += f'<div class="day-label">{date_fmt(date)}</div>'
        for m in by_date[date]:
            fix = m.get("fixture","")
            ex  = extra.get(fix,{})
            parts= fix.split(" vs ")
            home = parts[0] if parts else ""
            away = parts[1] if len(parts)>1 else ""
            hcc  = ex.get("home_corners",{})
            acc  = ex.get("away_corners",{})
            pred_cor = ex.get("pred_corners",10.5)
            ref_yg = 3.5
            h_yg   = 1.8
            a_yg   = 1.8
            o10 = "fh" if pred_cor>=10.5 else ""
            o11 = "fh" if pred_cor>=11.0 else ""
            cc_html += f'''<div class="cccard">
  <div class="cctop"><div class="ccfix">{fix}</div><div class="ccdate">{m.get("date","")}</div></div>
  <div class="ccbody">
    <div class="ccsec">
      <div class="cctitle">⚽ Corners</div>
      <div class="ccrow"><span>{home}</span><span class="ccval">{hcc.get("corners_for",5.5):.1f} for / {hcc.get("corners_against",5.5):.1f} ag</span></div>
      <div class="ccrow"><span>{away}</span><span class="ccval">{acc.get("corners_for",5.5):.1f} for / {acc.get("corners_against",5.5):.1f} ag</span></div>
      <div class="ccpred">
        <div class="ccp-item {o10}">O10.5 <b>{"✓" if pred_cor>=10.5 else "✗"}</b></div>
        <div class="ccp-item {o11}">O11.5 <b>{"✓" if pred_cor>=11.5 else "✗"}</b></div>
        <div class="ccp-item">Pred: <b>{pred_cor:.1f}</b></div>
      </div>
    </div>
    <div class="ccsec">
      <div class="cctitle">🟨 Cards</div>
      <div class="ccrow"><span>{home} form</span><span class="ccval">{hcc.get("avg_gf",1.5):.1f} GF / {hcc.get("avg_ga",1.5):.1f} GA (L10)</span></div>
      <div class="ccrow"><span>{away} form</span><span class="ccval">{acc.get("avg_gf",1.5):.1f} GF / {acc.get("avg_ga",1.5):.1f} GA (L10)</span></div>
      <div class="ccpred">
        <div class="ccp-item">Ref avg: <b>{ref_yg:.1f} Y/g</b></div>
        <div class="ccp-item">Pred cards: <b>~{round(ref_yg*0.9,1)}</b></div>
      </div>
    </div>
  </div>
</div>'''

    # ── TAB 6: PLAYER vs DEFENCE ──
    pvp_html = ""
    for date in sorted(by_date.keys()):
        pvp_html += f'<div class="day-label">{date_fmt(date)}</div>'
        for m in by_date[date]:
            fix   = m.get("fixture","")
            ex    = extra.get(fix,{})
            matchups = ex.get("matchups",[])
            if not matchups: continue
            parts = fix.split(" vs ")
            pvp_html += f'<div class="pvpcard"><div class="pvptop"><div class="pvpfix">{fix}</div><div class="pvpdate">{m.get("date","")}</div></div><div class="pvpgrid">'
            for mu in matchups[:6]:
                opp    = mu.get("opp_name","")
                concede= mu.get("opp_concede",1.2)
                sp     = mu.get("score_prob",0)
                threat_cls = "high" if concede>1.5 else "med" if concede>1.0 else "low"
                pvp_html += f'''<div class="pvp">
  <div class="pvp-top">
    <div class="pvp-pos p{mu.get("position","mid").lower()}">{mu.get("position","?")}</div>
    <div class="pvp-prob {pc(sp)}">{sp:.0%}</div>
  </div>
  <div class="pvp-name">{mu.get("name","")}</div>
  <div class="pvp-team">{mu.get("team","")}</div>
  <div class="pvp-vs">vs {opp}</div>
  <div class="pvp-def {threat_cls}">Def concedes {concede:.1f} GA/g</div>
  <div class="pvp-xg">xG/90: {mu.get("xg_per90",0):.3f}</div>
</div>'''
            pvp_html += '</div></div>'

    # ── TAB 7: ACCA BUILDER ──
    acca_matches_js = json.dumps([{
        "fixture": m.get("fixture",""),
        "date":    m.get("date",""),
        "hw":      round(m.get("home_win_prob",0),3),
        "dr":      round(m.get("draw_prob",0),3),
        "aw":      round(m.get("away_win_prob",0),3),
        "iho":     round(m.get("implied_home_odds",0),2),
        "idr":     round(m.get("implied_draw_odds",0),2),
        "iaw":     round(m.get("implied_away_odds",0),2),
    } for m in matches])

    # ── RESULTS TRACKER ──
    tracker_html = '<div class="empty">No results logged yet. Run tracker.py --update after matches finish.</div>'
    if os.path.exists("results_log.json"):
        with open("results_log.json") as f:
            log = json.load(f)
        logged = log.get("matches",[])
        vb_log = log.get("value_bets",[])
        if logged:
            correct = sum(1 for m in logged if m["correct"])
            total   = len(logged)
            acc     = correct/total if total else 0
            vb_pnl  = sum(v["pnl"] for v in vb_log) if vb_log else 0
            vb_won  = sum(1 for v in vb_log if v["won"]) if vb_log else 0
            vb_tot  = len(vb_log)
            rows    = ""
            for ml in sorted(logged, key=lambda x:x["date"], reverse=True)[:15]:
                icon = "✅" if ml["correct"] else "❌"
                rows += f'<tr><td>{ml["fixture"]}</td><td class="tc">{ml["date"]}</td><td class="tc pred">{ml["predicted"]}</td><td class="tc act">{ml["actual"]}</td><td class="tc mono">{ml["score"]}</td><td class="tc">{icon}</td></tr>'
            tracker_html = f'''<div class="trstats">
  <div class="ts"><div class="tsv {"g" if acc>0.5 else "a"}">{acc:.0%}</div><div class="tsl">Accuracy</div></div>
  <div class="ts"><div class="tsv">{correct}/{total}</div><div class="tsl">Correct</div></div>
  <div class="ts"><div class="tsv {"g" if vb_pnl>0 else "r"}">{vb_pnl:+.1f}u</div><div class="tsl">Value P&L</div></div>
  <div class="ts"><div class="tsv">{vb_won}/{vb_tot}</div><div class="tsl">VB Won</div></div>
</div>
<table class="rtable"><thead><tr><th>Fixture</th><th>Date</th><th>Predicted</th><th>Actual</th><th>Score</th><th></th></tr></thead><tbody>{rows}</tbody></table>'''

    n_high = len(high); n_med = len(med)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PL Intel</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Barlow:wght@300;400;500;600&family=Barlow+Condensed:wght@500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
:root{{
  --bg:#060810;--s1:#0b0e16;--s2:#10141e;--s3:#151a26;
  --bd:rgba(255,255,255,0.055);--bd2:rgba(255,255,255,0.08);
  --g:#00ff87;--go:#ff9f00;--r:#ff3355;--b:#4488ff;--pu:#aa77ff;
  --tx:#dde4f4;--mu:#5a6480;
  --df:'Anton',sans-serif;--db:'Barlow',sans-serif;--dc:'Barlow Condensed',sans-serif;--dm:'JetBrains Mono',monospace;
}}
html{{scroll-behavior:smooth}}
body{{background:var(--bg);color:var(--tx);font-family:var(--db);font-size:14px;min-height:100vh;overflow-x:hidden}}
body::after{{content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(ellipse 80% 60% at 10% 5%,rgba(0,255,135,.03) 0%,transparent 55%),
             radial-gradient(ellipse 60% 50% at 90% 90%,rgba(68,136,255,.025) 0%,transparent 55%);}}
.wrap{{position:relative;z-index:1;max-width:1240px;margin:0 auto;padding:0 20px 100px}}

/* HEADER */
header{{padding:28px 0 22px;border-bottom:1px solid var(--bd);display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap}}
.logo-mark{{font-family:var(--df);font-size:54px;letter-spacing:5px;color:#fff;line-height:1}}
.logo-mark em{{color:var(--g);font-style:normal}}
.logo-sub{{font-family:var(--dm);font-size:9px;color:var(--mu);letter-spacing:3px;text-transform:uppercase;margin-top:4px;display:block}}
.hpills{{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}}
.pill{{display:inline-flex;align-items:center;gap:6px;background:var(--s2);border:1px solid var(--bd);border-radius:20px;padding:4px 12px;font-family:var(--dm);font-size:10px;color:var(--mu)}}
.pill b{{color:var(--tx)}}
.dot{{width:5px;height:5px;background:var(--g);border-radius:50%;display:inline-block;margin-right:3px;animation:blink 2s infinite}}
@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.2}}}}


/* LIVE BAR */
.lbar{{display:flex;align-items:center;gap:14px;background:var(--s2);border:1px solid var(--bd);border-radius:10px;padding:10px 16px;margin:18px 0 0;overflow:hidden}}
.lb-lbl{{font-family:var(--dm);font-size:9px;font-weight:500;color:var(--g);letter-spacing:2px;white-space:nowrap}}
.lb-scr{{display:flex;gap:10px;overflow-x:auto;flex:1;scrollbar-width:none}}
.lb-scr::-webkit-scrollbar{{display:none}}
.lb-t{{font-family:var(--dm);font-size:9px;color:var(--mu);white-space:nowrap}}
.ls{{display:flex;align-items:center;gap:8px;white-space:nowrap;padding:3px 10px;border-radius:6px;background:var(--s1);border:1px solid var(--bd);font-size:12px}}
.ls.live{{border-color:rgba(0,255,135,.2);background:rgba(0,255,135,.04)}}
.ls.fin{{opacity:.65}}
.ls-t b{{color:#fff;font-weight:600}}
.ls-m{{font-family:var(--dm);font-size:10px;color:var(--g)}}
.ls-ft,.ls-ko{{font-family:var(--dm);font-size:10px;color:var(--mu)}}
.ls-dot{{width:5px;height:5px;background:var(--g);border-radius:50%;animation:blink 1s infinite}}

/* NAV */
nav{{display:flex;gap:0;margin:20px 0 0;border-bottom:1px solid var(--bd);overflow-x:auto;scrollbar-width:none}}
nav::-webkit-scrollbar{{display:none}}
.tab{{font-family:var(--dm);font-size:10px;letter-spacing:1px;text-transform:uppercase;padding:12px 16px;color:var(--mu);cursor:pointer;border:none;background:transparent;border-bottom:2px solid transparent;transition:all .2s;white-space:nowrap;display:flex;align-items:center;gap:7px}}
.tab:hover{{color:var(--tx)}}
.tab.on{{color:var(--g);border-bottom-color:var(--g)}}
.badge{{font-family:var(--dm);font-size:9px;font-weight:500;padding:1px 6px;border-radius:8px;background:var(--g);color:#000}}
.badge.hot{{background:var(--go)}}

/* PANE */
.pane{{display:none;padding-top:24px}}.pane.on{{display:block}}
.day-label{{font-family:var(--dm);font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--mu);padding:4px 0 12px;margin-top:20px;border-bottom:1px solid var(--bd);margin-bottom:12px}}
.day-grid{{display:grid;gap:10px}}
.disc{{background:rgba(255,159,0,.05);border:1px solid rgba(255,159,0,.15);border-radius:8px;padding:11px 15px;margin-bottom:20px;font-size:12px;color:var(--mu);line-height:1.9}}
.disc strong{{color:var(--go)}}
.empty{{color:var(--mu);padding:48px;text-align:center;font-style:italic;line-height:2}}

/* TEAM LOGOS */
.team-logo{{object-fit:contain;filter:drop-shadow(0 1px 3px rgba(0,0,0,.4))}}
.logo-placeholder{{width:32px;height:32px;background:var(--s3);border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:var(--dm);font-size:8px;color:var(--mu);flex-shrink:0}}
.fteam-top{{display:flex;align-items:center;gap:10px}}
.fteam-top.right{{flex-direction:row-reverse}}

/* FIXTURE CARD */
.fcard{{background:var(--s2);border:1px solid var(--bd);border-radius:14px;overflow:hidden;transition:border-color .2s}}
.fcard:hover{{border-color:var(--bd2)}}
.fhead{{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px;padding:16px 18px 10px}}
.fteam{{display:flex;flex-direction:column;gap:6px}}
.fteam.right{{align-items:flex-end}}
.fname{{font-size:15px;font-weight:500;color:#fff}}
.fform{{display:flex;gap:3px}}
.form-dot{{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:4px;font-family:var(--dm);font-size:9px;font-weight:500}}
.fw{{background:rgba(0,255,135,.15);color:var(--g)}}
.fd{{background:rgba(255,159,0,.15);color:var(--go)}}
.fl{{background:rgba(255,51,85,.15);color:var(--r)}}
.fmid{{text-align:center}}
.fvs{{font-family:var(--df);font-size:16px;color:var(--mu);letter-spacing:2px;display:block}}
.felo{{font-family:var(--dm);font-size:9px;color:var(--mu);margin-top:3px}}
.h2h-bar,.mov-bar{{display:flex;align-items:center;gap:8px;padding:6px 18px;border-top:1px solid var(--bd);font-size:11px;flex-wrap:wrap}}
.h2h-lbl,.mov-lbl{{font-family:var(--dm);font-size:9px;color:var(--mu);text-transform:uppercase;letter-spacing:1px;margin-right:4px}}
.h2h-res{{font-family:var(--dm);font-size:11px;padding:2px 8px;border-radius:6px}}
.h2h-h{{background:rgba(0,255,135,.1);color:var(--g)}}
.h2h-d{{background:rgba(255,159,0,.1);color:var(--go)}}
.h2h-a{{background:rgba(255,51,85,.1);color:var(--r)}}
.h2h-sep{{color:var(--mu)}}
.mov-down{{color:var(--g);font-family:var(--dm);font-size:11px}}
.mov-up{{color:var(--r);font-family:var(--dm);font-size:11px}}
.mov-flat{{color:var(--mu);font-family:var(--dm);font-size:11px}}
.mov-sep{{color:var(--mu)}}

/* INJURY DROPDOWNS */
.inj-drop{{border-top:1px solid var(--bd)}}
.inj-btn{{width:100%;display:flex;align-items:center;gap:8px;padding:8px 16px;background:transparent;border:none;cursor:pointer;font-family:var(--db);font-size:12px;text-align:left;color:var(--tx);transition:background .15s}}
.inj-btn:hover{{background:rgba(255,255,255,.02)}}
.inj-red{{color:#ff6b7a}}.inj-amber{{color:var(--go)}}
.chev{{margin-left:auto;font-size:11px;color:var(--mu);transition:transform .2s}}
.chev.open{{transform:rotate(180deg)}}
.inj-panel{{background:var(--s1);border-top:1px solid var(--bd)}}
.ir{{display:flex;align-items:flex-start;justify-content:space-between;padding:7px 16px;border-bottom:1px solid rgba(255,255,255,.02);gap:10px}}
.ir:last-child{{border-bottom:none}}
.ir-l{{display:flex;align-items:center;gap:7px;min-width:160px;flex-wrap:wrap}}
.ir-r{{display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex:1}}
.ipos{{font-family:var(--dm);font-size:9px;padding:1px 5px;border-radius:3px;text-transform:uppercase}}
.pfwd{{background:rgba(255,51,85,.15);color:#ff6b7a}}
.pmid{{background:rgba(0,255,135,.1);color:var(--g)}}
.pdef{{background:rgba(68,136,255,.12);color:#6da8ff}}
.pgk{{background:rgba(255,159,0,.12);color:var(--go)}}
.in{{font-size:12px;color:var(--tx);font-weight:500}}
.kf{{background:rgba(255,159,0,.15);color:var(--go);font-family:var(--dm);font-size:8px;padding:1px 5px;border-radius:3px;text-transform:uppercase}}
.is{{font-family:var(--dm);font-size:10px;padding:2px 7px;border-radius:8px}}
.is.red{{background:rgba(255,51,85,.15);color:#ff6b7a}}
.is.amber{{background:rgba(255,159,0,.15);color:var(--go)}}
.ic{{font-family:var(--dm);font-size:11px;color:var(--go)}}
.inews{{font-size:11px;color:var(--mu);text-align:right;max-width:280px;line-height:1.5}}

/* ANALYSIS LINK */
.fanalysis{{background:rgba(0,255,135,.08);border-color:rgba(0,255,135,.2);color:var(--g);text-decoration:none;font-weight:500;transition:all .2s}}
.fanalysis:hover{{background:rgba(0,255,135,.15)}}

/* ODDS */
.fodds{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1px;background:var(--bd);border-top:1px solid var(--bd)}}
.fodd{{background:var(--s1);padding:11px 8px;text-align:center}}
.fodd.winner{{background:rgba(0,255,135,.06);border-top:2px solid rgba(0,255,135,.3)}}
.fl2{{font-size:9px;text-transform:uppercase;letter-spacing:1px;color:var(--mu);margin-bottom:3px}}
.fp{{font-family:var(--df);font-size:24px;color:#fff;line-height:1}}
.fodd.winner .fp{{color:var(--g)}}
.fo{{font-family:var(--dm);font-size:10px;color:var(--mu);margin-top:2px}}
.fmkts{{display:flex;gap:5px;padding:9px 14px;border-top:1px solid var(--bd);flex-wrap:wrap}}
.fmkt{{display:flex;align-items:center;gap:6px;background:var(--s1);border:1px solid var(--bd);border-radius:20px;padding:3px 11px;font-size:11px;color:var(--mu)}}
.fmkt b{{color:var(--tx);font-weight:500}}
.fmkt.fh{{border-color:rgba(0,255,135,.2);background:rgba(0,255,135,.04)}}
.fmkt.fh b{{color:var(--g)}}

/* VALUE */
.vcard{{background:var(--s2);border:1px solid var(--bd);border-radius:12px;padding:16px 18px;margin-bottom:9px}}
.vh{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:9px}}
.vf{{font-size:14px;font-weight:500;color:#fff}}
.vd{{font-family:var(--dm);font-size:9px;color:var(--mu);margin-top:3px}}
.ev-tag{{font-family:var(--df);font-size:15px;padding:3px 12px;border-radius:16px;letter-spacing:1px}}
.ev-p{{background:rgba(0,255,135,.1);color:var(--g)}}
.ev-n{{background:rgba(255,51,85,.1);color:var(--r)}}
.vm{{font-family:var(--df);font-size:20px;color:var(--go);letter-spacing:1px;margin-bottom:12px}}
.vn{{display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
.vv{{font-family:var(--df);font-size:24px;line-height:1}}
.vv.g{{color:var(--g)}}.vv.w{{color:#fff}}.vv.gold{{color:var(--go)}}
.vl{{font-family:var(--dm);font-size:9px;color:var(--mu);text-transform:uppercase;margin-top:2px}}
.varr{{font-size:18px;color:var(--mu)}}

/* PLAYERS */
.sec-title{{font-family:var(--dm);font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--mu);margin:24px 0 12px}}
.pgrid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(185px,1fr));gap:9px;margin-bottom:8px}}
.pcard{{background:var(--s2);border:1px solid var(--bd);border-radius:11px;padding:13px;position:relative;overflow:hidden}}
.pcard.cr{{border-color:rgba(255,51,85,.12)}}
.pcard::before{{content:'';position:absolute;top:0;right:0;width:55px;height:55px;border-radius:0 11px 0 55px;opacity:.05}}
.pcard:not(.cr)::before{{background:var(--g)}}.pcard.cr::before{{background:var(--r)}}
.ppos{{display:inline-block;font-family:var(--dm);font-size:8px;font-weight:500;padding:2px 6px;border-radius:4px;margin-bottom:7px;text-transform:uppercase;letter-spacing:1px}}
.pname{{font-size:13px;font-weight:500;color:#fff;margin-bottom:2px;line-height:1.3}}
.pteam{{font-size:11px;color:var(--mu);margin-bottom:3px}}
.pfix{{font-size:10px;color:var(--mu);opacity:.55;margin-bottom:9px}}
.pst{{display:flex;gap:8px}}
.psv{{font-family:var(--df);font-size:19px;line-height:1}}
.psv.g{{color:var(--g)}}.psv.a{{color:var(--go)}}.psv.m{{color:var(--mu)}}
.psl{{font-family:var(--dm);font-size:8px;text-transform:uppercase;color:var(--mu);margin-top:1px}}

/* BETS */
.btitle{{font-family:var(--dm);font-size:9px;font-weight:500;letter-spacing:2px;text-transform:uppercase;padding:5px 12px;border-radius:5px;margin:22px 0 11px;display:inline-block}}
.btitle.high{{background:rgba(0,255,135,.08);color:var(--g)}}
.btitle.med{{background:rgba(255,159,0,.08);color:var(--go)}}
.bcard{{background:var(--s2);border:1px solid var(--bd);border-radius:11px;padding:14px 18px;margin-bottom:7px}}
.bcard.high{{border-left:3px solid var(--g)}}
.bcard.med{{border-left:3px solid var(--go)}}
.btop{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}}
.bname{{font-size:14px;font-weight:500;color:#fff}}
.bfix{{font-family:var(--dm);font-size:9px;color:var(--mu);margin-top:3px}}
.bright{{text-align:right}}
.bstars{{font-size:14px;color:var(--go);display:block;margin-bottom:2px}}
.bmkt{{font-family:var(--dm);font-size:8px;text-transform:uppercase;color:var(--mu);letter-spacing:1px}}
.bst{{display:flex;gap:18px}}
.bsv{{font-family:var(--df);font-size:22px;line-height:1}}
.bsv.g{{color:var(--g)}}.bsv.w{{color:#fff}}
.bsl{{font-family:var(--dm);font-size:8px;text-transform:uppercase;color:var(--mu)}}

/* CORNERS & CARDS */
.cccard{{background:var(--s2);border:1px solid var(--bd);border-radius:12px;margin-bottom:9px;overflow:hidden}}
.cctop{{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--bd)}}
.ccfix{{font-size:14px;font-weight:500;color:#fff}}
.ccdate{{font-family:var(--dm);font-size:9px;color:var(--mu)}}
.ccbody{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--bd)}}
.ccsec{{background:var(--s2);padding:12px 16px}}
.cctitle{{font-family:var(--dm);font-size:9px;text-transform:uppercase;letter-spacing:1px;color:var(--mu);margin-bottom:8px}}
.ccrow{{display:flex;justify-content:space-between;font-size:12px;margin-bottom:5px;color:var(--tx)}}
.ccval{{font-family:var(--dm);font-size:11px;color:var(--mu)}}
.ccpred{{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}}
.ccp-item{{font-family:var(--dm);font-size:10px;padding:3px 9px;border-radius:6px;background:var(--s1);border:1px solid var(--bd);color:var(--mu)}}
.ccp-item b{{color:var(--tx)}}
.ccp-item.fh{{border-color:rgba(0,255,135,.2);background:rgba(0,255,135,.05)}}
.ccp-item.fh b{{color:var(--g)}}

/* PLAYER vs DEFENCE */
.pvpcard{{background:var(--s2);border:1px solid var(--bd);border-radius:12px;margin-bottom:9px;overflow:hidden}}
.pvptop{{display:flex;justify-content:space-between;align-items:center;padding:11px 16px;border-bottom:1px solid var(--bd)}}
.pvpfix{{font-size:14px;font-weight:500;color:#fff}}
.pvpdate{{font-family:var(--dm);font-size:9px;color:var(--mu)}}
.pvpgrid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:1px;background:var(--bd)}}
.pvp{{background:var(--s2);padding:12px 14px}}
.pvp-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}}
.pvp-pos{{font-family:var(--dm);font-size:8px;padding:2px 5px;border-radius:3px;text-transform:uppercase}}
.pvp-prob{{font-family:var(--df);font-size:22px;line-height:1}}
.pvp-name{{font-size:12px;font-weight:500;color:#fff;margin-bottom:2px}}
.pvp-team{{font-size:10px;color:var(--mu);margin-bottom:3px}}
.pvp-vs{{font-size:10px;color:var(--mu);margin-bottom:5px}}
.pvp-def{{font-family:var(--dm);font-size:10px;padding:3px 8px;border-radius:5px;display:inline-block;margin-bottom:3px}}
.pvp-def.high{{background:rgba(0,255,135,.1);color:var(--g)}}
.pvp-def.med{{background:rgba(255,159,0,.1);color:var(--go)}}
.pvp-def.low{{background:rgba(255,51,85,.1);color:var(--r)}}
.pvp-xg{{font-family:var(--dm);font-size:9px;color:var(--mu)}}

/* ACCA BUILDER */
.acca-wrap{{display:grid;grid-template-columns:1fr 340px;gap:20px;align-items:start}}
.acca-list{{display:grid;gap:8px}}
.acca-row{{background:var(--s2);border:1px solid var(--bd);border-radius:10px;padding:12px 14px}}
.acca-fix{{font-size:13px;font-weight:500;color:#fff;margin-bottom:8px}}
.acca-opts{{display:flex;gap:6px;flex-wrap:wrap}}
.acca-btn{{font-family:var(--dm);font-size:10px;padding:5px 12px;border-radius:7px;border:1px solid var(--bd);background:var(--s1);color:var(--mu);cursor:pointer;transition:all .15s}}
.acca-btn:hover{{border-color:var(--bd2);color:var(--tx)}}
.acca-btn.sel{{border-color:var(--g);background:rgba(0,255,135,.08);color:var(--g)}}
.acca-panel{{background:var(--s2);border:1px solid var(--bd);border-radius:12px;padding:20px;position:sticky;top:20px}}
.acca-title{{font-family:var(--df);font-size:28px;color:#fff;margin-bottom:4px}}
.acca-sub{{font-family:var(--dm);font-size:9px;color:var(--mu);text-transform:uppercase;letter-spacing:1px;margin-bottom:20px}}
.acca-legs{{display:grid;gap:6px;margin-bottom:20px;min-height:60px}}
.acca-leg{{display:flex;justify-content:space-between;font-size:12px;padding:6px 10px;background:var(--s1);border-radius:6px}}
.acca-leg span{{color:var(--mu)}}
.acca-leg b{{color:var(--tx)}}
.acca-empty{{color:var(--mu);font-size:12px;font-style:italic;text-align:center;padding:16px}}
.acca-result{{border-top:1px solid var(--bd);padding-top:16px}}
.acca-odds-big{{font-family:var(--df);font-size:52px;color:var(--g);line-height:1}}
.acca-prob{{font-family:var(--dm);font-size:12px;color:var(--mu);margin-bottom:12px}}
.acca-stake{{display:flex;align-items:center;gap:8px;margin-bottom:10px}}
.acca-stake label{{font-family:var(--dm);font-size:10px;color:var(--mu);text-transform:uppercase}}
.acca-input{{background:var(--s1);border:1px solid var(--bd);border-radius:6px;padding:6px 10px;color:#fff;font-family:var(--dm);font-size:13px;width:80px}}
.acca-return{{font-size:13px;color:var(--tx)}}
.acca-return b{{color:var(--g)}}
.acca-conf{{font-family:var(--dm);font-size:10px;margin-top:8px;padding:5px 10px;border-radius:5px;display:inline-block}}
.acca-clear{{font-family:var(--dm);font-size:9px;color:var(--mu);cursor:pointer;text-decoration:underline;margin-top:10px;display:inline-block}}

/* RESULTS TRACKER */
.trstats{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}}
.ts{{background:var(--s2);border:1px solid var(--bd);border-radius:11px;padding:14px;text-align:center}}
.tsv{{font-family:var(--df);font-size:30px;line-height:1;color:#fff}}
.tsv.g{{color:var(--g)}}.tsv.a{{color:var(--go)}}.tsv.r{{color:var(--r)}}
.tsl{{font-family:var(--dm);font-size:9px;text-transform:uppercase;color:var(--mu);margin-top:5px}}
.rtable{{width:100%;border-collapse:collapse;font-size:12px}}
.rtable th{{background:var(--s1);padding:9px 11px;text-align:left;color:var(--mu);font-weight:400;font-size:9px;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid var(--bd)}}
.rtable td{{padding:9px 11px;border-bottom:1px solid rgba(255,255,255,.025)}}
.tc{{text-align:center}}.pred{{color:var(--b)}}.act{{color:var(--g)}}.mono{{font-family:var(--dm)}}

footer{{text-align:center;color:var(--mu);font-family:var(--dm);font-size:9px;letter-spacing:1px;padding-top:24px;border-top:1px solid var(--bd);margin-top:60px;line-height:2.5}}

@media(max-width:640px){{
  .logo-mark{{font-size:38px}}
  .fhead{{padding:12px 12px 8px}}
  .fname{{font-size:13px}}
  .pgrid{{grid-template-columns:1fr 1fr}}
  .ccbody{{grid-template-columns:1fr}}
  .pvpgrid{{grid-template-columns:1fr 1fr}}
  .acca-wrap{{grid-template-columns:1fr}}
  .trstats{{grid-template-columns:1fr 1fr}}
  header{{flex-direction:column;align-items:flex-start}}
}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div>
    <div class="logo-mark">PL <em>INTEL</em></div>
    <span class="logo-sub">Neural Network Betting Intelligence</span>
  </div>
  <div class="hpills">
    <span class="pill"><span class="dot"></span>{generated_at}</span>
    <span class="pill"><b>{len(matches)}</b> fixtures</span>
    <span class="pill"><b>{len(bets)}</b> bet suggestions</span>
    <span class="pill"><b>52.5%</b> model acc</span>
  </div>
</header>

{live_bar}

<nav>
  <button class="tab on"  onclick="show('p1',this)">Predictions <span class="badge">{len(matches)}</span></button>
  <button class="tab" onclick="show('p2',this)">Value Finder <span class="badge">{len(vb_real)}</span></button>
  <button class="tab" onclick="show('p3',this)">Player Picks <span class="badge">{len(all_players)}</span></button>
  <button class="tab" onclick="show('p4',this)">Bet Suggestions <span class="badge hot">{n_high}H {n_med}M</span></button>
  <button class="tab" onclick="show('p5',this)">Corners &amp; Cards</button>
  <button class="tab" onclick="show('p6',this)">Player vs Defence</button>
  <button class="tab" onclick="show('p7',this)">Acca Builder</button>
  <button class="tab" onclick="show('p8',this)">Results Tracker</button>
</nav>

<div id="p1" class="pane on">{pred_html}</div>

<div id="p2" class="pane">
  <div class="disc"><strong>Value bets</strong> — model probability exceeds bookmaker implied probability by 5%+. Edges over 200% EV indicate bad data. Focus on 10–40% edges. Always gamble responsibly. 18+</div>
  {vb_html}
</div>

<div id="p3" class="pane">
  <div class="sec-title">Top Scorer Candidates</div>{sc_html}
  <div class="sec-title">Card Risks</div>{yw_html}
</div>

<div id="p4" class="pane">
  <div class="disc"><strong>Disclaimer:</strong> Model suggestions only. Not financial advice. 52.5% match accuracy. Gamble responsibly — 18+ only.</div>
  {bet_html}
</div>

<div id="p5" class="pane">{cc_html}</div>

<div id="p6" class="pane">
  <div class="disc"><strong>Player vs Defence</strong> — scorer probability weighted against the opponent's defensive record. Green = weak defence, good opportunity.</div>
  {pvp_html}
</div>

<div id="p7" class="pane">
  <div class="disc"><strong>Acca Builder</strong> — click outcomes to build an accumulator. Model confidence shown for each selection.</div>
  <div class="acca-wrap">
    <div class="acca-list" id="acca-list"></div>
    <div class="acca-panel">
      <div class="acca-title">YOUR ACCA</div>
      <div class="acca-sub">Select outcomes from the left</div>
      <div class="acca-legs" id="acca-legs"><div class="acca-empty">No selections yet</div></div>
      <div class="acca-result">
        <div class="acca-odds-big" id="acca-odds">—</div>
        <div class="acca-prob" id="acca-prob"></div>
        <div class="acca-stake">
          <label>Stake £</label>
          <input class="acca-input" type="number" id="acca-stake" value="10" min="1" oninput="updateAcca()">
        </div>
        <div class="acca-return" id="acca-return"></div>
        <div class="acca-conf" id="acca-conf"></div>
      </div>
      <div class="acca-clear" onclick="clearAcca()">Clear all</div>
    </div>
  </div>
</div>

<div id="p8" class="pane">{tracker_html}</div>

<footer>PL INTEL · NEURAL NETWORK · 9120 MATCHES TRAINED · NOT FINANCIAL ADVICE</footer>
</div>

<script>
const MATCHES = {acca_matches_js};
let accaSelections = {{}};

function show(id,btn){{
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  btn.classList.add('on');
  if(id==='p7') buildAccaList();
}}

function tog(uid){{
  var p=document.getElementById('i-'+uid), c=document.getElementById('c-'+uid);
  if(p.style.display==='none'){{p.style.display='block';c.classList.add('open');}}
  else{{p.style.display='none';c.classList.remove('open');}}
}}

function buildAccaList(){{
  const list = document.getElementById('acca-list');
  if(list.children.length>0) return;
  MATCHES.forEach((m,i)=>{{
    const parts = m.fixture.split(' vs ');
    const home = parts[0]||'', away = parts[1]||'';
    const row = document.createElement('div');
    row.className = 'acca-row';
    row.innerHTML = `<div class="acca-fix">${{m.fixture}} <span style="color:var(--mu);font-size:11px">${{m.date}}</span></div>
      <div class="acca-opts">
        <button class="acca-btn" onclick="selectAcca(${{i}},'home','${{home}} Win',${{m.hw}},${{m.iho}})" id="ab-${{i}}-home">${{home}} Win <span style="color:var(--mu)">${{(m.hw*100).toFixed(0)}}% / ${{m.iho}}</span></button>
        <button class="acca-btn" onclick="selectAcca(${{i}},'draw','Draw',${{m.dr}},${{m.idr}})" id="ab-${{i}}-draw">Draw <span style="color:var(--mu)">${{(m.dr*100).toFixed(0)}}% / ${{m.idr}}</span></button>
        <button class="acca-btn" onclick="selectAcca(${{i}},'away','${{away}} Win',${{m.aw}},${{m.iaw}})" id="ab-${{i}}-away">${{away}} Win <span style="color:var(--mu)">${{(m.aw*100).toFixed(0)}}% / ${{m.iaw}}</span></button>
      </div>`;
    list.appendChild(row);
  }});
}}

function selectAcca(idx, outcome, label, prob, odds){{
  const prev = accaSelections[idx];
  if(prev && prev.outcome===outcome){{
    delete accaSelections[idx];
    document.querySelectorAll(`[id^="ab-${{idx}}-"]`).forEach(b=>b.classList.remove('sel'));
  }} else {{
    accaSelections[idx] = {{outcome,label,prob,odds,fixture:MATCHES[idx].fixture}};
    document.querySelectorAll(`[id^="ab-${{idx}}-"]`).forEach(b=>b.classList.remove('sel'));
    document.getElementById(`ab-${{idx}}-${{outcome}}`).classList.add('sel');
  }}
  updateAcca();
}}

function updateAcca(){{
  const legs = document.getElementById('acca-legs');
  const oddsEl = document.getElementById('acca-odds');
  const probEl = document.getElementById('acca-prob');
  const retEl  = document.getElementById('acca-return');
  const confEl = document.getElementById('acca-conf');
  const stake  = parseFloat(document.getElementById('acca-stake').value)||10;
  const sels   = Object.values(accaSelections);
  if(sels.length===0){{
    legs.innerHTML='<div class="acca-empty">No selections yet</div>';
    oddsEl.textContent='—'; probEl.textContent=''; retEl.textContent=''; confEl.textContent='';
    return;
  }}
  legs.innerHTML = sels.map(s=>`<div class="acca-leg"><span>${{s.fixture}}</span><b>${{s.label}} @ ${{s.odds}}</b></div>`).join('');
  const combOdds = sels.reduce((acc,s)=>acc*s.odds,1);
  const combProb = sels.reduce((acc,s)=>acc*s.prob,1);
  const ret      = (stake * combOdds).toFixed(2);
  const profit   = (stake * combOdds - stake).toFixed(2);
  oddsEl.textContent = combOdds.toFixed(2);
  probEl.textContent = `Model probability: ${{(combProb*100).toFixed(1)}}%`;
  retEl.innerHTML    = `Returns <b>£${{ret}}</b> (profit £${{profit}}) on £${{stake}} stake`;
  const confPct = combProb*100;
  let confText, confCls;
  if(confPct>=20){{confText=`Strong acca — model backs this`;confCls='color:var(--g)';}}
  else if(confPct>=5){{confText=`Reasonable acca`;confCls='color:var(--go)';}}
  else{{confText=`Long shot — proceed with caution`;confCls='color:var(--r)';}}
  confEl.innerHTML = `<span style="${{confCls}}">${{confText}} (${{confPct.toFixed(1)}}% combined)</span>`;
}}

function clearAcca(){{
  accaSelections={{}};
  document.querySelectorAll('.acca-btn').forEach(b=>b.classList.remove('sel'));
  updateAcca();
}}
</script>
</body>
</html>"""

    outfile = "pl_intel.html"
    with open(outfile,"w",encoding="utf-8") as f:
        f.write(html)

    try:
        compile(html, 'test', 'exec')
    except: pass

    print(f"Saved to {outfile}")
    import webbrowser
    try: webbrowser.open(f"file://{os.path.abspath(outfile)}")
    except: pass
    input("\nPress Enter to close...")

if __name__=="__main__":
    main()
