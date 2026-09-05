from playwright.sync_api import sync_playwright
from pathlib import Path
import json

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
    page.goto(proj_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)

    # Click on "Videos" tab on the left sidebar
    print("Checking Videos tab...")
    vid_tab = page.locator('button:has-text("Videos"), div:has-text("Videos")').first
    if vid_tab.is_visible(timeout=3000):
        vid_tab.click()
        page.wait_for_timeout(2000)

    # Inspect all video elements or download links
    vids = page.evaluate('''() => {
        const list = [];
        document.querySelectorAll('video, a[href*=".mp4"], [src*=".mp4"], [src*="getMediaUrlRedirect"]').forEach(el => {
            const s = el.src || el.href || el.currentSrc;
            if (s) list.push({ tag: el.tagName, src: s });
        });
        return list;
    }''')
    print("Found media elements:", vids)

    # Take screenshot without waiting for fonts
    page.screenshot(path="veo_status_check.png", timeout=10000)
    print("Saved veo_status_check.png")

    ctx.close()
