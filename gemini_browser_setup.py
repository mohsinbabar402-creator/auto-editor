"""
gemini_browser_setup.py
Opens a real Chrome browser window pointing to https://gemini.google.com/app
using the dedicated persistent profile at 'browser/gemini_profile'.

Sign in with your Google account (e.g. mohsinoctal777@gmail.com or any Gemini account).
Once logged in, simply close the browser window.
Your session is saved permanently for the Whop production review loop.
"""

import sys
import os
from pathlib import Path
import time
from playwright.sync_api import sync_playwright

# Windows console encoding
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROFILE_DIR = Path(__file__).resolve().parent / "browser" / "google_flow_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 65)
print(" GEMINI BROWSER PROFILE SETUP")
print("=" * 65)
print(f"Profile saved to: {PROFILE_DIR}")
print("1. Chrome will open to https://gemini.google.com/app")
print("2. Click 'Sign in' and log into your Google account.")
print("   (Recommended: mohsinoctal777@gmail.com or any Gemini account)")
print("3. Once you see the Gemini chat interface, CLOSE the browser window.")
print("4. Your session will be permanently saved for automated video reviews.")
print("=" * 65)
print("\nOpening browser now...")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized"
        ],
        viewport={"width": 1280, "height": 900},
        accept_downloads=True
    )
    
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)
    
    print("\n>> Browser is open! Please log in now.")
    print(">> Close the browser window when you are done.\n")
    
    try:
        while True:
            try:
                # Check if any pages remain open
                if not context.pages:
                    break
                time.sleep(1)
            except Exception:
                break
    except KeyboardInterrupt:
        pass
    
    try:
        context.close()
    except Exception:
        pass

print("\n" + "=" * 65)
print("SUCCESS: Gemini session saved permanently!")
print("The Whop production review loop can now use this profile.")
print("=" * 65)
