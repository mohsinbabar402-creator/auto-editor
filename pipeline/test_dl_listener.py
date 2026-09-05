"""
Download using page.on('download') listener and element click
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
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

downloads = []

def handle_download(dl):
    print(f"📥 Download event received: {dl.suggested_filename}", flush=True)
    downloads.append(dl)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
        viewport={'width': 1280, 'height': 900},
        accept_downloads=True
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.on("download", handle_download)

    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Click Card 1
    page.mouse.click(250, 250)
    page.wait_for_timeout(3000)

    # Click Download button in player
    dl_btn = page.locator('button:has-text("download"), button:has-text("Download")').first
    if dl_btn.is_visible():
        print("Clicking download button...", flush=True)
        dl_btn.click()
        page.wait_for_timeout(5000)

    if downloads:
        dl = downloads[-1]
        save_file = clips_dir / "scene_02.mp4"
        dl.save_as(str(save_file))
        print(f"✅ Saved downloaded file to {save_file} ({save_file.stat().st_size // 1024} KB)")

    context.close()

print("Test complete.")
