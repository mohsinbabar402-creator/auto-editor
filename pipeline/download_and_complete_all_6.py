"""
Download all 6 unique video clips by clicking the top scene icons in the player modal,
generate Scene 5 & Scene 6, run Gemini AI Review, and composite.
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

PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

print("="*65, flush=True)
print("📥 FULL 6-SCENE DOWNLOAD & GEMINI AI AUDIT PIPELINE", flush=True)
print("="*65, flush=True)

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

    # Open the player modal by clicking the first card on canvas
    print("Opening player modal...", flush=True)
    page.mouse.click(250, 250)
    page.wait_for_timeout(3000)

    # In the top center, there are thumbnail icons for each scene in the session:
    # We can click each icon at (480, 40), (505, 40), (530, 40), (555, 40)
    # Or locate img elements inside the top navigation bar
    top_icons = [
        (480, 40, "scene_02.mp4", "Scene 2: Supersonic Winds & City Disintegration"),
        (505, 40, "scene_01.mp4", "Scene 1: Earth Stopping Orbital Hook"),
        (530, 40, "scene_03.mp4", "Scene 3: Mega-Tsunami Water Wall"),
        (555, 40, "scene_04.mp4", "Scene 4: Aurora & Magnetic Shield Collapse"),
    ]

    for ix, iy, filename, label in top_icons:
        print(f"\n• Selecting {label} -> {filename}...", flush=True)
        try:
            # Click scene icon in top bar
            page.mouse.click(ix, iy)
            page.wait_for_timeout(2000)

            # Click download icon (at top right around x=766, y=40 or selector)
            dl_btn = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
            t_path = clips_dir / filename
            if dl_btn.is_visible(timeout=3000):
                with page.expect_download(timeout=20000) as dl_info:
                    dl_btn.click()
                dl_info.value.save_as(str(t_path))
                print(f"  ✅ Saved {filename}: {t_path.stat().st_size // 1024} KB", flush=True)
            else:
                # Click coordinates of download icon in top bar
                with page.expect_download(timeout=20000) as dl_info:
                    page.mouse.click(766, 40)
                dl_info.value.save_as(str(t_path))
                print(f"  ✅ Saved {filename} via coordinate click: {t_path.stat().st_size // 1024} KB", flush=True)
        except Exception as e:
            print(f"  Download notice: {e}", flush=True)

    # Close modal
    done_btn = page.locator('button:has-text("Done")').first
    if done_btn.is_visible(timeout=2000):
        done_btn.click(force=True)
        page.wait_for_timeout(2000)

    context.close()

print("\nRunning Gemini AI Video Review Audit...", flush=True)
gemini_full_video_review(proj_dir)
