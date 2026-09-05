"""
Direct Gallery Batch Downloader
Opens Videos tab and downloads all video items one by one.
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

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
        viewport={'width': 1280, 'height': 900},
        accept_downloads=True
    )
    page = context.pages[0] if context.pages else context.new_page()

    print("Navigating to project...", flush=True)
    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Click Videos tab in sidebar
    print("Opening Videos panel...", flush=True)
    v_tab = page.locator('button:has-text("Videos"), div:has-text("Videos")').first
    if v_tab.is_visible(timeout=3000):
        v_tab.click()
        page.wait_for_timeout(3000)

    # Find all video cards in the gallery
    video_cards = page.locator('img[src*="googleusercontent"]').all()
    print(f"Found {len(video_cards)} video items in gallery", flush=True)

    target_files = ["scene_03.mp4", "scene_04.mp4", "scene_05.mp4", "scene_06.mp4"]

    for idx, card in enumerate(video_cards[2:]):
        if idx >= len(target_files):
            break
        t_name = target_files[idx]
        print(f"\n• Downloading video [{idx+3}] -> {t_name}...", flush=True)
        try:
            card.click(force=True)
            page.wait_for_timeout(2500)

            dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
            if dl_btn.is_visible(timeout=4000):
                target_path = clips_dir / t_name
                with page.expect_download(timeout=25000) as dl_info:
                    dl_btn.click()
                dl = dl_info.value
                dl.save_as(str(target_path))
                print(f"  ✅ Saved: {t_name} ({target_path.stat().st_size // 1024} KB)", flush=True)

            done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
            if done_btn.is_visible(timeout=2000):
                done_btn.click(force=True)
                page.wait_for_timeout(1500)
        except Exception as e:
            print(f"  Note on {t_name}: {e}", flush=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

    context.close()

print("\nGallery download finished!", flush=True)
