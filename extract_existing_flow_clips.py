import sys, os, json, time, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from playwright.sync_api import sync_playwright

proj_url = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"
clips_dir = config.PROJECTS_DIR / "earth_stops_rotating" / "clips"
clips_dir.mkdir(parents=True, exist_ok=True)

print("Starting browser session to inspect Google Flow project...", flush=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1400, "height": 900},
        accept_downloads=True
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    collected_videos = {}

    def handle_response(response):
        url = response.url
        if "flow-content.google/video" in url:
            vid_id = url.split("/video/")[1].split("?")[0]
            if vid_id not in collected_videos:
                collected_videos[vid_id] = url
                print(f"Captured video URL [{vid_id}]: {url[:80]}...", flush=True)

    page.on("response", handle_response)

    print(f"Navigating to: {proj_url}", flush=True)
    page.goto(proj_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    screenshot_path = clips_dir / "flow_project_loaded.png"
    page.screenshot(path=str(screenshot_path))
    print(f"Project screenshot saved to: {screenshot_path.name}", flush=True)

    cards = page.locator('img[src*="googleusercontent"]')
    card_count = cards.count()
    print(f"Found {card_count} image cards on the project board.", flush=True)

    for i in range(card_count):
        try:
            card = cards.nth(i)
            print(f"Clicking card #{i+1}...", flush=True)
            card.click(force=True)
            page.wait_for_timeout(3000)
            
            page.evaluate("document.querySelector('video')?.play()")
            page.wait_for_timeout(2000)

            close_btn = page.locator('button[aria-label="Close"], button:has-text("Close")')
            if close_btn.count() > 0:
                close_btn.first.click(force=True)
                page.wait_for_timeout(1000)
            else:
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
        except Exception as e:
            print(f"Error interacting with card #{i+1}: {e}", flush=True)

    cookies = ctx.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

    ctx.close()

print(f"\nTotal video URLs captured from Flow: {len(collected_videos)}", flush=True)
with open(clips_dir / "captured_flow_videos.json", "w", encoding="utf-8") as f:
    json.dump({"videos": collected_videos, "cookie_str": cookie_str}, f, indent=2)
