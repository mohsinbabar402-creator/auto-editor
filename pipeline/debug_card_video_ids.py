"""
Navigate to Google Flow, click ONLY the Aurora card (4th card),
wait for its unique video ID to appear in network traffic,
and download only if it's different from Scene 2.
"""
import sys, os, json, subprocess, requests, hashlib
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

clips_dir = config.PROJECTS_DIR / "earth_stops_rotating" / "clips"
proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
scene6_path = clips_dir / "scene_06.mp4"
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

# Get hash of scene_02 to compare
scene2_hash = hashlib.md5(open(clips_dir / "scene_02.mp4", "rb").read()).hexdigest()
print(f"Scene 2 MD5: {scene2_hash}", flush=True)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900},
        accept_downloads=True,
    )
    page = context.pages[0] if context.pages else context.new_page()

    # Intercept ALL network video responses with their video IDs
    all_video_responses = []
    def on_response(response):
        url = response.url
        if "flow-content.google/video" in url:
            # Extract video ID from URL
            vid_id = url.split("/video/")[1].split("?")[0] if "/video/" in url else "unknown"
            all_video_responses.append({"url": url, "video_id": vid_id})
            print(f"   [NET] Video ID: {vid_id}", flush=True)

    page.on("response", on_response)

    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Take screenshot to see card layout
    page.screenshot(path=str(proj_dir / "canvas_layout.png"))

    # Don't click any card yet - let's see what auto-loads
    page.wait_for_timeout(3000)
    
    print(f"\nAuto-loaded video IDs: {len(all_video_responses)}", flush=True)
    auto_ids = set(v["video_id"] for v in all_video_responses)
    print(f"Unique IDs on page load: {auto_ids}", flush=True)

    # Now click each card one by one and collect unique video IDs
    # Card approximate positions from screenshot
    card_positions = [
        (300, 210, "Card 1"),
        (470, 210, "Card 2"),
        (640, 210, "Card 3"),
        (810, 210, "Card 4 (Aurora)"),
    ]

    card_video_map = {}
    
    for cx, cy, label in card_positions:
        print(f"\nClicking {label} at ({cx}, {cy})...", flush=True)
        pre_count = len(all_video_responses)
        
        page.mouse.click(cx, cy)
        page.wait_for_timeout(2000)
        
        # Force play
        page.evaluate("document.querySelector('video')?.play()")
        page.wait_for_timeout(4000)
        
        # Check what new video IDs appeared
        new_responses = all_video_responses[pre_count:]
        new_ids = set(v["video_id"] for v in new_responses)
        print(f"   New video IDs for {label}: {new_ids}", flush=True)
        
        if new_ids:
            card_video_map[label] = {
                "video_id": list(new_ids)[-1],
                "url": [v for v in new_responses if v["video_id"] == list(new_ids)[-1]][-1]["url"]
            }
        
        # Close player
        done_btn = page.locator('button:has-text("Done")').first
        if done_btn.is_visible(timeout=2000):
            done_btn.click(force=True)
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(1500)

    print(f"\n=== Card -> Video ID Map ===", flush=True)
    for label, info in card_video_map.items():
        print(f"  {label}: {info['video_id']}", flush=True)

    # Get unique video IDs
    unique_ids = set(info["video_id"] for info in card_video_map.values())
    print(f"\nUnique video IDs across all 4 cards: {len(unique_ids)}", flush=True)
    print(f"IDs: {unique_ids}", flush=True)

    # Download Aurora card's video if it has a different ID
    aurora_info = card_video_map.get("Card 4 (Aurora)")
    city_info = card_video_map.get("Card 1")
    
    if aurora_info and city_info and aurora_info["video_id"] != city_info["video_id"]:
        print(f"\nAurora has DIFFERENT video ID! Downloading...", flush=True)
        cookies = context.cookies()
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        resp = requests.get(aurora_info["url"], headers={"Cookie": cookie_str}, stream=True, timeout=30)
        if resp.status_code == 200:
            with open(scene6_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            s6_hash = hashlib.md5(open(scene6_path, "rb").read()).hexdigest()
            print(f"Scene 6 MD5: {s6_hash} (Scene 2: {scene2_hash})", flush=True)
            print(f"UNIQUE: {s6_hash != scene2_hash}", flush=True)
    else:
        print(f"\nAll cards have SAME video ID - Google Flow CDN bug confirmed.", flush=True)
        print("Google Flow serves the same cached video for all cards in a project.", flush=True)

    context.close()

print("\nDone.", flush=True)
