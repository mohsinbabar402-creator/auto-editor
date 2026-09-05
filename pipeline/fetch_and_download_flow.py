"""
Direct Google Flow Video Downloader & Generator
Navigates to project, clicks Videos tab / canvas video card, downloads rendered MP4s.
"""
import sys, os, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

PROJECT_NAME = "earth_stops_rotating"
proj_dir = config.PROJECTS_DIR / PROJECT_NAME
clips_dir = proj_dir / "clips"
clips_dir.mkdir(parents=True, exist_ok=True)
prompts_file = proj_dir / "google_flow_prompts.json"

with open(prompts_file, "r", encoding="utf-8") as f:
    prompts = json.load(f)

print("="*60, flush=True)
print("🎬 GOOGLE FLOW DIRECT VIDEO MATCHER & DOWNLOADER", flush=True)
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

    # Step 1: Open Google Flow
    print("Navigating to Google Flow...", flush=True)
    page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    # Step 2: Check for existing projects or create a new project
    print("Accessing latest project...", flush=True)
    # Click on the first existing project card if available
    proj_cards = page.locator('div:has-text("Untitled session"), div[role="button"]:has(img), a[href*="/project/"]').all()
    if proj_cards:
        try:
            proj_cards[0].click()
            page.wait_for_timeout(4000)
        except:
            pass

    if "/project/" not in page.url:
        new_btn = page.locator('button:has-text("New project")').first
        if new_btn.is_visible(timeout=3000):
            new_btn.click()
            page.wait_for_timeout(6000)

    print(f"Current URL: {page.url}", flush=True)
    page.screenshot(path=str(proj_dir / "current_editor_state.png"))

    # Step 3: Check Videos in sidebar
    print("Checking All Media / Videos gallery...", flush=True)
    try:
        videos_tab = page.locator('button:has-text("Videos"), div:has-text("Videos"), button:has-text("All Media")').first
        if videos_tab.is_visible(timeout=3000):
            videos_tab.click()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(proj_dir / "gallery_view.png"))
    except Exception as e:
        print(f"Gallery notice: {e}", flush=True)

    # Look for download buttons or video streams
    print("Searching for downloadable video assets...", flush=True)
    download_buttons = page.locator('button[aria-label*="Download" i], button:has-text("Download"), a[download], [data-tooltip*="Download" i]').all()
    print(f"Found {len(download_buttons)} download buttons on page", flush=True)

    for i, btn in enumerate(download_buttons):
        try:
            if btn.is_visible():
                print(f"Clicking download button [{i}]...", flush=True)
                with page.expect_download(timeout=15000) as dl_info:
                    btn.click()
                dl = dl_info.value
                out_path = clips_dir / f"scene_03.mp4"
                dl.save_as(str(out_path))
                print(f"✅ Downloaded to: {out_path} ({out_path.stat().st_size // 1024} KB)", flush=True)
                break
        except Exception as err:
            print(f"Button [{i}] download note: {err}", flush=True)

    context.close()

print("="*60, flush=True)
print("Fetch script completed.", flush=True)
