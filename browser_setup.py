"""
Simple browser setup - opens Chromium, keeps it open until you close it.
Login to Google Flow, then just close the browser window when done.
Your session will be saved automatically.
"""
import sys
import os

# Fix Windows console encoding
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright
from pathlib import Path
import time

PROFILE_DIR = Path(__file__).parent / "browser" / "google_flow_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

print(">> Opening browser for Google Flow login...")
print(f"   Profile saved to: {PROFILE_DIR}")
print("   -> Log into your Google account")
print("   -> Once you see Google Flow with your credits, just CLOSE the browser window")
print("   -> Your session will be saved automatically")
print()

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        viewport={"width": 1280, "height": 900},
        accept_downloads=True
    )
    
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://labs.google/fx/tools/video-fx", wait_until="domcontentloaded", timeout=60000)
    
    print(">> Browser is open! Log in now.")
    print("   Close the browser window when you are done.")
    print()
    
    # Keep alive until user closes the browser
    try:
        while True:
            try:
                _ = context.pages
                time.sleep(1)
            except Exception:
                break
    except KeyboardInterrupt:
        pass
    
    try:
        context.close()
    except Exception:
        pass

print("")
print(">> Session saved! You can now run the pipeline with --flow")
