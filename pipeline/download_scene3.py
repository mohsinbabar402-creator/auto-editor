"""
Robust clip downloader that handles download menu options if present
"""
import sys, os, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"
PROJECT_URL = "https://labs.google/fx/tools/flow/project/9b78c938-72d2-4167-9edf-84dbc20ad57a"

def download_card(page, card_x, card_y, filename):
    print(f"\n--- Downloading {filename} at ({card_x}, {card_y}) ---", flush=True)
    page.mouse.click(card_x, card_y)
    page.wait_for_timeout(3000)

    # Check if player opened
    dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
    if dl_btn.is_visible(timeout=3000):
        print("Found download button, clicking...", flush=True)
        try:
            with page.expect_download(timeout=10000) as dl_info:
                dl_btn.click()
            dl = dl_info.value
            target_path = clips_dir / filename
            dl.save_as(str(target_path))
            print(f"✅ Saved direct download: {filename} ({target_path.stat().st_size // 1024} KB)", flush=True)
        except Exception:
            # Check if a menu popped up (e.g. "Original", "Video (MP4)", etc.)
            menu_items = page.locator('div[role="menuitem"], li, button:has-text("Original"), button:has-text("MP4"), span:has-text("MP4")').all()
            print(f"Found {len(menu_items)} menu items after download click", flush=True)
            for item in menu_items:
                try:
                    if item.is_visible():
                        print(f"Clicking menu item: {item.inner_text()}...", flush=True)
                        with page.expect_download(timeout=15000) as dl_info2:
                            item.click()
                        dl = dl_info2.value
                        target_path = clips_dir / filename
                        dl.save_as(str(target_path))
                        print(f"✅ Saved menu download: {filename} ({target_path.stat().st_size // 1024} KB)", flush=True)
                        break
                except Exception as e:
                    print(f"Item note: {e}", flush=True)

    # Return to canvas
    done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
    if done_btn.is_visible(timeout=2000):
        done_btn.click(force=True)
        page.wait_for_timeout(2000)

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

    # Download Card 2 (Mega-Tsunami) -> scene_03.mp4
    download_card(page, 380, 260, "scene_03.mp4")

    # Download Card 4 (Split Earth) -> scene_04.mp4
    download_card(page, 650, 260, "scene_04.mp4")

    context.close()

print("\nBatch download script finished!", flush=True)
