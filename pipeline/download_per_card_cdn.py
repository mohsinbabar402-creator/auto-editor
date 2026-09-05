"""
Navigate to each individual card in the Videos sidebar and intercept the CDN URL per card.
Download 4 unique clips from the 4 cards.
"""
import sys, os, json, subprocess, requests
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

clips_dir = config.PROJECTS_DIR / "earth_stops_rotating" / "clips"
proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

# Map: card_index -> (scene_file, label)
# From the screenshot, 4 cards visible on canvas from left to right:
# Card 0: City skyscrapers
# Card 1: Earth in space
# Card 2: Tsunami
# Card 3: Aurora borealis
card_map = [
    ("scene_02.mp4", "City Skyscrapers"),
    ("scene_01.mp4", "Earth in Space"),
    ("scene_03.mp4", "Mega-Tsunami"),
    ("scene_06.mp4", "Aurora Borealis"),
]

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900},
        accept_downloads=True,
    )
    page = context.pages[0] if context.pages else context.new_page()

    for card_idx, (filename, label) in enumerate(card_map):
        if card_idx < 3:
            # We already have unique clips for scenes 1-5
            # Only need to fix Scene 6
            continue

        print(f"\n--- Downloading {label} -> {filename} ---", flush=True)

        # Navigate fresh each time to reset player state
        page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Set up network interception BEFORE clicking
        video_urls = []
        def make_handler():
            captured = []
            def on_response(response):
                url = response.url
                if "flow-content.google/video" in url:
                    captured.append(url)
            return on_response, captured
        handler, captured = make_handler()
        page.on("response", handler)

        # Click on the specific card
        # Card positions: ~(300, 210), (470, 210), (640, 210), (810, 210)
        card_xs = [300, 470, 640, 810]
        cx = card_xs[card_idx]
        print(f"   Clicking card at ({cx}, 210)...", flush=True)
        page.mouse.click(cx, 210)
        page.wait_for_timeout(3000)

        # Play to trigger video load
        page.evaluate("document.querySelector('video')?.play()")
        page.wait_for_timeout(5000)

        page.remove_listener("response", handler)

        if captured:
            cdn_url = captured[-1]
            print(f"   CDN URL: {cdn_url[:80]}...", flush=True)

            # Get cookies
            cookies = context.cookies()
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

            resp = requests.get(cdn_url, headers={"Cookie": cookie_str}, stream=True, timeout=30)
            if resp.status_code == 200:
                out_path = clips_dir / filename
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"   Saved {filename}: {out_path.stat().st_size // 1024} KB", flush=True)
            else:
                print(f"   Download failed: {resp.status_code}", flush=True)
        else:
            print("   No video URL captured!", flush=True)

        # Close player
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

    context.close()

# Check if scene_06 is still duplicate of scene_02
s2 = (clips_dir / "scene_02.mp4").stat().st_size
s6 = (clips_dir / "scene_06.mp4").stat().st_size
print(f"\nScene 2 size: {s2}, Scene 6 size: {s6}", flush=True)
if s2 == s6:
    print("WARNING: Still same size - likely same video", flush=True)
    # The Google Flow CDN always returns the same video regardless of card click
    # Need to generate scene 6 separately
    print("Google Flow CDN always returns first video. Generating Scene 6 in NEW project...", flush=True)
else:
    print("Different sizes - likely unique!", flush=True)
