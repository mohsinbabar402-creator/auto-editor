import json
import logging
from pathlib import Path
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

BROWSER_DIR = Path("browser").resolve()
REGISTRY_FILE = BROWSER_DIR / "profile_registry.json"

PROFILES = [
    (1, "flow_profile_1", "mohsinoctal777@gmail.com"),
    (2, "flow_profile_2", "aoctal522@gmail.com"),
    (3, "flow_profile_3", "mohsinmughal1771@gmail.com"),
    (4, "flow_profile_4", "blazingsoul451@gmail.com"),
    (5, "flow_profile_5", "zestify1771@gmail.com"),
]

def check_profile(slot, prof_name, email):
    p_dir = BROWSER_DIR / prof_name
    if not p_dir.exists():
        return {"slot": slot, "name": prof_name, "flow": False, "gemini": False, "note": "Directory missing"}

    # Remove stale locks
    for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        f = p_dir / lk
        if f.exists():
            try:
                f.unlink()
            except Exception:
                pass

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(p_dir),
                channel="chrome",
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"]
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # Check Gemini
            gemini_logged_in = False
            user_label = None
            try:
                page.goto("https://gemini.google.com/app", timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                body = page.inner_text("body")
                avatar = page.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
                if avatar and "Sign in" not in body:
                    gemini_logged_in = True
                    user_label = avatar.get_attribute("aria-label") or "Authenticated"
            except Exception as e:
                pass

            # Check Flow
            flow_logged_in = False
            try:
                page.goto("https://labs.google/fx/tools/flow", timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                body_f = page.inner_text("body")
                if "Sign in" not in body_f or "Credits" in body_f or "Create" in body_f:
                    flow_logged_in = True
            except Exception as e:
                pass

            ctx.close()
            return {"slot": slot, "name": prof_name, "flow": flow_logged_in, "gemini": gemini_logged_in, "user": user_label}
        except Exception as e:
            return {"slot": slot, "name": prof_name, "flow": False, "gemini": False, "error": str(e)}

def main():
    print("=" * 65)
    print(" CHECKING GOOGLE FLOW & GEMINI AUTHENTICATION ACROSS ALL 5 PROFILES")
    print("=" * 65)
    results = []
    for slot, name, email in PROFILES:
        print(f"Checking Slot {slot} ({name})...", end="", flush=True)
        res = check_profile(slot, name, email)
        flow_str = "🟢 YES" if res.get("flow") else "⚪ NO"
        gemini_str = "🟢 YES" if res.get("gemini") else "⚪ NO"
        print(f" -> Flow: {flow_str} | Gemini: {gemini_str}")
        results.append(res)

    print("=" * 65)

if __name__ == "__main__":
    main()
