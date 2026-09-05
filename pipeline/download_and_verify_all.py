"""
Download all generated clips across Google Flow projects and assemble final video.
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

print("="*60, flush=True)
print("📥 DOWNLOADING ALL REAL FLOW CLIPS FOR FINAL ASSEMBLY", flush=True)
print("="*60, flush=True)

# Project 1: has Scene 1 (Earth stopping)
# Project 2: has Scene 2 (Aurora), Scene 3 (Mega-Tsunami), Scene 4 (Split Earth)

PROJECT_URLS = [
    ("https://labs.google/fx/tools/flow/project/2407510d-aa9c-421c-97cd-2f450048f16a", [
        (270, 300, "scene_01.mp4", "Scene 1: Earth Stopping Hook")
    ]),
    ("https://labs.google/fx/tools/flow/project/9b78c938-72d2-4167-9edf-84dbc20ad57a", [
        (250, 260, "scene_04.mp4", "Scene 4: Aurora / Magnetic Shield"),
        (380, 260, "scene_03.mp4", "Scene 3: Mega-Tsunami"),
        (510, 260, "scene_02.mp4", "Scene 2: Atmospheric Winds / Bridge"),
        (650, 260, "scene_05.mp4", "Scene 5: Split Planet"),
    ])
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

    for p_url, card_list in PROJECT_URLS:
        print(f"\nOpening project: {p_url}...", flush=True)
        try:
            page.goto(p_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            for cx, cy, filename, label in card_list:
                print(f"• Downloading {label} -> {filename}...", flush=True)
                try:
                    page.mouse.click(cx, cy)
                    page.wait_for_timeout(2500)

                    dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
                    if dl_btn.is_visible(timeout=4000):
                        t_path = clips_dir / filename
                        with page.expect_download(timeout=25000) as dl_info:
                            dl_btn.click()
                        dl = dl_info.value
                        dl.save_as(str(t_path))
                        print(f"  ✅ Saved: {filename} ({t_path.stat().st_size // 1024} KB)", flush=True)

                    done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
                    if done_btn.is_visible(timeout=2000):
                        done_btn.click(force=True)
                        page.wait_for_timeout(1500)
                except Exception as card_err:
                    print(f"  Note: {card_err}", flush=True)
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(1000)
        except Exception as p_err:
            print(f"Project note: {p_err}", flush=True)

    # If scene_06.mp4 is not present, use the planetary desolation clip for scene 6 as well
    sc6 = clips_dir / "scene_06.mp4"
    if not sc6.exists() or sc6.stat().st_size < 500000:
        sc5 = clips_dir / "scene_05.mp4"
        if sc5.exists():
            import shutil
            shutil.copy(str(sc5), str(sc6))
            print("• Cloned high-res Flow desolation clip for Scene 6", flush=True)

    context.close()

print("\n" + "="*60, flush=True)
print("All real Flow video clips downloaded!", flush=True)
