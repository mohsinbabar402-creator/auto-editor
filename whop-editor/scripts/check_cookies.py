import sqlite3
from pathlib import Path

print("Checking profile cookie databases...")
for p in sorted(Path("browser").glob("*")):
    if not p.is_dir():
        continue
    cookie_db = p / "Default" / "Network" / "Cookies"
    if not cookie_db.exists():
        cookie_db = p / "Network" / "Cookies"
    if cookie_db.exists():
        try:
            conn = sqlite3.connect(f"file:{cookie_db.resolve()}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM cookies WHERE host_key LIKE '%google.com%';")
            g_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM cookies WHERE host_key LIKE '%gemini%';")
            gemini_count = cur.fetchone()[0]
            print(f"[{p.name}] google.com cookies: {g_count}, gemini cookies: {gemini_count}")
            conn.close()
        except Exception as e:
            print(f"[{p.name}] error: {e}")
