"""
Premier League Predictor — Enhanced
=====================================
Added features:
  - Elo ratings (rolling skill estimate per team)
  - Injury/availability data from FPL API
  - Home-specific and away-specific form
  - Goals scored vs conceded separately
  - Days rest between matches

Usage:
    python pl.py --build     Build enhanced features (run once after data pull)
    python pl.py --train     Train the model
    python pl.py --predict   Predict upcoming fixtures
    python pl.py --both      Train then predict
    python pl.py --all       Build + train + predict
"""

import sqlite3
import numpy as np
import pandas as pd
import joblib
import json
import argparse
import requests
from datetime import datetime
from pathlib import Path
from collections import defaultdict

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset
except ImportError:
    print("Run: pip install torch"); exit()

try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import classification_report, accuracy_score
except ImportError:
    print("Run: pip install scikit-learn"); exit()

DB_PATH   = "premier_league.db"
MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)
FPL_API   = "https://fantasy.premierleague.com/api/bootstrap-static/"

ELO_START    = 1500
ELO_K        = 32
ELO_HOME_ADV = 100

BASE_FEATURES = [
    "home_l5_wins","home_l5_draws","home_l5_losses",
    "away_l5_wins","away_l5_draws","away_l5_losses",
    "home_l5_scored","home_l5_conceded",
    "away_l5_scored","away_l5_conceded",
    "home_l5_scored_avg","home_l5_conceded_avg",
    "away_l5_scored_avg","away_l5_conceded_avg",
    "home_home_l5_wins","home_home_l5_scored","home_home_l5_conceded",
    "away_away_l5_wins","away_away_l5_scored","away_away_l5_conceded",
    "home_position","away_position",
    "home_points","away_points",
    "home_gd","away_gd",
    "position_diff","points_diff","gd_diff",
    "home_win_rate_l5","away_win_rate_l5",
    "h2h_home_wins","h2h_away_wins","h2h_draws",
    "home_elo","away_elo","elo_diff",
    "home_elo_form","away_elo_form",
    "home_injury_ratio","away_injury_ratio",
    "home_key_players_out","away_key_players_out",
    "home_days_rest","away_days_rest","rest_advantage",
    # xG features
    "home_xg_avg_l5","away_xg_avg_l5",
    "home_xga_avg_l5","away_xga_avg_l5",
    "home_xg_diff_l5","away_xg_diff_l5",
    # Referee
    "ref_yellows_pg","ref_reds_pg","ref_home_win_pct",
    # Weather
    "temperature_c","precipitation_mm","wind_speed_kmh",
    "is_wet","is_cold","is_windy",
    # Availability
    "home_players_out","away_players_out",
    "home_key_out","away_key_out",
]

RESULT_MAP   = {"HOME": 0, "DRAW": 1, "AWAY": 2}
RESULT_NAMES = ["Home Win", "Draw", "Away Win"]

FPL_TO_DB = {
    "Man City":"Man City","Man Utd":"Man United","Spurs":"Tottenham",
    "Nott'm Forest":"Nottingham Forest",
}


def compute_elo_ratings(conn):
    print("[ELO] Computing ratings...")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS elo_ratings (
            match_id INTEGER, team_id INTEGER,
            elo_before REAL, elo_after REAL, is_home INTEGER,
            PRIMARY KEY (match_id, team_id))""")
    conn.execute("DELETE FROM elo_ratings")
    matches = conn.execute("""
        SELECT id, home_team_id, away_team_id, winner, utc_date
        FROM matches WHERE status='FINISHED' ORDER BY utc_date, id
    """).fetchall()
    elo = defaultdict(lambda: ELO_START)
    for mid, htid, atid, winner, date in matches:
        he, ae = elo[htid], elo[atid]
        exp_h = 1 / (1 + 10**((ae - he - ELO_HOME_ADV)/400))
        act_h = 1.0 if winner=="HOME_TEAM" else 0.0 if winner=="AWAY_TEAM" else 0.5
        nh, na = he + ELO_K*(act_h - exp_h), ae + ELO_K*((1-act_h)-(1-exp_h))
        conn.execute("INSERT OR REPLACE INTO elo_ratings VALUES(?,?,?,?,1)", (mid,htid,he,nh))
        conn.execute("INSERT OR REPLACE INTO elo_ratings VALUES(?,?,?,?,0)", (mid,atid,ae,na))
        elo[htid], elo[atid] = nh, na
    conn.commit()
    print(f"[ELO] Done — {len(matches)} matches processed")
    teams = conn.execute("SELECT id, name FROM teams").fetchall()
    ratings = sorted([(name, elo[tid]) for tid, name in teams if tid in elo], key=lambda x:-x[1])
    print("[ELO] Top 10 teams by Elo:")
    for name, r in ratings[:10]:
        print(f"  {name:<25} {r:.0f}")
    return elo


def get_elo_before(conn, mid, tid):
    r = conn.execute("SELECT elo_before FROM elo_ratings WHERE match_id=? AND team_id=?",(mid,tid)).fetchone()
    return float(r[0]) if r else ELO_START

def get_elo_form(conn, tid, before_mid, n=5):
    rows = conn.execute("SELECT elo_before,elo_after FROM elo_ratings WHERE team_id=? AND match_id<? ORDER BY match_id DESC LIMIT ?",(tid,before_mid,n)).fetchall()
    return float(rows[0][1]-rows[-1][0]) if rows else 0.0

def get_current_elo(conn, tid):
    r = conn.execute("SELECT elo_after FROM elo_ratings WHERE team_id=? ORDER BY match_id DESC LIMIT 1",(tid,)).fetchone()
    return float(r[0]) if r else ELO_START

def get_home_away_form(conn, tid, venue, before_date, n=5):
    if venue=="home":
        rows = conn.execute("SELECT home_score_ft,away_score_ft,winner FROM matches WHERE home_team_id=? AND status='FINISHED' AND utc_date<? ORDER BY utc_date DESC LIMIT ?",(tid,before_date,n)).fetchall()
        wins = sum(1 for r in rows if r[2]=="HOME_TEAM")
        sc, cc = sum(r[0] or 0 for r in rows), sum(r[1] or 0 for r in rows)
    else:
        rows = conn.execute("SELECT away_score_ft,home_score_ft,winner FROM matches WHERE away_team_id=? AND status='FINISHED' AND utc_date<? ORDER BY utc_date DESC LIMIT ?",(tid,before_date,n)).fetchall()
        wins = sum(1 for r in rows if r[2]=="AWAY_TEAM")
        sc, cc = sum(r[0] or 0 for r in rows), sum(r[1] or 0 for r in rows)
    return wins, sc, cc

def get_rest_days(conn, tid, before_date):
    r = conn.execute("SELECT utc_date FROM matches WHERE (home_team_id=? OR away_team_id=?) AND status='FINISHED' AND utc_date<? ORDER BY utc_date DESC LIMIT 1",(tid,tid,before_date)).fetchone()
    if not r: return 7
    try:
        last = datetime.fromisoformat(r[0].replace("Z",""))
        curr = datetime.fromisoformat(before_date.replace("Z",""))
        return max((curr-last).days,1)
    except: return 7

def get_availability(conn, tid):
    r = conn.execute("SELECT injury_ratio,key_players_out FROM team_availability WHERE team_id=?",(tid,)).fetchone()
    return (float(r[0]),int(r[1])) if r else (0.0,0)

def fetch_injury_data(conn):
    print("[INJURY] Fetching FPL data...")
    conn.execute("""CREATE TABLE IF NOT EXISTS team_availability(
        team_id INTEGER PRIMARY KEY, injury_ratio REAL DEFAULT 0,
        key_players_out INTEGER DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("DELETE FROM team_availability")
    try:
        resp = requests.get(FPL_API,headers={"User-Agent":"Mozilla/5.0"},timeout=15)
        data = resp.json()
    except Exception as e:
        print(f"[INJURY] Failed: {e}"); return {}
    fpl_teams = {t["id"]:t["name"] for t in data.get("teams",[])}
    by_team = defaultdict(lambda:{"injured":0,"total":0,"key_out":0})
    for p in data.get("elements",[]):
        mins = int(p.get("minutes",0))
        if mins < 1200: continue
        ftn = fpl_teams.get(p.get("team"),"")
        dbn = FPL_TO_DB.get(ftn, ftn)
        status = p.get("status","a")
        is_key = mins >= 2000
        is_out = status in ("i","u","s")
        by_team[dbn]["total"] += 1
        if is_out:
            by_team[dbn]["injured"] += 1
            if is_key: by_team[dbn]["key_out"] += 1
    for tname, d in by_team.items():
        row = conn.execute("SELECT id FROM teams WHERE name=? OR name LIKE ? LIMIT 1",(tname,f"%{tname.split()[0]}%")).fetchone()
        if row:
            conn.execute("INSERT OR REPLACE INTO team_availability VALUES(?,?,?,CURRENT_TIMESTAMP)",(row[0],round(d["injured"]/max(d["total"],1),3),d["key_out"]))
    conn.commit()
    print(f"[INJURY] Saved data for {len(by_team)} teams")
    for t,d in sorted(by_team.items(), key=lambda x:-x[1]["key_out"]):
        if d["key_out"]>0: print(f"  {t:<25} {d['key_out']} key players out")

def build_enhanced_features(conn):
    print("\n[BUILD] Adding enhanced feature columns...")
    new_cols = [
        ("home_l5_scored","REAL DEFAULT 0"),("home_l5_conceded","REAL DEFAULT 0"),
        ("away_l5_scored","REAL DEFAULT 0"),("away_l5_conceded","REAL DEFAULT 0"),
        ("home_l5_scored_avg","REAL DEFAULT 0"),("home_l5_conceded_avg","REAL DEFAULT 0"),
        ("away_l5_scored_avg","REAL DEFAULT 0"),("away_l5_conceded_avg","REAL DEFAULT 0"),
        ("home_home_l5_wins","INTEGER DEFAULT 0"),("home_home_l5_scored","REAL DEFAULT 0"),("home_home_l5_conceded","REAL DEFAULT 0"),
        ("away_away_l5_wins","INTEGER DEFAULT 0"),("away_away_l5_scored","REAL DEFAULT 0"),("away_away_l5_conceded","REAL DEFAULT 0"),
        ("home_elo","REAL DEFAULT 1500"),("away_elo","REAL DEFAULT 1500"),("elo_diff","REAL DEFAULT 0"),
        ("home_elo_form","REAL DEFAULT 0"),("away_elo_form","REAL DEFAULT 0"),
        ("home_injury_ratio","REAL DEFAULT 0"),("away_injury_ratio","REAL DEFAULT 0"),
        ("home_key_players_out","INTEGER DEFAULT 0"),("away_key_players_out","INTEGER DEFAULT 0"),
        ("home_days_rest","INTEGER DEFAULT 7"),("away_days_rest","INTEGER DEFAULT 7"),("rest_advantage","INTEGER DEFAULT 0"),
    ]
    existing = [r[1] for r in conn.execute("PRAGMA table_info(match_features)").fetchall()]
    for col,ct in new_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE match_features ADD COLUMN {col} {ct}")
    conn.commit()

    matches = conn.execute("""
        SELECT id,matchday,utc_date,home_team_id,away_team_id,season_id
        FROM matches WHERE status='FINISHED' ORDER BY utc_date
    """).fetchall()
    print(f"[BUILD] Processing {len(matches)} matches...")

    for i,(mid,md,date,htid,atid,sid) in enumerate(matches):
        hf = conn.execute("SELECT last5_gf,last5_ga FROM team_form WHERE team_id=? AND season_id=? AND as_of_matchday<=? ORDER BY as_of_matchday DESC LIMIT 1",(htid,sid,md)).fetchone() or (0,0)
        af = conn.execute("SELECT last5_gf,last5_ga FROM team_form WHERE team_id=? AND season_id=? AND as_of_matchday<=? ORDER BY as_of_matchday DESC LIMIT 1",(atid,sid,md)).fetchone() or (0,0)
        hh = get_home_away_form(conn,htid,"home",date)
        aa = get_home_away_form(conn,atid,"away",date)
        he = get_elo_before(conn,mid,htid)
        ae = get_elo_before(conn,mid,atid)
        hef= get_elo_form(conn,htid,mid)
        aef= get_elo_form(conn,atid,mid)
        hav= get_availability(conn,htid)
        aav= get_availability(conn,atid)
        hr = get_rest_days(conn,htid,date)
        ar = get_rest_days(conn,atid,date)
        conn.execute("""UPDATE match_features SET
            home_l5_scored=?,home_l5_conceded=?,away_l5_scored=?,away_l5_conceded=?,
            home_l5_scored_avg=?,home_l5_conceded_avg=?,away_l5_scored_avg=?,away_l5_conceded_avg=?,
            home_home_l5_wins=?,home_home_l5_scored=?,home_home_l5_conceded=?,
            away_away_l5_wins=?,away_away_l5_scored=?,away_away_l5_conceded=?,
            home_elo=?,away_elo=?,elo_diff=?,home_elo_form=?,away_elo_form=?,
            home_injury_ratio=?,away_injury_ratio=?,home_key_players_out=?,away_key_players_out=?,
            home_days_rest=?,away_days_rest=?,rest_advantage=?
            WHERE match_id=?""",
            (float(hf[0]),float(hf[1]),float(af[0]),float(af[1]),
             float(hf[0])/5,float(hf[1])/5,float(af[0])/5,float(af[1])/5,
             hh[0],float(hh[1]),float(hh[2]),
             aa[0],float(aa[1]),float(aa[2]),
             he,ae,he-ae,hef,aef,
             hav[0],aav[0],hav[1],aav[1],
             hr,ar,hr-ar,mid))
        if i%500==0: conn.commit(); print(f"  {i}/{len(matches)}...")

    conn.commit()

    # Update upcoming fixtures
    upcoming = conn.execute("SELECT id,utc_date,home_team_id,away_team_id FROM matches WHERE status IN ('TIMED','SCHEDULED')").fetchall()
    for mid,date,htid,atid in upcoming:
        d = date or "2099-01-01"
        hh=get_home_away_form(conn,htid,"home",d)
        aa=get_home_away_form(conn,atid,"away",d)
        he=get_current_elo(conn,htid)
        ae=get_current_elo(conn,atid)
        hef=get_elo_form(conn,htid,mid)
        aef=get_elo_form(conn,atid,mid)
        hav=get_availability(conn,htid)
        aav=get_availability(conn,atid)
        hr=get_rest_days(conn,htid,d)
        ar=get_rest_days(conn,atid,d)
        conn.execute("""UPDATE match_features SET
            home_home_l5_wins=?,home_home_l5_scored=?,home_home_l5_conceded=?,
            away_away_l5_wins=?,away_away_l5_scored=?,away_away_l5_conceded=?,
            home_elo=?,away_elo=?,elo_diff=?,home_elo_form=?,away_elo_form=?,
            home_injury_ratio=?,away_injury_ratio=?,home_key_players_out=?,away_key_players_out=?,
            home_days_rest=?,away_days_rest=?,rest_advantage=?
            WHERE match_id=?""",
            (hh[0],float(hh[1]),float(hh[2]),aa[0],float(aa[1]),float(aa[2]),
             he,ae,he-ae,hef,aef,hav[0],aav[0],hav[1],aav[1],hr,ar,hr-ar,mid))
    conn.commit()
    print(f"[BUILD] Done. Updated {len(upcoming)} upcoming fixtures too.")


class PLPredictor(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim,64),nn.ReLU(),nn.Dropout(0.4),
            nn.Linear(64,32),nn.ReLU(),nn.Dropout(0.4),
        )
        self.result_head = nn.Linear(32,3)
        self.over25_head = nn.Sequential(nn.Linear(32,1),nn.Sigmoid())
        self.btts_head   = nn.Sequential(nn.Linear(32,1),nn.Sigmoid())

    def forward(self,x):
        e=self.encoder(x)
        return self.result_head(e),self.over25_head(e),self.btts_head(e)


def add_derived(df):
    df=df.copy()
    df["position_diff"]   = df.get("home_position",10)-df.get("away_position",10)
    df["points_diff"]     = df.get("home_points",0)-df.get("away_points",0)
    df["gd_diff"]         = df.get("home_gd",0)-df.get("away_gd",0)
    df["home_win_rate_l5"]= df.get("home_l5_wins",0)/5.0
    df["away_win_rate_l5"]= df.get("away_l5_wins",0)/5.0
    df["elo_diff"]        = df.get("home_elo",1500)-df.get("away_elo",1500)
    for col in BASE_FEATURES:
        if col not in df.columns: df[col]=0
    return df


def train():
    conn=sqlite3.connect(DB_PATH)
    df=pd.read_sql_query("""
        SELECT mf.*,ht.name AS home_team,at.name AS away_team
        FROM match_features mf
        JOIN teams ht ON ht.id=mf.home_team_id
        JOIN teams at ON at.id=mf.away_team_id
        LEFT JOIN fixture_enrichment fe ON fe.match_id = mf.match_id
        WHERE mf.result IS NOT NULL ORDER BY mf.utc_date
    """,conn)
    conn.close()
    df=add_derived(df)

    available=[c for c in BASE_FEATURES if c in df.columns and df[c].notna().any()]
    missing  =[c for c in BASE_FEATURES if c not in available]
    print(f"Loaded {len(df)} matches, {df['season_id'].nunique()} seasons")
    print(f"Using {len(available)}/{len(BASE_FEATURES)} features")
    if missing: print(f"Missing (run --build): {missing[:5]}{'...' if len(missing)>5 else ''}")

    X        =df[available].fillna(0).values.astype(np.float32)
    y_result =df["result"].map(RESULT_MAP).values.astype(np.int64)
    y_over25 =df["over_2_5"].values.astype(np.float32).reshape(-1,1)
    y_btts   =df["btts"].values.astype(np.float32).reshape(-1,1)

    n=len(X); te=int(n*0.70); ve=int(n*0.85)
    X_tr,X_val,X_te=X[:te],X[te:ve],X[ve:]
    yr_tr,yr_val,yr_te=y_result[:te],y_result[te:ve],y_result[ve:]
    yo_tr,yo_val=y_over25[:te],y_over25[te:ve]
    yb_tr,yb_val=y_btts[:te],y_btts[te:ve]

    sc=StandardScaler()
    X_tr=sc.fit_transform(X_tr); X_val=sc.transform(X_val); X_te=sc.transform(X_te)
    joblib.dump(sc,MODEL_DIR/"scaler.pkl")
    with open(MODEL_DIR/"feature_cols.json","w") as f: json.dump(available,f)

    loader=DataLoader(TensorDataset(*[torch.tensor(a) for a in [X_tr,yr_tr,yo_tr,yb_tr]]),batch_size=16,shuffle=True)
    model=PLPredictor(len(available))
    total=4195+2254+2671
    weights=torch.tensor([total/4195,total/2254,total/2671],dtype=torch.float32)
    cel=nn.CrossEntropyLoss(weight=weights); bce=nn.BCELoss()
    opt=optim.Adam(model.parameters(),lr=3e-4,weight_decay=1e-2)
    sch=optim.lr_scheduler.ReduceLROnPlateau(opt,patience=15,factor=0.5)

    best=0.0; no_imp=0
    print(f"\nTraining {len(X_tr)} / val {len(X_val)} / test {len(X_te)}\n")

    for ep in range(1,301):
        model.train(); tl=0
        for xb,yr,yo,yb in loader:
            opt.zero_grad()
            rl,op,bp=model(xb)
            loss=cel(rl,yr)+0.5*bce(op,yo)+0.5*bce(bp,yb)
            loss.backward(); opt.step(); tl+=loss.item()
        model.eval()
        with torch.no_grad():
            rl,_,_=model(torch.tensor(X_val.astype(np.float32)))
            va=accuracy_score(yr_val,rl.argmax(1).numpy())
        sch.step(1-va)
        if va>best: best=va; no_imp=0; torch.save(model.state_dict(),MODEL_DIR/"best_model.pt")
        else: no_imp+=1
        if ep%20==0: print(f"  Epoch {ep:3d} | Loss:{tl/len(loader):.4f} | Val:{va:.3f} | Best:{best:.3f}")
        if no_imp>=40: print(f"\n  Early stopping at epoch {ep}"); break

    model.load_state_dict(torch.load(MODEL_DIR/"best_model.pt",map_location="cpu"))
    model.eval()
    with torch.no_grad():
        rl,_,_=model(torch.tensor(X_te.astype(np.float32)))
        preds=rl.argmax(1).numpy()
    print(f"\n{'='*55}\nFINAL RESULTS (best val acc: {best:.3f})\n{'='*55}")
    print(classification_report(yr_te,preds,target_names=RESULT_NAMES))
    qual="EXCELLENT" if best>=0.52 else "GOOD" if best>=0.48 else "OK — get more data"
    print(f"Model quality: {qual}")


def predict():
    mp=MODEL_DIR/"best_model.pt"; sp=MODEL_DIR/"scaler.pkl"; fp=MODEL_DIR/"feature_cols.json"
    if not mp.exists(): print("No model. Run: python pl.py --train"); return
    fc=json.load(open(fp)) if fp.exists() else BASE_FEATURES

    conn=sqlite3.connect(DB_PATH)
    df=pd.read_sql_query("""
        SELECT mf.*,ht.name AS home_team,at.name AS away_team
        FROM match_features mf
        JOIN teams ht ON ht.id=mf.home_team_id
        JOIN teams at ON at.id=mf.away_team_id
        LEFT JOIN fixture_enrichment fe ON fe.match_id = mf.match_id
        WHERE mf.result IS NULL ORDER BY mf.utc_date
    """,conn)
    conn.close()
    if df.empty: print("No fixtures. Run: python live_fixtures.py"); return

    df=add_derived(df)
    for c in fc:
        if c not in df.columns: df[c]=0

    X=df[fc].fillna(0).values.astype(np.float32)
    sc=joblib.load(sp); Xs=sc.transform(X)
    model=PLPredictor(len(fc))
    model.load_state_dict(torch.load(mp,map_location="cpu"))
    model.eval()

    with torch.no_grad():
        rl,op,bp=model(torch.tensor(Xs))

    T=2.5; lg=rl.numpy()/T
    ex=np.exp(lg-lg.max(1,keepdims=True)); probs=ex/ex.sum(1,keepdims=True)
    op=op.squeeze().numpy(); bp=bp.squeeze().numpy()
    if op.ndim==0: op=np.array([float(op)]); bp=np.array([float(bp)])

    print("\n"+"="*85)
    print("PREMIER LEAGUE PREDICTIONS — ENHANCED MODEL")
    print("="*85)
    print(f"{'Fixture':<34} {'H Win':>6} {'Draw':>6} {'A Win':>6} {'O2.5':>6} {'BTTS':>6} {'Elo H':>6} {'Elo A':>6}")
    print("-"*85)

    results=[]
    for i in range(len(df)):
        row=df.iloc[i]
        hw,dr,aw=float(probs[i][0]),float(probs[i][1]),float(probs[i][2])
        o25,bt=float(op[i]),float(bp[i])
        he=float(df.iloc[i].get("home_elo",1500)); ae=float(df.iloc[i].get("away_elo",1500))
        fix=f"{row['home_team']} vs {row['away_team']}"[:33]
        inj_h=float(df.iloc[i].get("home_key_players_out",0))
        inj_a=float(df.iloc[i].get("away_key_players_out",0))
        inj_note=""
        if inj_h>0: inj_note+=f" ⚠ {row['home_team'].split()[0]} {int(inj_h)} out"
        if inj_a>0: inj_note+=f" ⚠ {row['away_team'].split()[0]} {int(inj_a)} out"
        print(f"{fix:<34} {hw:>5.1%} {dr:>5.1%} {aw:>5.1%} {o25:>5.1%} {bt:>5.1%} {he:>6.0f} {ae:>6.0f}{inj_note}")
        results.append({
            "date":str(row["utc_date"])[:10],"fixture":fix,
            "home_win_prob":round(hw,4),"draw_prob":round(dr,4),"away_win_prob":round(aw,4),
            "implied_home_odds":round(1/hw,2) if hw>0.01 else 99.0,
            "implied_draw_odds":round(1/dr,2) if dr>0.01 else 99.0,
            "implied_away_odds":round(1/aw,2) if aw>0.01 else 99.0,
            "over_2_5_prob":round(o25,4),"btts_prob":round(bt,4),
            "home_elo":round(he),"away_elo":round(ae),
            "home_key_out":int(inj_h),"away_key_out":int(inj_a),
        })
    print("="*85)
    out=f"predictions_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out,"w") as f: json.dump(results,f,indent=2)
    print(f"\nSaved {len(results)} predictions to {out}")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--build",  action="store_true")
    parser.add_argument("--train",  action="store_true")
    parser.add_argument("--predict",action="store_true")
    parser.add_argument("--both",   action="store_true")
    parser.add_argument("--all",    action="store_true")
    args=parser.parse_args()

    conn=sqlite3.connect(DB_PATH)
    if args.build or args.all:
        print("Step 1: Elo ratings...")
        compute_elo_ratings(conn)
        print("\nStep 2: Injury data...")
        fetch_injury_data(conn)
        print("\nStep 3: Enhanced features...")
        build_enhanced_features(conn)
        print("\nDone! Now run: python pl.py --train")
    conn.close()

    if args.train or args.both or args.all: train()
    if args.predict or args.both or args.all: predict()
    if not any([args.build,args.train,args.predict,args.both,args.all]):
        print("Usage:")
        print("  python pl.py --build     Build Elo + injury + enhanced features")
        print("  python pl.py --train     Train the model")
        print("  python pl.py --predict   Predict upcoming fixtures")
        print("  python pl.py --both      Train then predict")
        print("  python pl.py --all       Build + train + predict (recommended)")
