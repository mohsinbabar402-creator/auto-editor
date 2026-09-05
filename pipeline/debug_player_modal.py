"""
Debug player modal and download menu dropdown
"""
import sys, os, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
        viewport={'width': 1280, 'height': 900},
        accept_downloads=True
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Click Card 1 (City Skyscrapers)
    print("Clicking Card 1 (City Skyscrapers) at (250, 250)...", flush=True)
    page.mouse.click(250, 250)
    page.wait_for_timeout(2500)

    page.screenshot(path=str(proj_dir / "player_modal_card1.png"))
    print("Screenshot saved to player_modal_card1.png", flush=True)

    # List all buttons in the player
    buttons = page.locator('button').all()
    print(f"Found {len(buttons)} buttons in modal:", flush=True)
    for i, b in enumerate(buttons):
        try:
            txt = b.inner_text().replace('\n', ' ')
            aria = b.get_attribute('aria-label') or ''
            if 'download' in txt.lower() or 'download' in aria.lower() or 'done' in txt.lower() or 'done' in aria.lower():
                print(f"  [{i}] text='{txt}' aria='{aria}'", flush=True)
        except: pass

    # Click download button and capture popup
    dl = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
    if dl.is_visible():
        print("Clicking download button...", flush=True)
        dl.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(proj_dir / "player_download_clicked.png"))
        print("Screenshot saved to player_download_clicked.png", flush=True)

    context.close()

print("Player inspection complete.", flush=True)
