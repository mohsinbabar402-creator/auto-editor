"""
Precise top thumbnail selector & generator for all 6 scenes
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

    # Click Card 1 to open player
    page.mouse.click(250, 250)
    page.wait_for_timeout(3000)

    # In the player modal, look for the scene thumbnails container
    thumbs = page.locator('header img, div[role="tablist"] img, div:has(> img[src*="googleusercontent"]) img').all()
    print(f"Found {len(thumbs)} scene thumbnail elements in player modal", flush=True)

    # Map thumbnails:
    # Thumb 0 -> City Skyscrapers (Scene 2)
    # Thumb 1 -> Earth in Space (Scene 1)
    # Thumb 2 -> Mega-Tsunami (Scene 3)
    # Thumb 3 -> Aurora Borealis (Scene 4)

    target_mapping = [
        (0, "scene_02.mp4", "Scene 2: City Skyscrapers Destruction"),
        (1, "scene_01.mp4", "Scene 1: Earth in Space Hook"),
        (2, "scene_03.mp4", "Scene 3: Mega-Tsunami Ocean Wall"),
        (3, "scene_04.mp4", "Scene 4: Aurora Magnetic Collapse"),
    ]

    for t_idx, filename, label in target_mapping:
        if t_idx < len(thumbs):
            print(f"\nClicking thumbnail [{t_idx}] -> {label}...", flush=True)
            thumbs[t_idx].click()
            page.wait_for_timeout(2500)

            # Click download button
            dl_btn = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
            if dl_btn.is_visible(timeout=3000):
                t_path = clips_dir / filename
                with page.expect_download(timeout=20000) as dl_info:
                    dl_btn.click()
                dl_info.value.save_as(str(t_path))
                print(f"  ✅ Saved: {filename} ({t_path.stat().st_size // 1024} KB)", flush=True)

    # Close modal to generate Scene 5 and Scene 6
    done_btn = page.locator('button:has-text("Done")').first
    if done_btn.is_visible(timeout=2000):
        done_btn.click(force=True)
        page.wait_for_timeout(2000)

    # Queue Scene 5 & Scene 6
    print("\n--- Submitting Scene 5 (Frozen/Scorched) & Scene 6 (Twilight Horizon) ---", flush=True)
    chat_in = page.locator('[contenteditable="true"]').first
    if chat_in.is_visible(timeout=3000):
        chat_in.click()
        prompt_5_6 = "Generate cinematic 9:16 vertical videos for:\n[Scene 5: Half Frozen Half Scorched Wasteland]\nSplit planetary orbital perspective, left half scorching orange desert dunes, right half blue blizzard glaciers.\n\n[Scene 6: The Twilight Ribbon Silhouette]\nSolitary silhouette of a person on a cliff edge looking out at glowing golden twilight horizon between day and night."
        page.keyboard.type(prompt_5_6, delay=3)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")

        # Auto approve
        for _ in range(5):
            page.wait_for_timeout(2000)
            app = page.locator('text="Approve, do not ask again", text="Approve"').last
            if app.is_visible(timeout=1000):
                app.click(force=True)
                print("  ✓ Approved credit confirmation for Scene 5 & 6.")
                break

    print("\nWaiting 90s for Scene 5 & 6 cloud render...", flush=True)
    for _ in range(6):
        page.wait_for_timeout(15000)

    context.close()

print("\nAudit running now...", flush=True)
gemini_full_video_review(proj_dir)
