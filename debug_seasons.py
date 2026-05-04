"""
Debug seasons table
Run: python debug_seasons.py
"""
import sqlite3
DB_PATH = "premier_league.db"
conn = sqlite3.connect(DB_PATH)

print("Seasons table:")
rows = conn.execute("SELECT id, start_date, end_date, current_matchday FROM seasons ORDER BY id DESC LIMIT 5").fetchall()
for r in rows:
    print(f"  ID {r[0]}: {r[1]} to {r[2]}  matchday {r[3]}")

print("\nMax season ID:", conn.execute("SELECT MAX(id) FROM seasons").fetchone()[0])

print("\nMatches in max season:")
max_sid = conn.execute("SELECT MAX(id) FROM seasons").fetchone()[0]
r = conn.execute("""
    SELECT COUNT(*), MIN(utc_date), MAX(utc_date)
    FROM matches WHERE season_id=? AND status='FINISHED'
""", (max_sid,)).fetchone()
print(f"  {r[0]} finished matches, {r[1]} to {r[2]}")

print("\nTeams with matches in current season:")
teams = conn.execute("""
    SELECT DISTINCT t.name FROM matches m
    JOIN teams t ON t.id = m.home_team_id
    WHERE m.season_id=? AND m.status='FINISHED'
    ORDER BY t.name
""", (max_sid,)).fetchall()
for t in teams:
    print(f"  {t[0]}")

conn.close()
input("\nPress Enter...")
