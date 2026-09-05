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

    downloaded_files = []
    def on_response(res):
        u = res.url
        ct = res.headers.get("content-type", "")
        if ("video" in ct or ".mp4" in u) and ("google" in u or "flow" in u):
            print(f"\n[REAL VIDEO DETECTED]: {u[:100]}...")
            dest = out_dir / f"veo_video_{len(downloaded_files)+1}.mp4"
            try:
                # Use page.request to download with cookies
                body = page.request.get(u).body()
                dest.write_bytes(body)
                print(f"[SUCCESS] Downloaded real AI video to {dest.name} ({dest.stat().st_size} bytes)")
                downloaded_files.append(dest)
            except Exception as e:
                print(f"Download error: {e}")
    page.on("response", on_response)

    page.goto(proj_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)

    # Click "Approve, do not ask again" using text locator or coordinate click
    print("Finding 'Approve, do not ask again'...")
    target = page.locator('text="Approve, do not ask again"').first
    if target.is_visible(timeout=5000):
        print("Clicking 'Approve, do not ask again' via locator...")
        target.click()
    else:
        print("Clicking via coordinates (850, 715)...")
        page.mouse.click(850, 715)

    page.wait_for_timeout(3000)
    page.screenshot(path="after_approve_click.png")
    print("Screenshot saved to after_approve_click.png")

    # Monitor generation
    print("Monitoring Veo video rendering (up to 3 minutes)...")
    for i in range(30):
        page.wait_for_timeout(6000)
        print(f"  Rendering... ({ (i+1)*6 }s) - downloaded: {len(downloaded_files)}")
        if downloaded_files:
            print("Real video downloaded successfully!")
            break

    page.screenshot(path="after_render_wait.png")
    ctx.close()
