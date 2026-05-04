"""
Debug fixture name matching
Run: python debug_tracker.py
"""
import requests, json, glob, os
from datetime import datetime, timedelta

API_KEY  = open("api_key.txt").read().strip() if os.path.exists("api_key.txt") else ""
BASE_URL = "https://api.football-data.org/v4"
HEADERS  = {"X-Auth-Token": API_KEY}

# Fetch results
today     = datetime.now()
two_weeks = today - timedelta(days=14)
params    = {"dateFrom": two_weeks.strftime("%Y-%m-%d"), "dateTo": today.strftime("%Y-%m-%d"), "status": "FINISHED"}
resp      = requests.get(f"{BASE_URL}/competitions/PL/matches", headers=HEADERS, params=params, timeout=15)
results   = resp.json().get("matches", [])

print("API RESULTS:")
for r in results[:10]:
    h = r["homeTeam"]["name"]
    a = r["awayTeam"]["name"]
    ft = r.get("score",{}).get("fullTime",{})
    print(f"  '{h}' vs '{a}'  {ft.get('home')}-{ft.get('away')}")

# Load predictions
pred_files = glob.glob("predictions_*.json")
if pred_files:
    with open(max(pred_files, key=os.path.getmtime)) as f:
        preds = json.load(f)
    print("\nPREDICTION FIXTURES:")
    for p in preds[:10]:
        print(f"  '{p.get('fixture','')}'")

input("\nPress Enter...")
