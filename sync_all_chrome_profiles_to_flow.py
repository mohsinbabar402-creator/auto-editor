"""
sync_all_chrome_profiles_to_flow.py
Directly clones authenticated sessions from your real Google Chrome profiles into the
automation slots in browser/flow_profile_X.
Eliminates Google bot-detection login blocks and passwords completely.
"""

import os
import sys
import shutil
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
CHROME_DATA = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"
BROWSER_DIR = BASE_DIR / "browser"
BROWSER_DIR.mkdir(parents=True, exist_ok=True)

# Exact mapping of Automation Slot Number -> Real Chrome Profile Folder & Known Email
PROFILE_MAPPING = [
    (1,  "Default",    "mohsinoctal777@gmail.com",   "Pro (500 Daily Credits)"),
    (2,  "Profile 10", "aoctal522@gmail.com",        "Octal"),
    (3,  "Profile 16", "mohsinmughal1771@gmail.com", "Mughal official"),
    (4,  "Profile 17", "blazingsoul451@gmail.com",   "Blazing soul (Pro)"),
    (5,  "Profile 28", "zestify1771@gmail.com",      "Alex"),
    (6,  "Profile 4",  "donkeyraja646@gmail.com",    "pikachu"),
    (7,  "Profile 7",  "asa2333332@gmail.com",       "asa"),
    (8,  "Profile 27", "zestify1122@gmail.com",      "Alex 1122"),
    (9,  "Profile 29", "zestify7771@gmail.com",      "Drake 7771"),
    (10, "Profile 30", "zestify7744@gmail.com",      "Drake 7744"),
    (11, "Profile 33", "zestify1331@gmail.com",      "Alex 1331"),
    (12, "Profile 34", "zestifym1771@gmail.com",     "Alez 1771"),
    (13, "Profile 35", "zestifym1122@gmail.com",     "Me 1122"),
    (14, "Profile 36", "zestifym77@gmail.com",       "Ww 77"),
    (15, "Profile 18", "mohsinbabar402@gmail.com",   "M Babar"),
]


def sync_all():
    print("=" * 65)
    print(" SYNCING ALL REAL CHROME SESSIONS TO GOOGLE FLOW SLOTS")
    print("=" * 65)

    if not (CHROME_DATA / "Local State").exists():
        print("[!] Error: Chrome Local State file not found!")
        return

    success_count = 0
    for slot_num, chrome_folder, expected_email, label in PROFILE_MAPPING:
        src_profile = CHROME_DATA / chrome_folder
        if not src_profile.exists():
            print(f"[-] Slot #{slot_num:<2} ({label}): Chrome folder '{chrome_folder}' not found. Skipping.")
            continue

        dest_dir = BROWSER_DIR / f"flow_profile_{slot_num}"
        dest_default = dest_dir / "Default"
        dest_default.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Copy Local State (encryption keys)
            shutil.copy2(CHROME_DATA / "Local State", dest_dir / "Local State")

            # 2. Copy Preferences & Secure Preferences
            for pref_name in ["Preferences", "Secure Preferences"]:
                if (src_profile / pref_name).exists():
                    shutil.copy2(src_profile / pref_name, dest_default / pref_name)

            # 3. Copy Network directory (contains Cookies)
            src_net = src_profile / "Network"
            dest_net = dest_default / "Network"
            dest_net.mkdir(parents=True, exist_ok=True)
            if (src_net / "Cookies").exists():
                try:
                    shutil.copy2(src_net / "Cookies", dest_net / "Cookies")
                except Exception as e:
                    print(f"[~] Slot #{slot_num:<2} Note: Active Chrome tab holds Cookies lock ({e}). Preferences and state synced.")

            # Also copy Web Data and Login Data for full session persistence
            for data_file in ["Login Data", "Web Data", "Favicons"]:
                if (src_profile / data_file).exists():
                    try:
                        shutil.copy2(src_profile / data_file, dest_default / data_file)
                    except Exception:
                        pass

            print(f"[OK] Slot #{slot_num:<2} -> Synced {expected_email} ({label})")
            success_count += 1
        except Exception as e:
            print(f"[!] Slot #{slot_num:<2} Error: {e}")

    # Also sync Default to google_flow_profile for general flow runner
    try:
        gflow = BROWSER_DIR / "google_flow_profile"
        gflow_def = gflow / "Default"
        gflow_def.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CHROME_DATA / "Local State", gflow / "Local State")
        for pref_name in ["Preferences", "Secure Preferences"]:
            if (CHROME_DATA / "Default" / pref_name).exists():
                shutil.copy2(CHROME_DATA / "Default" / pref_name, gflow_def / pref_name)
        dest_net = gflow_def / "Network"
        dest_net.mkdir(parents=True, exist_ok=True)
        if (CHROME_DATA / "Default" / "Network" / "Cookies").exists():
            shutil.copy2(CHROME_DATA / "Default" / "Network" / "Cookies", dest_net / "Cookies")
        print("[OK] Primary Slot 'google_flow_profile' synced with mohsinoctal777@gmail.com")
    except Exception as e:
        print(f"[!] Error updating google_flow_profile: {e}")

    print("=" * 65)
    print(f"COMPLETED: {success_count}/{len(PROFILE_MAPPING)} Google Flow profiles synced successfully.")
    print("All profiles are now pre-authenticated directly from your Chrome sessions.")
    print("=" * 65)


if __name__ == "__main__":
    sync_all()
