import argparse
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

# Windows UTF-8 console output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add whop-editor to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.profile_registry import ProfileRegistry, ProfileAuthStatus
from workers.worker_registry import WorkerRegistry, DEFAULT_WORKER_PROFILES
from workers.resource_governor import get_resource_governor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("login_wizard")

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
BROWSER_DIR = PROJECT_DIR / "browser"
BACKUP_DIR = PROJECT_DIR / "browser_backups"


def find_chrome_executable() -> Optional[str]:
    """Locates the installed Google Chrome binary on Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def clean_singleton_locks(profile_dir: Path):
    """Removes stale Playwright/Chrome singleton locks to prevent launch hangs."""
    for lock_name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_file = profile_dir / lock_name
        if lock_file.exists():
            try:
                lock_file.unlink()
            except Exception:
                pass


def backup_single_profile(profile_id: str):
    """Backs up essential session cookies and preferences for a single profile."""
    src = BROWSER_DIR / profile_id
    if not src.exists():
        return

    dest = BACKUP_DIR / "latest" / profile_id
    dest.mkdir(parents=True, exist_ok=True)

    # Copy Local State
    if (src / "Local State").exists():
        try:
            shutil.copy2(src / "Local State", dest / "Local State")
        except Exception:
            pass

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

        net_src = sub_dir / "Network" / "Cookies"
        if net_src.exists():
            net_dest = (dest / "Default" if sub_dir.name == "Default" else dest) / "Network"
            net_dest.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(net_src, net_dest / "Cookies")
            except Exception:
                pass

    print(f"  [✓] Backed up session files to: {dest}")


def print_status_table(registry: ProfileRegistry) -> List[Any]:
    profiles = registry.get_all_profiles()
    profiles.sort(key=lambda p: p.profile_id)

    print("\n" + "=" * 80)
    print("      AUTONOMOUS CONTENT ENGINE — 8-WORKER PROFILE AUTHENTICATION STATUS")
    print("=" * 80)
    print(f"{'#':<3} | {'Profile ID':<15} | {'Worker Role':<24} | {'Auth Status':<15} | {'Account Email':<22}")
    print("-" * 80)

    auth_count = 0
    for idx, p in enumerate(profiles, start=1):
        if p.auth_status == ProfileAuthStatus.AUTHENTICATED:
            auth_count += 1
            badge = "🟢 [AUTHENTICATED]"
        else:
            badge = "⚪ [AUTH REQUIRED] "

        role_display = p.worker_role.replace("_", " ").title()
        email_display = p.account_email or "--- (Not Logged In)"
        print(f"[{idx}] | {p.profile_id:<15} | {role_display:<24} | {badge:<15} | {email_display:<22}")

    print("=" * 80)
    print(f"Ready: {auth_count}/{len(profiles)} workers authenticated for autonomous operation.")
    print("=" * 80 + "\n")
    return profiles


def launch_profile_for_login(profile_num: int, registry: ProfileRegistry, worker_registry: WorkerRegistry):
    profile_id = f"flow_profile_{profile_num}"
    p = registry.get_profile(profile_id)
    if not p:
        print(f"Error: Profile {profile_id} not found in registry.")
        return

    profile_dir = Path(p.user_data_dir).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    clean_singleton_locks(profile_dir)

    chrome_exe = find_chrome_executable()
    if not chrome_exe:
        print("ERROR: Google Chrome executable not found on this machine.")
        return

    urls = [
        "https://labs.google/fx/tools/flow",
        "https://gemini.google.com",
    ]

    cmd = [
        chrome_exe,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
    ] + urls

    print("\n" + "#" * 70)
    print(f"  LAUNCHING ISOLATED CHROME WINDOW FOR: {profile_id}")
    print(f"  Worker Role:  {p.worker_role.replace('_', ' ').title()}")
    print(f"  Directory:    {profile_dir}")
    print("#" * 70)
    print("  INSTRUCTIONS:")
    print("  1. In the Chrome window that just opened, log into your Google Account.")
    print("  2. Complete 2FA / Phone verification if prompted.")
    print("  3. Verify that Google Flow and Gemini dashboards load successfully.")
    print("  4. NOTE: NEVER type passwords into this console. Everything is done in Chrome.")
    print("#" * 70 + "\n")

    proc = subprocess.Popen(cmd)

    input("Press [ENTER] when you have completed login in Chrome...")

    # Optional email entry
    current_email = p.account_email or ""
    prompt_str = f"Enter the account email for {profile_id} [{current_email}]: " if current_email else f"Enter the account email for {profile_id}: "
    new_email = input(prompt_str).strip()
    final_email = new_email if new_email else current_email

    # Mark authenticated in registry and PostgreSQL
    worker_registry.mark_profile_authenticated(profile_id, email=final_email if final_email else None)
    backup_single_profile(profile_id)

    print(f"\n[SUCCESS] {profile_id} marked AUTHENTICATED and synchronized to PostgreSQL!\n")


def run_wizard():
    parser = argparse.ArgumentParser(description="Manual Login Wizard for 8-Worker Autonomous System")
    parser.add_argument("--list-only", action="store_true", help="Print worker status table and exit")
    parser.add_argument("--sync-only", action="store_true", help="Sync all profiles to PostgreSQL and exit")
    parser.add_argument("--profile", type=int, choices=range(1, 9), help="Directly launch profile 1-8")
    args = parser.parse_args()

    registry = ProfileRegistry()
    worker_reg = WorkerRegistry(profile_registry=registry)

    if args.list_only:
        print_status_table(registry)
        return

    if args.sync_only:
        worker_reg.sync_all_workers_to_db()
        print("Synchronized all profiles to PostgreSQL workers table.")
        return

    if args.profile:
        launch_profile_for_login(args.profile, registry, worker_reg)
        return

    # Interactive Loop
    while True:
        profiles = print_status_table(registry)
        print("OPTIONS:")
        print("  [1-8] Launch Chrome for Worker Profile 1 to 8")
        print("  [A]   Auto-step through next unauthenticated profile")
        print("  [B]   Backup all authenticated profile sessions")
        print("  [S]   Sync all profiles to PostgreSQL")
        print("  [Q]   Exit Wizard")

        choice = input("\nEnter choice: ").strip().upper()
        if choice == "Q":
            print("Exiting Login Wizard. System is ready for autonomous production.")
            break
        elif choice == "S":
            worker_reg.sync_all_workers_to_db()
            print("PostgreSQL workers table synchronized successfully.")
        elif choice == "B":
            from backup_all_sessions import backup_sessions
            backup_sessions()
        elif choice == "A":
            unauth = [p for p in profiles if p.auth_status != ProfileAuthStatus.AUTHENTICATED]
            if not unauth:
                print("\nAll 8 profiles are already authenticated! Nothing to do.\n")
            else:
                next_p = unauth[0]
                num = int(next_p.profile_id.replace("flow_profile_", ""))
                launch_profile_for_login(num, registry, worker_reg)
        elif choice in [str(i) for i in range(1, 9)]:
            launch_profile_for_login(int(choice), registry, worker_reg)
        else:
            print("Invalid selection. Please choose an option from the menu.")


if __name__ == "__main__":
    run_wizard()
