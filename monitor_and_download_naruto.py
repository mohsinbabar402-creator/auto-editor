from playwright.sync_api import sync_playwright
from pathlib import Path
import time

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_dir = Path("projects/08_naruto_vs_sasuke/real_videos")
dest_file = out_dir / "naruto_real_motion_video.mp4"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(proj_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)

    # Click on "Videos" tab on left
    print("Switching to Videos tab...")
    vid_tab = page.locator('button:has-text("Videos"), div:has-text("Videos")').first
    if vid_tab.is_visible(timeout=3000):
        vid_tab.click()
        page.wait_for_timeout(2000)

    sasuke_id = "8d6c01ad-499c-4ebe-97ea-dec4b70566b1"

    print("Checking for Naruto video (waiting up to 90s if still generating)...")
    naruto_url = None
    for i in range(20): # 100s
        media_list = page.evaluate('''() => {
            const list = [];
            document.querySelectorAll('video, [src*="getMediaUrlRedirect"]').forEach(el => {
                const s = el.src || el.currentSrc;
                if (s && s.includes('getMediaUrlRedirect')) list.push(s);
            });
            return list;
        }''')
        for u in media_list:
            if sasuke_id not in u:
                naruto_url = u
                break
        if naruto_url:
            print(f"Found Naruto video! URL: {naruto_url[:80]}...")
            break
        print(f"  Still rendering... ({ (i+1)*5 }s)")
        page.wait_for_timeout(5000)

    if naruto_url:
        if naruto_url.startswith('/'):
            naruto_url = "https://labs.google" + naruto_url
        print("Downloading Naruto video via Playwright request...")
        resp = page.request.get(naruto_url)
        if resp.status == 200:
            dest_file.write_bytes(resp.body())
            print(f"SUCCESS! Downloaded {dest_file.name} ({dest_file.stat().st_size} bytes)")
        else:
            print("Download failed status:", resp.status)
    else:
        print("Naruto video not detected yet.")
        page.screenshot(path="naruto_check_state.png")

    ctx.close()
