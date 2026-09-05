"""
Generate Scene 6 by creating a brand new Google Flow project from home page.
"""
import sys, os, json, subprocess, requests, hashlib, time
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"
scene6_path = clips_dir / "scene_06.mp4"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900},
        accept_downloads=True
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    captured_urls = []
    def on_resp(r):
        if "flow-content.google/video" in r.url:
            captured_urls.append(r.url)
            print(f"Captured video URL: {r.url[:80]}...", flush=True)
    page.on("response", on_resp)

    print("Opening Google Flow home...", flush=True)
    page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    # Take screenshot of home
    page.screenshot(path=str(proj_dir / "home_debug.png"))

    # Look for the new project / prompt input
    prompt_box = page.locator('textarea, [contenteditable="true"], input[type="text"]').first
    if prompt_box.is_visible(timeout=5000):
        print("Found prompt box on home page", flush=True)
        prompt_box.click()
    else:
        # Check for + button or New Project button
        new_proj_btn = page.locator('button:has-text("New"), button:has-text("+"), button[aria-label*="New"], button[aria-label*="Create"]').first
        if new_proj_btn.is_visible(timeout=3000):
            print("Clicking New Project button...", flush=True)
            new_proj_btn.click()
            page.wait_for_timeout(4000)
            prompt_box = page.locator('textarea, [contenteditable="true"]').first
            prompt_box.click()

    prompt_scene6 = (
        "Cinematic vertical 9:16 video: A lone human silhouette stands on a jagged cliff edge at twilight. "
        "Behind them, the sky is split in two halves: left is frozen dark blue with stars, right is fiery glowing amber. "
        "A sharp glowing golden twilight line separates them. "
        "8K National Geographic cinematic documentary, slow dramatic camera push."
    )

    print("Typing prompt...", flush=True)
    page.keyboard.type(prompt_scene6, delay=1)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    print("Pressed Enter. Waiting for project creation & approval...", flush=True)
    page.wait_for_timeout(5000)

    # Click Approve
    for attempt in range(10):
        approve = page.locator('button:has-text("Approve"), button:has-text("Generate"), button:has-text("Create")')
        if approve.count() > 0:
            approve.last.click(force=True)
            print(f"Approved on attempt {attempt+1}!", flush=True)
            break
        page.wait_for_timeout(2000)

    print(f"Current page URL: {page.url}", flush=True)

    # Wait for generation (poll every 10s)
    print("Waiting for new video to render...", flush=True)
    for i in range(20):
        page.wait_for_timeout(10000)
        if captured_urls:
            print(f"Video URL intercepted at {(i+1)*10}s!", flush=True)
            break
        # Also try clicking on the card if rendered
        cards = page.locator('img[src*="googleusercontent"]')
        if cards.count() > 0:
            print(f"Card visible at {(i+1)*10}s, clicking to trigger playback...", flush=True)
            cards.first.click(force=True)
            page.wait_for_timeout(2000)
            page.evaluate("document.querySelector('video')?.play()")
            page.wait_for_timeout(3000)
            if captured_urls:
                break
        print(f"  {(i+1)*10}s...", flush=True)

    cookies = ctx.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    ctx.close()

if captured_urls:
    target_url = captured_urls[-1]
    print(f"Downloading Scene 6 from: {target_url[:80]}...", flush=True)
    resp = requests.get(target_url, headers={"Cookie": cookie_str}, stream=True, timeout=60)
    if resp.status_code == 200:
        with open(scene6_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"SUCCESS: Saved Scene 6 ({scene6_path.stat().st_size // 1024} KB)", flush=True)
    else:
        print(f"Download error: {resp.status_code}", flush=True)
else:
    print("No video URL captured.", flush=True)
