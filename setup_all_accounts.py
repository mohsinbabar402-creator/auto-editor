import json
import logging
import os
from pathlib import Path
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
BROWSER_DIR = BASE_DIR / "browser"
REGISTRY_FILE = BROWSER_DIR / "profile_registry.json"
MC_FILE = BASE_DIR / "mission_control.json"
VERIFIED_FILE = BASE_DIR / "verified_sessions.json"

ACCOUNTS = [
    {"id": 1, "profile": "flow_profile_1", "email": "mohsinoctal777@gmail.com", "label": "Primary Chrome (Pro)"},
    {"id": 2, "profile": "flow_profile_2", "email": "aoctal522@gmail.com", "label": "Octal (Currently Authenticated)"},
    {"id": 3, "profile": "flow_profile_3", "email": "mohsinmughal1771@gmail.com", "label": "Mughal official"},
    {"id": 4, "profile": "flow_profile_4", "email": "blazingsoul451@gmail.com", "label": "Blazing soul (Pro)"},
    {"id": 5, "profile": "flow_profile_5", "email": "zestify1771@gmail.com", "label": "Alex / Zestify (Pro)"},
]


def clean_profile_locks(profile_dir: Path):
    for lock_name in ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"]:
        lock_path = profile_dir / lock_name
        if lock_path.exists():
            try:
                lock_path.unlink()
            except Exception:
                pass


def load_registry() -> list:
    if REGISTRY_FILE.exists():
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_registry_profile(profile_id: str, email: str, auth_status: str = "AUTHENTICATED"):
    items = load_registry()
    found = False
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for item in items:
        if item.get("profile_id") == profile_id:
            item["auth_status"] = auth_status
            item["account_email"] = email
            item["last_successful_launch"] = now_iso
            item["current_status"] = "IDLE"
            found = True
            break
    if not found:
        items.append({
            "profile_id": profile_id,
            "user_data_dir": str((BROWSER_DIR / profile_id).resolve()),
            "auth_status": auth_status,
            "account_email": email,
            "flow_capable": True,
            "gemini_capable": True,
            "assigned_worker_id": None,
            "enabled": True,
            "last_successful_launch": now_iso,
            "last_successful_gemini_review": None,
            "current_status": "IDLE"
        })
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def save_verified_id(account_id: int):
    verified = []
    if VERIFIED_FILE.exists():
        try:
            with open(VERIFIED_FILE, "r", encoding="utf-8") as f:
                verified = json.load(f)
        except Exception:
            pass
    if account_id not in verified:
        verified.append(account_id)
        with open(VERIFIED_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(verified), f, indent=2)


def login_account(acc: dict):
    profile_name = acc["profile"]
    profile_dir = BROWSER_DIR / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)
    clean_profile_locks(profile_dir)

    print("\n" + "=" * 70)
    print(f"  OPENING CHROME FOR: Profile {acc['id']} — {acc['label']}")
    print(f"  Target Google Account: {acc['email']}")
    print("=" * 70)
    print(f">> Browser profile: {profile_dir}")
    print(f">> Opening Google Flow and Gemini tabs...")
    print(f">> Please sign into: {acc['email']}")
    print(f">> When both Google Flow and Gemini are loaded and visible,")
    print(f">> press ENTER in this console to verify and save.\n")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--start-maximized"
            ],
            viewport={"width": 1280, "height": 900}
        )

        # Tab 1: Google Flow
        page_flow = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page_flow.goto("https://labs.google/fx/tools/flow", timeout=45000, wait_until="domcontentloaded")
        except Exception:
            pass

        # Tab 2: Gemini
        page_gemini = ctx.new_page()
        try:
            page_gemini.goto("https://gemini.google.com/app", timeout=45000, wait_until="domcontentloaded")
        except Exception:
            pass

        page_gemini.bring_to_front()

        try:
            input(">> Press ENTER once you have completed sign-in on both tabs: ")
        except EOFError:
            pass

        print("\nVerifying authentication status...")
        
        # Check Gemini
        gemini_auth = False
        gemini_user = None
        try:
            page_gemini.bring_to_front()
            page_gemini.wait_for_timeout(2000)
            avatar = page_gemini.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
            if avatar:
                gemini_user = avatar.get_attribute("aria-label") or "Authenticated"
                gemini_auth = True
        except Exception as e:
            print(f"  Gemini check: {e}")

        # Check Flow
        flow_auth = False
        try:
            page_flow.bring_to_front()
            page_flow.wait_for_timeout(2000)
            body = page_flow.inner_text("body")
            if "Sign in" not in body or "Credits" in body or "Create" in body:
                flow_auth = True
        except Exception as e:
            print(f"  Flow check: {e}")

        ctx.close()

    # Save to registry
    actual_email = acc["email"]
    if gemini_user and "@" in gemini_user:
        # Extract email if present
        import re
        m = re.search(r'[\w\.-]+@[\w\.-]+', gemini_user)
        if m:
            actual_email = m.group(0)

    save_registry_profile(profile_name, actual_email, "AUTHENTICATED" if gemini_auth else "AUTH_REQUIRED")
    save_verified_id(acc["id"])

    print("=" * 70)
    print(f"  [✓] PROFILE {acc['id']} ({profile_name}) SAVED!")
    print(f"  Account: {actual_email}")
    print(f"  Gemini Status: {'🟢 Authenticated' if gemini_auth else '⚪ Needs Auth'}")
    print(f"  Flow Status:   {'🟢 Authenticated' if flow_auth else '⚪ Needs Auth'}")
    print("=" * 70 + "\n")


def main():
    while True:
        registry = {p.get("profile_id"): p for p in load_registry()}

        print("\n" + "=" * 70)
        print("  GOOGLE FLOW & GEMINI — 5-ACCOUNT ONBOARDING MANAGER")
        print("=" * 70)
        next_pending = None
        for acc in ACCOUNTS:
            reg = registry.get(acc["profile"], {})
            is_auth = reg.get("auth_status") == "AUTHENTICATED"
            status_mark = "🟢 Authenticated & Ready" if is_auth else "⚪ Needs Login"
            print(f"  [{acc['id']}] {acc['profile']:<15} | {status_mark:<24} | {acc['email']}")
            if not is_auth and not next_pending:
                next_pending = acc

        print("=" * 70)
        if not next_pending:
            print("  🎉 ALL 5 PROFILES ARE AUTHENTICATED AND READY FOR PRODUCTION!")
            print("=" * 70)
            ans = input("Enter a profile number (1-5) to re-login, or 'q' to quit: ").strip()
            if ans.lower() == 'q':
                break
            target = next((a for a in ACCOUNTS if str(a["id"]) == ans), None)
            if target:
                login_account(target)
            continue

        prompt_str = f"Press ENTER to login Profile {next_pending['id']} ({next_pending['email']}), or enter 1-5 (q to quit): "
        choice = input(prompt_str).strip()

        if choice.lower() == 'q':
            break

        target = next_pending
        if choice and choice.isdigit():
            picked = next((a for a in ACCOUNTS if str(a["id"]) == choice), None)
            if picked:
                target = picked

        login_account(target)


if __name__ == "__main__":
    main()
