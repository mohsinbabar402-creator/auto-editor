"""
Download genuine Aurora Borealis clip to scene_06.mp4
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

print("Downloading Aurora Borealis clip for Scene 6...", flush=True)

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

    # Click Card 4 (Aurora) at (650, 250)
    page.mouse.click(650, 250)
    page.wait_for_timeout(3000)

    dl = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
    if dl.is_visible(timeout=3000):
        t6 = clips_dir / "scene_06.mp4"
        with page.expect_download(timeout=20000) as d_info:
            dl.click()
        d_info.value.save_as(str(t6))
        print(f"✅ Saved Aurora scene_06.mp4: {t6.stat().st_size // 1024} KB", flush=True)

    context.close()

print("Scene 6 Aurora download complete.")
