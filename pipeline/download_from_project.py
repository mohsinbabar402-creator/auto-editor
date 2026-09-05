"""
Download all completed videos directly from the exact project URL
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

PROJECT_URL = "https://labs.google/fx/tools/flow/project/9b78c938-72d2-4167-9edf-84dbc20ad57a"

print("="*60, flush=True)
print("FAST DOWNLOADING ALL 4 FINISHED CLIPS", flush=True)
print("="*60, flush=True)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
        viewport={'width': 1280, 'height': 900},
        accept_downloads=True
    )
    page = context.pages[0] if context.pages else context.new_page()

    print(f"Navigating to project: {PROJECT_URL}...", flush=True)
    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    # Click on the canvas video cards at different X positions:
    # 4 cards horizontally spaced across the canvas
    card_positions = [
        (250, 260, "scene_01.mp4"),
        (510, 260, "scene_03.mp4"),
        (650, 260, "scene_04.mp4"),
    ]

    for idx, (cx, cy, filename) in enumerate(card_positions):
        print(f"\n• Downloading [{idx+1}/3] -> {filename}...", flush=True)
        try:
            # Click card on canvas
            page.mouse.click(cx, cy)
            page.wait_for_timeout(3000)

            # Look for download button
            dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
            if dl_btn.is_visible(timeout=5000):
                target_path = clips_dir / filename
                with page.expect_download(timeout=30000) as dl_info:
                    dl_btn.click()
                dl = dl_info.value
                dl.save_as(str(target_path))
                print(f"  ✅ Saved: {filename} ({target_path.stat().st_size // 1024} KB)", flush=True)

            # Return back to canvas with Done button
            done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
            if done_btn.is_visible(timeout=3000):
                done_btn.click(force=True)
                page.wait_for_timeout(2500)
        except Exception as e:
            print(f"  Note on {filename}: {e}", flush=True)
            # Try pressing Escape to close any modal
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

    context.close()

print("\nFinished downloading batch clips!", flush=True)
