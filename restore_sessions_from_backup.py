import logging
import os
from pathlib import Path
import shutil
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_DIR = Path(__file__).resolve().parent
BROWSER_DIR = PROJECT_DIR / "browser"
BACKUP_DIR = PROJECT_DIR / "browser_backups" / "latest"

PROFILES = [
    "flow_profile_1",
    "flow_profile_2",
    "flow_profile_3",
    "flow_profile_4",
]

def restore_sessions():
    print("=" * 65)
    print(" RESTORING SESSIONS FROM PERMANENT BACKUP")
    print("=" * 65)

    if not BACKUP_DIR.exists():
        print("[!] No backup directory found at:", BACKUP_DIR)
        return

    restored = 0
    for prof in PROFILES:
        src = BACKUP_DIR / prof
        if not src.exists():
            continue

        dest = BROWSER_DIR / prof
        dest.mkdir(parents=True, exist_ok=True)

        for root, dirs, files in os.walk(src):
            rel_path = Path(root).relative_to(src)
            target_dir = dest / rel_path
            target_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                try:
                    shutil.copy2(Path(root) / f, target_dir / f)
                except Exception:
                    pass

        print(f"  [✓] Restored {prof} from backup.")
        restored += 1

    print("=" * 65)
    print(f"COMPLETE: {restored} authenticated sessions restored to active browser directory.")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    restore_sessions()
