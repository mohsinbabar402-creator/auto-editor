"""
Direct coordinate-based player thumbnail switcher & downloader
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

print("="*65, flush=True)
print("🎯 EXACT SCENE DOWNLOAD & GEMINI AI AUDIT", flush=True)
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

    # 1. Open player modal
    print("Opening player modal...", flush=True)
    page.mouse.click(250, 250)
    page.wait_for_timeout(3000)

    # Top scene icons in the center header:
    # 4-6 small thumbnail buttons at y=40:
    # Thumb 1 (City Winds): x=380
    # Thumb 2 (Earth Space): x=405
    # Thumb 3 (Mega-Tsunami): x=430
    # Thumb 4 (Aurora): x=455
    # Thumb 5 (Frozen/Scorched): x=480
    # Thumb 6 (Twilight): x=505

    scene_targets = [
        (380, 40, "scene_02.mp4", "Scene 2: Supersonic City Winds"),
        (405, 40, "scene_01.mp4", "Scene 1: Earth in Space Hook"),
        (430, 40, "scene_03.mp4", "Scene 3: Mega-Tsunami Water Wall"),
        (455, 40, "scene_04.mp4", "Scene 4: Aurora & Magnetic Shield"),
        (480, 40, "scene_05.mp4", "Scene 5: Half Frozen / Half Scorched"),
        (505, 40, "scene_06.mp4", "Scene 6: Twilight Horizon Silhouette"),
    ]

    for tx, ty, filename, label in scene_targets:
        print(f"\n• Selecting {label} at ({tx}, {ty})...", flush=True)
        try:
            # Click top thumbnail icon
            page.mouse.click(tx, ty)
            page.wait_for_timeout(2000)

            # Click download icon at top right (x=766, y=40)
            t_path = clips_dir / filename
            try:
                with page.expect_download(timeout=12000) as dl_info:
                    page.mouse.click(766, 40)
                dl_info.value.save_as(str(t_path))
                print(f"  ✅ Downloaded {filename}: {t_path.stat().st_size // 1024} KB", flush=True)
            except Exception as dl_err:
                print(f"  DL error on {filename}: {dl_err}", flush=True)
        except Exception as e:
            print(f"  Notice on {filename}: {e}", flush=True)

    context.close()

print("\n" + "="*65, flush=True)
print("Auditing downloaded clips with Gemini AI Reviewer...", flush=True)
review_result = gemini_full_video_review(proj_dir)

if review_result["passed"]:
    print("🎉 ALL CLIPS PASSED AUDIT WITH ZERO DUPLICATES! Rendering final video...", flush=True)
    import subprocess
    cmd = ["python", "run_pipeline.py", "--project", "earth_stops_rotating"]
    subprocess.run(cmd)
else:
    print("⚠️ Gemini Audit detected issues. Please check report above.", flush=True)
