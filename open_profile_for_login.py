import json
import logging
import os
from pathlib import Path
import re
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
BROWSER_DIR = BASE_DIR / "browser"
REGISTRY_FILE = BROWSER_DIR / "profile_registry.json"
VERIFIED_FILE = BASE_DIR / "verified_sessions.json"

ACCOUNTS = {
    1: {"profile": "flow_profile_1", "email": "mohsinoctal777@gmail.com", "label": "Primary Chrome (Pro)"},
    2: {"profile": "flow_profile_2", "email": "aoctal522@gmail.com", "label": "Octal (Already Authenticated)"},
    3: {"profile": "flow_profile_3", "email": "mohsinmughal1771@gmail.com", "label": "Mughal official (Pro)"},
    4: {"profile": "flow_profile_4", "email": "blazingsoul451@gmail.com", "label": "Blazing soul (Pro)"},
    5: {"profile": "flow_profile_5", "email": "zestify1771@gmail.com", "label": "Alex / Zestify (Pro)"},
}


def clean_locks(p_dir: Path):
    for name in ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"]:
        f = p_dir / name
        if f.exists():
            try:
                f.unlink()
            except Exception:
                pass


def update_registry(profile_id: str, email: str, is_auth: bool):
    items = []
    if REGISTRY_FILE.exists():
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception:
            pass

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    found = False
    for item in items:
        if item.get("profile_id") == profile_id:
            if is_auth:
                item["auth_status"] = "AUTHENTICATED"
            item["account_email"] = email
            item["last_successful_launch"] = now_iso
            item["current_status"] = "IDLE"
            found = True
            break

    if not found:
        items.append({
            "profile_id": profile_id,
            "user_data_dir": str((BROWSER_DIR / profile_id).resolve()),
            "auth_status": "AUTHENTICATED" if is_auth else "AUTH_REQUIRED",
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


def update_verified(acc_id: int):
    verified = []
    if VERIFIED_FILE.exists():
        try:
            with open(VERIFIED_FILE, "r", encoding="utf-8") as f:
                verified = json.load(f)
        except Exception:
            pass
    if acc_id not in verified:
        verified.append(acc_id)
        with open(VERIFIED_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(verified), f, indent=2)


def main():
    profile_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    acc = ACCOUNTS.get(profile_num)
    if not acc:
        print(f"Invalid profile number: {profile_num}. Choose 1, 2, 3, 4, or 5.")
        sys.exit(1)

    profile_name = acc["profile"]
    p_dir = BROWSER_DIR / profile_name
    p_dir.mkdir(parents=True, exist_ok=True)
    clean_locks(p_dir)

    print("=" * 70, flush=True)
    print(f"  ONE-TIME LOGIN SETUP — PROFILE {profile_num} ({profile_name})", flush=True)
    print(f"  Target Google Account: {acc['email']} ({acc['label']})", flush=True)
    print(f"  Directory: {p_dir}", flush=True)
    print("=" * 70, flush=True)
    print("1. Chrome will open on your screen with Google Flow & Gemini.", flush=True)
    print(f"2. Log into your Google Account: {acc['email']}", flush=True)
    print("3. Ensure you can see both Google Flow and Gemini prompt areas.", flush=True)
    print("4. When you are done logging in, simply CLOSE the Chrome window.", flush=True)
    print("=" * 70 + "\n", flush=True)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(p_dir),
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

        # Flow tab
        page_flow = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page_flow.goto("https://labs.google/fx/tools/flow", timeout=45000, wait_until="domcontentloaded")
        except Exception:
            pass

        # Gemini tab
        page_gemini = ctx.new_page()
        try:
            page_gemini.goto("https://gemini.google.com/app", timeout=45000, wait_until="domcontentloaded")
        except Exception:
            pass

        page_gemini.bring_to_front()

        print(">> Chrome is open! Sign into Google now.", flush=True)
        print(">> Close the Chrome window when finished.\n", flush=True)

        detected_email = acc["email"]
        gemini_auth = False
        flow_auth = False

        # Monitor loop until window is closed or authenticated
        while True:
            time.sleep(1.5)
            try:
                if not ctx.pages or len(ctx.pages) == 0:
                    break
                if page_gemini.is_closed() and page_flow.is_closed():
                    break

                # Periodically check Gemini auth in background
                if not gemini_auth and not page_gemini.is_closed():
                    avatar = page_gemini.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
                    if avatar:
                        aria = avatar.get_attribute("aria-label") or ""
                        if "@" in aria:
                            m = re.search(r'[\w\.-]+@[\w\.-]+', aria)
                            if m:
                                detected_email = m.group(0)
                        gemini_auth = True
                        print(f"  [✓] Detected Gemini login: {detected_email}!", flush=True)

                if not flow_auth and not page_flow.is_closed():
                    body = page_flow.inner_text("body")
                    if "Credits" in body or "Create" in body:
                        flow_auth = True
                        print(f"  [✓] Detected Google Flow login!", flush=True)

            except Exception:
                break

        try:
            ctx.close()
        except Exception:
            pass

    # Record results
    is_authenticated = gemini_auth or flow_auth
    update_registry(profile_name, detected_email, is_authenticated)
    if is_authenticated:
        update_verified(profile_num)

    print("\n" + "=" * 70, flush=True)
    if is_authenticated:
        print(f"  🎉 SUCCESS! Profile {profile_num} ({profile_name}) is AUTHENTICATED and saved!", flush=True)
        print(f"  Google Account: {detected_email}", flush=True)
        print("  From now on, production will launch this profile automatically without sign-in prompts.", flush=True)
    else:
        print(f"  Browser closed. Profile {profile_num} saved.", flush=True)
    print("=" * 70 + "\n", flush=True)


if __name__ == "__main__":
    main()
