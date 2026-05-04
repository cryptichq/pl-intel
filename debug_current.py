"""
Find current season matches
Run: python debug_current.py
"""
import sqlite3
DB_PATH = "premier_league.db"
conn = sqlite3.connect(DB_PATH)

print("Most recent finished matches:")
rows = conn.execute("""
    SELECT id, utc_date, season_id, home_team_id, away_team_id
    FROM matches WHERE status='FINISHED'
    ORDER BY utc_date DESC LIMIT 10
""").fetchall()
for r in rows:
    home = conn.execute("SELECT name FROM teams WHERE id=?", (r[3],)).fetchone()
    away = conn.execute("SELECT name FROM teams WHERE id=?", (r[4],)).fetchone()
    print(f"  season_id={r[2]}  {r[1][:10]}  {home[0] if home else '?'} vs {away[0] if away else '?'}")

print("\nDistinct season_ids in matches table:")
rows = conn.execute("""
    SELECT season_id, COUNT(*), MIN(utc_date), MAX(utc_date)
    FROM matches GROUP BY season_id ORDER BY MAX(utc_date) DESC LIMIT 10
""").fetchall()
for r in rows:
    print(f"  season_id={r[0]}  count={r[1]}  {str(r[2])[:10]} to {str(r[3])[:10]}")

print("\nUpcoming fixtures season_ids:")
rows = conn.execute("""
    SELECT DISTINCT season_id, COUNT(*) FROM matches
    WHERE status IN ('TIMED','SCHEDULED') GROUP BY season_id
""").fetchall()
for r in rows:
    print(f"  season_id={r[0]}  count={r[1]}")

conn.close()
input("\nPress Enter...")
