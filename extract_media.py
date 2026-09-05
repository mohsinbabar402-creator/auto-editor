from playwright.sync_api import sync_playwright
from pathlib import Path
import json, urllib.request

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_dir = Path("projects/08_naruto_vs_sasuke/renders")
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

    # Find all media (img / video) on the page
    media_urls = page.evaluate('''() => {
        const results = [];
        document.querySelectorAll('img, video').forEach(el => {
            const src = el.currentSrc || el.src;
            if (src && !src.startsWith('data:image/svg')) {
                results.push({ tag: el.tagName, src: src });
            }
        });
        return results;
    }''')
    print("Found media on page:")
    for m in media_urls:
        print(f"  [{m['tag']}] {m['src'][:100]}...")

    # Download largest image/video
    for i, m in enumerate(media_urls):
        src = m['src']
        if "googleusercontent.com" in src or "flow" in src:
            ext = ".mp4" if m['tag'] == 'VIDEO' else ".png"
            dest = out_dir / f"sasuke_scene_asset_{i}{ext}"
            try:
                urllib.request.urlretrieve(src, str(dest))
                print(f"Downloaded asset {dest.name} ({dest.stat().st_size} bytes)")
            except Exception as e:
                print(f"Download failed: {e}")

    ctx.close()
