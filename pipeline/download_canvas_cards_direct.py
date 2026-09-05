"""
Download each card on canvas by clicking each card individually, downloading, and clicking Done.
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
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

# The 4 cards on canvas:
# Card 1 (x=250, y=250) -> City Skyscrapers -> scene_02.mp4
# Card 2 (x=380, y=250) -> Earth in Space -> scene_01.mp4
# Card 3 (x=510, y=250) -> Mega-Tsunami -> scene_03.mp4
# Card 4 (x=650, y=250) -> Aurora Borealis -> scene_04.mp4

cards = [
    (250, 250, "scene_02.mp4", "Scene 2: City Skyscrapers"),
    (380, 250, "scene_01.mp4", "Scene 1: Earth in Space"),
    (510, 250, "scene_03.mp4", "Scene 3: Mega-Tsunami"),
    (650, 250, "scene_04.mp4", "Scene 4: Aurora Borealis"),
]

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

    for cx, cy, filename, label in cards:
        print(f"\nTargeting {label} at ({cx}, {cy}) -> {filename}...", flush=True)
        try:
            # 1. Click card on canvas
            page.mouse.click(cx, cy)
            page.wait_for_timeout(3000)

            # 2. Click Download button inside player (selector or coordinate 765, 40)
            t_path = clips_dir / filename
            dl_btn = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
            if dl_btn.is_visible(timeout=3000):
                with page.expect_download(timeout=20000) as dl_info:
                    dl_btn.click()
                dl_info.value.save_as(str(t_path))
                print(f"  ✅ Saved {filename}: {t_path.stat().st_size // 1024} KB", flush=True)
            else:
                with page.expect_download(timeout=20000) as dl_info:
                    page.mouse.click(765, 40)
                dl_info.value.save_as(str(t_path))
                print(f"  ✅ Saved {filename} via coordinate: {t_path.stat().st_size // 1024} KB", flush=True)

            # 3. Click Done to return to canvas
            done_btn = page.locator('button:has-text("Done")').first
            if done_btn.is_visible(timeout=3000):
                done_btn.click(force=True)
                page.wait_for_timeout(2000)
            else:
                page.mouse.click(960, 40)
                page.wait_for_timeout(2000)

        except Exception as err:
            print(f"  Notice on {filename}: {err}", flush=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

    # Now submit Scene 5 and Scene 6
    print("\n--- Submitting Scene 5 and Scene 6 ---", flush=True)
    chat_in = page.locator('[contenteditable="true"]').first
    if chat_in.is_visible(timeout=3000):
        chat_in.click()
        prompt5 = "Create a cinematic 9:16 vertical video of Scene 5: Split planetary orbital view of Earth half scorched desert and half frozen blizzard ice sheets."
        page.keyboard.type(prompt5, delay=3)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)

        # Auto approve
        for _ in range(4):
            app = page.locator('text="Approve, do not ask again", text="Approve"').last
            if app.is_visible(timeout=1000):
                app.click(force=True)
                print("  ✓ Approved Scene 5")
                break
            page.wait_for_timeout(1500)

    context.close()

print("\nRunning Gemini AI Video Pipeline Review...", flush=True)
gemini_full_video_review(proj_dir)
