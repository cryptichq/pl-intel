"""
PL Intel Sync
==============
Downloads the latest versions of all scripts from GitHub.
Run this whenever you want to update your scripts.

Run: python sync.py
"""

import urllib.request
import json
import os
import sys

# GitHub raw content base URL for your repo
# Scripts are stored in a separate branch called 'scripts'
GITHUB_USER = "cryptichq"
GITHUB_REPO = "pl-intel"
BRANCH      = "scripts"
BASE_URL    = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{BRANCH}"

# All scripts to sync
SCRIPTS = [
    "pl.py",
    "playerstats.py",
    "live_fixtures.py",
    "enrich.py",
    "site.py",
    "valuefinder.py",
    "tracker.py",
    "injuries.py",
    "livescores.py",
    "xg.py",
    "extradata.py",
    "matchpages.py",
    "logos.py",
    "update.bat",
]

def check_version():
    """Check if there's a newer version available."""
    try:
        url = f"{BASE_URL}/version.json"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return data.get("version","?"), data.get("notes","")
    except:
        return None, ""

def download_script(filename):
    """Download a single script from GitHub."""
    url = f"{BASE_URL}/{filename}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            content = r.read()
        with open(filename, "wb") as f:
            f.write(content)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # File doesn't exist yet
        print(f"  HTTP {e.code}: {filename}")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

def main():
    print("="*55)
    print("PL INTEL SYNC")
    print("="*55)

    # Check version
    version, notes = check_version()
    if version:
        print(f"\nLatest version: {version}")
        if notes:
            print(f"What's new: {notes}")
    else:
        print("\nCould not check version — updating anyway...")

    print(f"\nDownloading {len(SCRIPTS)} scripts from GitHub...")
    print(f"Source: github.com/{GITHUB_USER}/{GITHUB_REPO}/tree/{BRANCH}\n")

    updated = 0
    skipped = 0
    failed  = 0

    for script in SCRIPTS:
        print(f"  {script:<30}", end=" ", flush=True)
        result = download_script(script)
        if result is True:
            print("✅ Updated")
            updated += 1
        elif result is None:
            print("⏭ Not available yet")
            skipped += 1
        else:
            print("❌ Failed")
            failed += 1

    print(f"\n{'='*55}")
    print(f"Updated: {updated}  Skipped: {skipped}  Failed: {failed}")

    if failed > 0:
        print("\nSome scripts failed to download.")
        print("Check your internet connection and try again.")
    elif updated > 0:
        print("\nAll scripts updated successfully!")
        print("Run update.bat to generate fresh predictions.")
    else:
        print("\nNo updates available — you're already up to date!")

    print("="*55)
    input("\nPress Enter to close...")

if __name__ == "__main__":
    main()
