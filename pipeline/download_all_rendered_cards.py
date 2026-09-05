"""
Download All Rendered Video Cards from Google Flow Project Canvas & Finalize Video
"""
import sys, os, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"
clips_dir.mkdir(parents=True, exist_ok=True)

print("="*60, flush=True)
print("📥 DOWNLOADING ALL BATCH-RENDERED VIDEO CARDS FROM GOOGLE FLOW", flush=True)
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

    print("[1/3] Accessing Google Flow project canvas...", flush=True)
    page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    # Click first project card
    proj_cards = page.locator('div:has-text("Cinematic Vertical Video"), div:has-text("Untitled session"), a[href*="/project/"]').all()
    if proj_cards:
        try:
            proj_cards[0].click()
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"Project open note: {e}", flush=True)

    print(f"Canvas URL: {page.url}", flush=True)
    page.screenshot(path=str(proj_dir / "batch_ready_canvas.png"))

    # Click on the Videos tab in the left sidebar to see all videos in a clean list
    print("[2/3] Opening Videos Gallery...", flush=True)
    try:
        videos_tab = page.locator('button:has-text("Videos"), div:has-text("Videos")').first
        if videos_tab.is_visible(timeout=3000):
            videos_tab.click()
            page.wait_for_timeout(3000)
    except:
        pass

    # Find and download all completed video items
    # Coordinates of the 4 cards on canvas:
    card_coords = [
        (250, 250), # Card 1
        (380, 250), # Card 2
        (510, 250), # Card 3
        (650, 250), # Card 4
    ]

    scene_mapping = [
        ("scene_02.mp4", "Aurora Shatter (Magnetic Shield Collapse)"),
        ("scene_03.mp4", "Mega-Tsunami Ocean Surge"),
        ("scene_01.mp4", "Instant Cataclysm / Winds"),
        ("scene_04.mp4", "Split Earth Planetary View"),
    ]

    for idx, (coord, (target_name, label)) in enumerate(zip(card_coords, scene_mapping)):
        print(f"\n• Downloading [{idx+1}/4] {label} -> {target_name}...", flush=True)
        try:
            # Click card on canvas
            page.mouse.click(coord[0], coord[1])
            page.wait_for_timeout(2500)

            # Look for download button
            dl_btn = page.locator('button:has-text("download"), button:has-text("Download"), button[aria-label*="Download" i]').first
            if dl_btn.is_visible(timeout=3000):
                target_file = clips_dir / target_name
                with page.expect_download(timeout=20000) as dl_info:
                    dl_btn.click()
                dl = dl_info.value
                dl.save_as(str(target_file))
                print(f"  ✅ Saved: {target_file} ({target_file.stat().st_size // 1024} KB)")

            # Return back with Done button
            done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
            if done_btn.is_visible(timeout=2000):
                done_btn.click(force=True)
                page.wait_for_timeout(2000)
        except Exception as err:
            print(f"  ⚠️ Card [{idx+1}] note: {err}")

    # Now queue the final scenes (Scene 5 & Scene 6)
    print("\n[3/3] Queuing final remaining scenes (Scene 5 & Scene 6)...", flush=True)
    try:
        chat_in = page.locator('[contenteditable="true"]').first
        if chat_in.is_visible(timeout=3000):
            chat_in.click()
            final_prompt = "Generate cinematic 9:16 vertical videos for:\n[Scene 5: Frozen Dark Wasteland vs Scorched Desert]\nSplit planetary perspective, scorched dunes contrasted with frozen blue blizzard storms.\n\n[Scene 6: The Twilight Ribbon Payoff]\nSolitary silhouette on cliff edge looking out at glowing golden twilight horizon between day and night."
            page.keyboard.type(final_prompt, delay=5)
            page.wait_for_timeout(500)
            send_btn = page.locator('button:has-text("arrow_forward"), button[aria-label*="Send" i]').first
            if send_btn.is_visible(timeout=2000):
                send_btn.click()
            else:
                page.keyboard.press("Enter")

            # Auto approve
            for _ in range(5):
                page.wait_for_timeout(2000)
                app = page.locator('text="Approve, do not ask again", text="Approve"').last
                if app.is_visible(timeout=1000):
                    app.click(force=True)
                    print("  ✓ Approved Scene 5 & 6 generation.")
                    break
    except Exception as e:
        print(f"Final queue notice: {e}")

    context.close()

print("\n" + "="*60, flush=True)
print("📥 Downloads completed! Now checking clip inventory...", flush=True)
