from playwright.sync_api import sync_playwright
from pathlib import Path
import time, urllib.request

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_dir = Path("projects/08_naruto_vs_sasuke/real_videos")
out_dir.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    captured_videos = []
    def on_response(res):
        u = res.url
        if "flow-content.google/video" in u or ("videofx" in u and ".mp4" in u) or "getMediaUrlRedirect" in u:
            ct = res.headers.get("content-type", "")
            if "video" in ct or ".mp4" in u:
                print(f"[CAPTURED VIDEO STREAM]: {u[:90]}...")
                captured_videos.append(u)
    page.on("response", on_response)

    page.goto(proj_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)

    # Click "Approve, do not ask again" button
    print("Clicking 'Approve, do not ask again' button...")
    approve_btn = page.locator('button:has-text("Approve, do not ask again"), button:has-text("Approve")').first
    if approve_btn.is_visible(timeout=5000):
        approve_btn.click()
        print("Approved! Video generation started.")
        page.wait_for_timeout(3000)
        page.screenshot(path="video_generation_in_progress.png")
    else:
        print("Approve button not found!")
        page.screenshot(path="approve_btn_missing.png")

    # Monitor generation (up to 3 minutes for video render)
    print("Waiting for video rendering to finish...")
    for i in range(30):
        page.wait_for_timeout(6000)
        print(f"  Rendering progress... ({ (i+1)*6 }s)")
        # Check if video tag appeared or video downloaded
        vids = page.locator('video').all()
        if vids:
            print(f"Found {len(vids)} video elements on page!")
            break

    page.screenshot(path="video_generation_completed.png")
    print("Screenshot saved to video_generation_completed.png")

    ctx.close()
