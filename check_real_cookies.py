import sqlite3
import shutil
from pathlib import Path

base_dir = Path("browser")
print("=== CHECKING ACTUAL GOOGLE FLOW COOKIES IN SQLITE ===")

really_logged_in = []
for i in range(1, 16):
    p_dir = base_dir / f"flow_profile_{i}"
    cookie_db = p_dir / "Default" / "Network" / "Cookies"
    if not cookie_db.exists():
        cookie_db = p_dir / "Default" / "Cookies"
        
    has_flow = False
    if cookie_db.exists():
        tmp = Path(f"temp_ck_{i}.db")
        try:
            shutil.copy2(cookie_db, tmp)
            conn = sqlite3.connect(tmp)
            c = conn.cursor()
            c.execute("SELECT name, host_key FROM cookies WHERE host_key LIKE '%labs.google%'")
            rows = c.fetchall()
            if len(rows) > 0:
                has_flow = True
                print(f"Profile {i:>2}: [REAL FLOW LOGIN] -> {len(rows)} labs.google cookies")
            conn.close()
        except Exception as e:
            pass
        finally:
            if tmp.exists():
                tmp.unlink()
            
    if has_flow:
        really_logged_in.append(i)

print("\nPROFILES THAT ACTUALLY LOGGED INTO GOOGLE FLOW:", really_logged_in)
