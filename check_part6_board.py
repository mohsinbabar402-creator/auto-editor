import sys, os, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from playwright.sync_api import sync_playwright

p6_url = "https://labs.google/fx/tools/flow/project/8e78e0af-eeb0-4d3e-a462-e30fe8fc966a"
screenshot_path = config.PROJECTS_DIR / "part6_the_twilight_zone" / "part6_board_check.png"

print("Checking Part 6 project board in Google Flow...", flush=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1400, "height": 900}
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(p6_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    
    page.screenshot(path=str(screenshot_path))
    print(f"Part 6 screenshot saved: {screenshot_path}")
    
    # Count media items / cards
    cards = page.locator('img[src*="googleusercontent"]').all()
    print(f"Found {len(cards)} cards on Part 6 board!")
    
    ctx.close()
