"""
Logo Fetcher
=============
Downloads team logos from football-data.org using your API key.
Saves them to a logos/ folder so they can be hosted on GitHub Pages.

Run once: python logos.py
Then commit the logos/ folder to GitHub.
"""

import requests
import os
import json
import time

API_KEY  = open("api_key.txt").read().strip() if os.path.exists("api_key.txt") else ""
BASE_URL = "https://api.football-data.org/v4"
HEADERS  = {"X-Auth-Token": API_KEY}

LOGO_DIR = "logos"
os.makedirs(LOGO_DIR, exist_ok=True)

# Name mapping from API to our DB names
NAME_MAP = {
    "Arsenal FC":                   "Arsenal",
    "Aston Villa FC":               "Aston Villa",
    "AFC Bournemouth":              "Bournemouth",
    "Brentford FC":                 "Brentford",
    "Brighton & Hove Albion FC":    "Brighton",
    "Burnley FC":                   "Burnley",
    "Chelsea FC":                   "Chelsea",
    "Crystal Palace FC":            "Crystal Palace",
    "Everton FC":                   "Everton",
    "Fulham FC":                    "Fulham",
    "Leeds United FC":              "Leeds",
    "Liverpool FC":                 "Liverpool",
    "Manchester City FC":           "Man City",
    "Manchester United FC":         "Man United",
    "Newcastle United FC":          "Newcastle",
    "Nottingham Forest FC":         "Nottingham Forest",
    "Sunderland AFC":               "Sunderland",
    "Tottenham Hotspur FC":         "Tottenham",
    "West Ham United FC":           "West Ham",
    "Wolverhampton Wanderers FC":   "Wolves",
}


def fetch_team_crests():
    """Fetch all PL team crests from football-data.org."""
    print("Fetching team data from football-data.org...")
    r = requests.get(
        f"{BASE_URL}/competitions/PL/teams",
        headers=HEADERS,
        params={"season": 2025},
        timeout=15
    )

    if r.status_code != 200:
        print(f"API error: {r.status_code}")
        print("Trying season 2024...")
        r = requests.get(
            f"{BASE_URL}/competitions/PL/teams",
            headers=HEADERS,
            params={"season": 2024},
            timeout=15
        )

    if r.status_code != 200:
        print(f"Failed: {r.status_code} — {r.text[:200]}")
        return {}

    teams = r.json().get("teams", [])
    print(f"Got {len(teams)} teams")

    crest_map = {}
    for t in teams:
        name     = t.get("name","")
        db_name  = NAME_MAP.get(name, name)
        crest    = t.get("crest","")
        team_id  = t.get("id","")
        crest_map[db_name] = {
            "crest_url": crest,
            "api_id":    team_id,
            "api_name":  name,
        }

    return crest_map


def download_crest(team_name, crest_url):
    """Download a single crest image."""
    if not crest_url:
        return None

    # Determine file extension
    ext = "svg" if crest_url.endswith(".svg") else "png"
    safe = team_name.lower().replace(' ','_').replace("'",'').replace('.','')
    filename = f"{safe}.{ext}"
    filepath = os.path.join(LOGO_DIR, filename)

    if os.path.exists(filepath):
        print(f"  Already exists: {filename}")
        return filename

    try:
        r = requests.get(
            crest_url,
            headers={"X-Auth-Token": API_KEY},
            timeout=10
        )
        if r.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(r.content)
            print(f"  ✅ {team_name}: {filename} ({len(r.content)} bytes)")
            return filename
        else:
            print(f"  ❌ {team_name}: HTTP {r.status_code}")
            return None
    except Exception as e:
        print(f"  ❌ {team_name}: {e}")
        return None


def build_logo_map(crest_map):
    """Download all crests and build a JS-ready logo map."""
    print("\nDownloading team crests...")
    logo_map = {}

    for db_name, info in crest_map.items():
        filename = download_crest(db_name, info["crest_url"])
        if filename:
            logo_map[db_name] = f"logos/{filename}"
        time.sleep(0.3)

    # Save logo map
    with open("logo_map.json", "w") as f:
        json.dump(logo_map, f, indent=2)

    print(f"\nSaved logo map for {len(logo_map)} teams to logo_map.json")
    return logo_map


def main():
    print("="*55)
    print("LOGO FETCHER")
    print("="*55)

    crest_map = fetch_team_crests()
    if not crest_map:
        print("\nCould not fetch team data. Check your API key in api_key.txt")
        input("Press Enter..."); return

    logo_map = build_logo_map(crest_map)

    print("\nLogos saved to logos/ folder")
    print("\nNext steps:")
    print("  python site.py   (will now include logos)")
    print("  git add logos/")
    print("  git add index.html logo_map.json")
    print("  git commit -m 'Add team logos'")
    print("  git push origin master")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
