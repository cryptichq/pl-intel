"""
Check available stats and fetch xG from FBref
Run: python check_xg.py
"""
import requests, json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
API_KEY = open("api_key.txt").read().strip()
FD_HEADERS = {"X-Auth-Token": API_KEY}

print("Checking football-data.org match stats...")
r = requests.get(
    "https://api.football-data.org/v4/competitions/PL/matches",
    headers=FD_HEADERS,
    params={"status": "FINISHED", "limit": 1},
    timeout=15
)
data = r.json()
matches = data.get("matches", [])
if matches:
    m = matches[0]
    print(f"Match: {m['homeTeam']['name']} vs {m['awayTeam']['name']}")
    print(f"Keys available: {list(m.keys())}")
    print(f"Score keys: {list(m.get('score',{}).keys())}")
    print(f"Odds: {m.get('odds')}")
    print(f"Stats: {m.get('statistics')}")
    print(f"Full match data:")
    print(json.dumps(m, indent=2)[:1000])
else:
    print("No matches returned")
    print(data)

print("\n\nChecking FBref for xG data...")
r2 = requests.get(
    "https://fbref.com/en/comps/9/shooting/Premier-League-Stats",
    headers=HEADERS, timeout=20
)
print(f"FBref status: {r2.status_code}")
if r2.status_code == 200:
    # Look for xG data
    if "xG" in r2.text or "npxG" in r2.text:
        print("FBref has xG data - can scrape!")
    else:
        print("No xG found in page")

input("\nPress Enter...")
