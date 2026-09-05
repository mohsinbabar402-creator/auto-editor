"""
Extract the actual video source URL from Google Flow player and download directly.
"""
import sys, os
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

clips_dir = config.PROJECTS_DIR / "earth_stops_rotating" / "clips"
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900},
        accept_downloads=True,
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Click Card 4 (Aurora) at (650, 250)
    print("Clicking Aurora card...", flush=True)
    page.mouse.click(650, 250)
    page.wait_for_timeout(3000)

    # Extract all video source URLs from the page
    video_srcs = page.evaluate("""
        () => {
            const videos = document.querySelectorAll('video');
            const srcs = [];
            videos.forEach(v => {
                if (v.src) srcs.push(v.src);
                const sources = v.querySelectorAll('source');
                sources.forEach(s => { if (s.src) srcs.push(s.src); });
            });
            return srcs;
        }
    """)
    print(f"Found {len(video_srcs)} video source URLs:", flush=True)
    for s in video_srcs:
        print(f"  {s[:120]}", flush=True)

    # Also check for blob URLs and try to get the actual media URL
    blob_urls = page.evaluate("""
        () => {
            const videos = document.querySelectorAll('video');
            const info = [];
            videos.forEach((v, i) => {
                info.push({
                    index: i,
                    src: v.src,
                    currentSrc: v.currentSrc,
                    readyState: v.readyState,
                    duration: v.duration,
                    width: v.videoWidth,
                    height: v.videoHeight,
                });
            });
            return info;
        }
    """)
    print("\nVideo element details:", flush=True)
    for b in blob_urls:
        print(f"  #{b['index']}: src={b['src'][:100]}, {b['width']}x{b['height']}, dur={b['duration']}", flush=True)

    # Try to intercept network requests for video
    print("\nListening for video network requests...", flush=True)
    video_urls = []

    def on_response(response):
        ct = response.headers.get("content-type", "")
        if "video" in ct or response.url.endswith(".mp4"):
            video_urls.append(response.url)
            print(f"  VIDEO RESPONSE: {response.url[:120]}", flush=True)

    page.on("response", on_response)

    # Click play to trigger network fetch
    page.mouse.click(640, 400)
    page.wait_for_timeout(5000)

    # Try seeking to force load
    page.evaluate("document.querySelector('video')?.play()")
    page.wait_for_timeout(3000)

    print(f"\nCaptured {len(video_urls)} video URLs", flush=True)

    context.close()

print("Done inspecting.", flush=True)
