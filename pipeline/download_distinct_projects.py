"""
Download distinct project scenes and audit with Gemini AI
"""
import sys, os, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright
from pipeline.gemini_video_reviewer import gemini_full_video_review

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"
clips_dir.mkdir(parents=True, exist_ok=True)

# 1. Earth in space -> Project 1
# 2. City skyscrapers -> Project 2 (Card 1)
# 3. Mega-tsunami -> Project 3
# 4. Aurora -> Project 2 (Card 4)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
        viewport={'width': 1280, 'height': 900},
        accept_downloads=True
    )
    page = context.pages[0] if context.pages else context.new_page()

    # Step 1: Download Scene 1 (Earth in Space)
    print("--- [1/4] Fetching Scene 1 (Earth in Space) ---", flush=True)
    page.goto("https://labs.google/fx/tools/flow/project/2407510d-aa9c-421c-97cd-2f450048f16a", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    page.mouse.click(270, 300)
    page.wait_for_timeout(2000)
    dl = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
    if dl.is_visible(timeout=3000):
        t1 = clips_dir / "scene_01.mp4"
        with page.expect_download(timeout=20000) as d_info:
            dl.click()
        d_info.value.save_as(str(t1))
        print(f"  ✅ Saved scene_01.mp4: {t1.stat().st_size // 1024} KB", flush=True)

    # Step 2: Download Scene 3 (Mega-Tsunami)
    print("--- [2/4] Fetching Scene 3 (Mega-Tsunami) ---", flush=True)
    page.goto("https://labs.google/fx/tools/flow/project/9b78c938-72d2-4167-9edf-84dbc20ad57a", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    page.mouse.click(270, 300)
    page.wait_for_timeout(2000)
    dl = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
    if dl.is_visible(timeout=3000):
        t3 = clips_dir / "scene_03.mp4"
        with page.expect_download(timeout=20000) as d_info:
            dl.click()
        d_info.value.save_as(str(t3))
        print(f"  ✅ Saved scene_03.mp4: {t3.stat().st_size // 1024} KB", flush=True)

    # Step 3: Project 2 (City Skyscrapers & Aurora)
    print("--- [3/4] Fetching Scene 2 (City Skyscrapers) & Scene 4 (Aurora) ---", flush=True)
    page.goto("https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    # Card 1 (Skyscrapers) -> (250, 250)
    page.mouse.click(250, 250)
    page.wait_for_timeout(2000)
    dl = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
    if dl.is_visible(timeout=3000):
        t2 = clips_dir / "scene_02.mp4"
        with page.expect_download(timeout=20000) as d_info:
            dl.click()
        d_info.value.save_as(str(t2))
        print(f"  ✅ Saved scene_02.mp4: {t2.stat().st_size // 1024} KB", flush=True)

    done_btn = page.locator('button:has-text("Done")').first
    if done_btn.is_visible(timeout=2000):
        done_btn.click(force=True)
        page.wait_for_timeout(2000)

    # Card 4 (Aurora) -> (650, 250)
    page.mouse.click(650, 250)
    page.wait_for_timeout(2000)
    dl = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
    if dl.is_visible(timeout=3000):
        t4 = clips_dir / "scene_04.mp4"
        with page.expect_download(timeout=20000) as d_info:
            dl.click()
        d_info.value.save_as(str(t4))
        print(f"  ✅ Saved scene_04.mp4: {t4.stat().st_size // 1024} KB", flush=True)

    context.close()

print("\n--- Running Gemini AI Reviewer ---", flush=True)
gemini_full_video_review(proj_dir)
