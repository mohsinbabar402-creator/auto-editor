"""
Generate distinct Scene 6 in Google Flow and download to scene_06.mp4
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
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

print("--- Generating Distinct Scene 6: Twilight Horizon Silhouette ---", flush=True)

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

    # Submit Scene 6 prompt
    chat_in = page.locator('[contenteditable="true"]').first
    if chat_in.is_visible(timeout=3000):
        chat_in.click()
        prompt6 = "Generate a cinematic 9:16 vertical video of Scene 6: A solitary human silhouette standing on a mountain cliff edge looking toward a glowing golden twilight horizon strip between fiery day and frozen starry night, National Geographic cinematic documentary, photorealistic 8K."
        page.keyboard.type(prompt6, delay=3)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)

        # Auto approve
        for _ in range(5):
            app = page.locator('text="Approve, do not ask again", text="Approve"').last
            if app.is_visible(timeout=1000):
                app.click(force=True)
                print("✓ Approved Scene 6 credit confirmation.", flush=True)
                break
            page.wait_for_timeout(1500)

    print("Waiting 90s for Scene 6 cloud generation...", flush=True)
    for _ in range(6):
        page.wait_for_timeout(15000)

    # Click the new card on canvas (or last card)
    print("Downloading Scene 6 video card...", flush=True)
    # The new card is placed on canvas
    page.mouse.click(250, 450) # second row or newest position
    page.wait_for_timeout(3000)

    dl_btn = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
    if dl_btn.is_visible(timeout=3000):
        t6 = clips_dir / "scene_06.mp4"
        try:
            with page.expect_download(timeout=20000) as dl_info:
                dl_btn.click()
            dl_info.value.save_as(str(t6))
            print(f"✅ Saved unique scene_06.mp4: {t6.stat().st_size // 1024} KB", flush=True)
        except Exception as e:
            print(f"DL note: {e}")

    context.close()

print("Scene 6 workflow finished.")
