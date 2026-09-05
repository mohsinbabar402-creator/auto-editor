"""
Download each distinct video directly from its corresponding project in Google Flow
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

# 3 Distinct Projects:
PROJECT_MAPPING = [
    # 1. Earth in space with sun flare -> Scene 1
    ("https://labs.google/fx/tools/flow/project/2407510d-aa9c-421c-97cd-2f450048f16a", "scene_01.mp4", "Scene 1: Earth in Space"),
    # 2. Aurora shimmering in space -> Scene 4
    ("https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91", "scene_04.mp4", "Scene 4: Aurora Borealis"),
    # 3. Mega-tsunami -> Scene 3
    ("https://labs.google/fx/tools/flow/project/9b78c938-72d2-4167-9edf-84dbc20ad57a", "scene_03.mp4", "Scene 3: Mega-Tsunami"),
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

    for p_url, filename, label in PROJECT_MAPPING:
        print(f"\n========================================", flush=True)
        print(f"Fetching {label} -> {filename} from {p_url}...", flush=True)
        print(f"========================================", flush=True)
        try:
            page.goto(p_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            # Click canvas video card at center (270, 300)
            page.mouse.click(270, 300)
            page.wait_for_timeout(3000)

            # Find download button
            dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
            if dl_btn.is_visible(timeout=4000):
                target_path = clips_dir / filename
                with page.expect_download(timeout=25000) as dl_info:
                    dl_btn.click()
                dl = dl_info.value
                dl.save_as(str(target_path))
                print(f"  ✅ Saved {filename}: {target_path.stat().st_size // 1024} KB", flush=True)
        except Exception as e:
            print(f"  Error on {filename}: {e}", flush=True)

    context.close()

print("\nFinished downloading the 3 distinct clips!", flush=True)
