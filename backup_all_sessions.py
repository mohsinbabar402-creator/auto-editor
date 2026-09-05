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
BACKUP_DIR = PROJECT_DIR / "browser_backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

PROFILES = [
    "flow_profile_1",
    "flow_profile_2",
    "flow_profile_3",
    "flow_profile_4",
]

IMPORTANT_FILES = [
    "Local State",
    "Preferences",
    "Secure Preferences",
    "Login Data",
    "Web Data",
    "Network/Cookies",
]

def backup_sessions():
    print("=" * 65)
    print(" PERMANENTLY BACKING UP AUTHENTICATED BROWSER SESSIONS")
    print("=" * 65)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    current_backup = BACKUP_DIR / "latest"
    current_backup.mkdir(parents=True, exist_ok=True)

    backed_up = 0
    for prof in PROFILES:
        src = BROWSER_DIR / prof
        if not src.exists():
            continue

        dest = current_backup / prof
        dest.mkdir(parents=True, exist_ok=True)

        # Copy Local State
        if (src / "Local State").exists():
            shutil.copy2(src / "Local State", dest / "Local State")

        # Copy Default subfolder items
        for sub_dir in [src, src / "Default"]:
            if not sub_dir.exists():
                continue
            for item in ["Preferences", "Secure Preferences", "Login Data", "Web Data"]:
                if (sub_dir / item).exists():
                    dest_sub = dest / "Default" if sub_dir.name == "Default" else dest
                    dest_sub.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(sub_dir / item, dest_sub / item)
                    except Exception:
                        pass

            # Network/Cookies
            net_src = sub_dir / "Network" / "Cookies"
            if net_src.exists():
                net_dest = (dest / "Default" if sub_dir.name == "Default" else dest) / "Network"
                net_dest.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(net_src, net_dest / "Cookies")
                except Exception:
                    pass

        print(f"  [✓] Backed up {prof} -> {dest}")
        backed_up += 1

    print("=" * 65)
    print(f"COMPLETE: {backed_up} authenticated browser sessions permanently secured in:")
    print(f"{current_backup}")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    backup_sessions()
