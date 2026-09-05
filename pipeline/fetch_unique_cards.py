"""
Accurate individual card downloader:
Opens each card, screenshots the player to verify visual uniqueness, and downloads.
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
clips_dir.mkdir(parents=True, exist_ok=True)

PROJECT_URL = "https://labs.google/fx/tools/flow/project/9b78c938-72d2-4167-9edf-84dbc20ad57a"

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

    # Coordinates of each card on canvas (from 80s screenshot):
    # Card 1 (Aurora): x=250, y=250
    # Card 2 (Tsunami): x=380, y=250
    # Card 3 (City winds): x=510, y=250
    # Card 4 (Earth orbital): x=650, y=250

    cards_to_fetch = [
        (650, 250, "scene_01.mp4", "Scene 1: Earth Orbital Sunset"),
        (510, 250, "scene_02.mp4", "Scene 2: City Supersonic Winds"),
        (380, 250, "scene_03.mp4", "Scene 3: Mega-Tsunami"),
        (250, 250, "scene_04.mp4", "Scene 4: Aurora Magnetic Collapse"),
    ]

    for cx, cy, filename, label in cards_to_fetch:
        print(f"\n========================================", flush=True)
        print(f"Targeting: {label} at ({cx}, {cy}) -> {filename}", flush=True)
        print(f"========================================", flush=True)

        # 1. Click specific card on canvas
        page.mouse.click(cx, cy)
        page.wait_for_timeout(2500)

        # 2. Take verification screenshot of the opened player modal
        shot_path = str(proj_dir / f"verify_open_{filename}.png")
        page.screenshot(path=shot_path)
        print(f"  📸 Saved modal snapshot: {shot_path}", flush=True)

        # 3. Click download
        dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
        if dl_btn.is_visible(timeout=3000):
            t_path = clips_dir / filename
            try:
                with page.expect_download(timeout=20000) as dl_info:
                    dl_btn.click()
                dl = dl_info.value
                dl.save_as(str(t_path))
                print(f"  ✅ Downloaded {filename}: {t_path.stat().st_size // 1024} KB", flush=True)
            except Exception as e:
                print(f"  Download error: {e}", flush=True)

        # 4. Click Done to return to canvas
        done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
        if done_btn.is_visible(timeout=2000):
            done_btn.click(force=True)
            page.wait_for_timeout(2000)

    context.close()

print("\nDone individual card downloads!", flush=True)
