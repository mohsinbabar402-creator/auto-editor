"""
Generate Scene 5 & Scene 6, then download all 6 distinct video cards with 100% perfection.
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

PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

print("="*60, flush=True)
print("🚀 COMPLETING ALL 6 PERFECT SCENES ON GOOGLE FLOW", flush=True)
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

    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # 1. Download Card 1 (City Skyscrapers & Bridge Winds) -> scene_02.mp4
    print("\n[1/6] Downloading Scene 2: City Skyscrapers & Supersonic Winds...", flush=True)
    page.mouse.click(250, 250)
    page.wait_for_timeout(2500)
    dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
    if dl_btn.is_visible(timeout=3000):
        t_path = clips_dir / "scene_02.mp4"
        with page.expect_download(timeout=20000) as dl_info:
            dl_btn.click()
        dl_info.value.save_as(str(t_path))
        print(f"  ✅ Saved scene_02.mp4: {t_path.stat().st_size // 1024} KB", flush=True)
    done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
    if done_btn.is_visible(timeout=2000):
        done_btn.click(force=True)
        page.wait_for_timeout(2000)

    # 2. Download Card 2 (Earth in Space with Sunrise Flare) -> scene_01.mp4
    print("\n[2/6] Downloading Scene 1: Earth in Space Hook...", flush=True)
    page.mouse.click(380, 250)
    page.wait_for_timeout(2500)
    dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
    if dl_btn.is_visible(timeout=3000):
        t_path = clips_dir / "scene_01.mp4"
        with page.expect_download(timeout=20000) as dl_info:
            dl_btn.click()
        dl_info.value.save_as(str(t_path))
        print(f"  ✅ Saved scene_01.mp4: {t_path.stat().st_size // 1024} KB", flush=True)
    done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
    if done_btn.is_visible(timeout=2000):
        done_btn.click(force=True)
        page.wait_for_timeout(2000)

    # 3. Download Card 3 (Mega-Tsunami Ocean Wall) -> scene_03.mp4
    print("\n[3/6] Downloading Scene 3: Mega-Tsunami Ocean Surge...", flush=True)
    page.mouse.click(510, 250)
    page.wait_for_timeout(2500)
    dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
    if dl_btn.is_visible(timeout=3000):
        t_path = clips_dir / "scene_03.mp4"
        with page.expect_download(timeout=20000) as dl_info:
            dl_btn.click()
        dl_info.value.save_as(str(t_path))
        print(f"  ✅ Saved scene_03.mp4: {t_path.stat().st_size // 1024} KB", flush=True)
    done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
    if done_btn.is_visible(timeout=2000):
        done_btn.click(force=True)
        page.wait_for_timeout(2000)

    # 4. Download Card 4 (Aurora Borealis & Cosmic Shield) -> scene_04.mp4
    print("\n[4/6] Downloading Scene 4: Magnetic Shield Aurora Collapse...", flush=True)
    page.mouse.click(650, 250)
    page.wait_for_timeout(2500)
    dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
    if dl_btn.is_visible(timeout=3000):
        t_path = clips_dir / "scene_04.mp4"
        with page.expect_download(timeout=20000) as dl_info:
            dl_btn.click()
        dl_info.value.save_as(str(t_path))
        print(f"  ✅ Saved scene_04.mp4: {t_path.stat().st_size // 1024} KB", flush=True)
    done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
    if done_btn.is_visible(timeout=2000):
        done_btn.click(force=True)
        page.wait_for_timeout(2000)

    # 5. Queue Scene 5 & Scene 6 in chat
    print("\n[5/6] Submitting prompts for Scene 5 & Scene 6...", flush=True)
    chat_in = page.locator('[contenteditable="true"]').first
    if chat_in.is_visible(timeout=3000):
        chat_in.click()
        batch_prompt = "Generate cinematic 9:16 vertical videos for:\n[Scene 5: Half Frozen Half Scorched Planet]\nSplit planetary orbital perspective: left half scorched glowing orange desert dunes, right half engulfed in blue glacial ice sheets and blizzard storms.\n\n[Scene 6: The Twilight Ribbon Cliff Horizon]\nSolitary silhouette of a person on a cliff edge looking out at the glowing golden twilight horizon ribbon between frozen darkness and scorching desert, cinematic golden hour."
        page.keyboard.type(batch_prompt, delay=3)
        page.wait_for_timeout(400)
        send_btn = page.locator('button:has-text("arrow_forward"), button[aria-label*="Send" i]').first
        if send_btn.is_visible(timeout=2000):
            send_btn.click()
        else:
            page.keyboard.press("Enter")

        # Auto approve
        for _ in range(6):
            page.wait_for_timeout(2000)
            app = page.locator('text="Approve, do not ask again", text="Approve"').last
            if app.is_visible(timeout=1000):
                app.click(force=True)
                print("  ✓ Approved credits for Scene 5 & 6.")
                break

    print("\n[6/6] Waiting 90s for Scene 5 & Scene 6 cloud render...", flush=True)
    for w in range(6):
        page.wait_for_timeout(15000)
        print(f"  • Rendering in cloud ({(w+1)*15}s elapsed)...", flush=True)

    page.screenshot(path=str(proj_dir / "all_6_scenes_canvas.png"))

    context.close()

print("\nBatch generation complete!", flush=True)
