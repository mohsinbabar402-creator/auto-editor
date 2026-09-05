import os
from pathlib import Path
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path(__file__).resolve().parent / "browser" / "google_flow_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 65, flush=True)
print(" GEMINI ONE-TIME LOGIN SETUP", flush=True)
print("=" * 65, flush=True)
print(f"Profile: {PROFILE_DIR}", flush=True)
print("1. Chrome will open to https://gemini.google.com/app", flush=True)
print("2. Click the blue 'Sign in' button in the top-right corner.", flush=True)
print("3. Enter your Google account and log in.", flush=True)
print("4. When you see your account avatar and the prompt box, CLOSE the browser window.", flush=True)
print("=" * 65, flush=True)

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
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
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://gemini.google.com/app", timeout=45000, wait_until="domcontentloaded")
    
    print("\n>> Browser is open!", flush=True)
    print(">> Please sign in on the browser window.", flush=True)
    print(">> When done, CLOSE the Chrome browser window.\n", flush=True)

    try:
        while True:
            time.sleep(1)
            if not ctx.pages or len(ctx.pages) == 0:
                break
            if page.is_closed():
                break
    except KeyboardInterrupt:
        pass
    except Exception:
        pass

    try:
        ctx.close()
    except Exception:
        pass

print("=" * 65, flush=True)
print("Browser window closed. Session saved!", flush=True)
print("=" * 65, flush=True)
