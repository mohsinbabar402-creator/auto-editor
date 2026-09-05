"""
Download unique Scene 6 from Google Flow project
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

    # In the chat, prompt for Scene 6 silhouette
    chat_in = page.locator('[contenteditable="true"]').first
    if chat_in.is_visible(timeout=3000):
        chat_in.click()
        prompt = "Create a cinematic 9:16 vertical video of Scene 6: Solitary silhouetted human traveler standing on a cliff edge overlooking the golden glowing twilight horizon line between fire and ice."
        page.keyboard.type(prompt, delay=3)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)

        for _ in range(4):
            app = page.locator('text="Approve, do not ask again", text="Approve"').last
            if app.is_visible(timeout=1000):
                app.click(force=True)
                print("✓ Approved Scene 6 credit confirmation.", flush=True)
                break
            page.wait_for_timeout(1500)

    print("Waiting 90s for Scene 6 render...", flush=True)
    for _ in range(6):
        page.wait_for_timeout(15000)

    # Click the new video card on canvas (top left or last card)
    print("Downloading Scene 6 video card...", flush=True)
    cards = page.locator('img[src*="googleusercontent"]').all()
    if cards:
        cards[-1].click(force=True)
        page.wait_for_timeout(3000)

        dl_btn = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
        if dl_btn.is_visible(timeout=3000):
            t6 = clips_dir / "scene_06.mp4"
            with page.expect_download(timeout=20000) as dl_info:
                dl_btn.click()
            dl_info.value.save_as(str(t6))
            print(f"✅ Saved unique scene_06.mp4: {t6.stat().st_size // 1024} KB", flush=True)

    context.close()

print("Scene 6 download complete.")
