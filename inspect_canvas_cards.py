from playwright.sync_api import sync_playwright
from pathlib import Path

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()

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

    # Click "All Media" to see everything
    all_media = page.locator('button:has-text("All Media"), div:has-text("All Media")').first
    if all_media.is_visible(timeout=3000):
        all_media.click()
        page.wait_for_timeout(2000)

    cards_info = page.evaluate('''() => {
        const list = [];
        document.querySelectorAll('img, video').forEach(el => {
            list.push({
                tag: el.tagName,
                src: el.src || el.currentSrc,
                aria: el.getAttribute('aria-label') || el.getAttribute('alt') || ''
            });
        });
        return list;
    }''')
    print("Found media on canvas:", len(cards_info))
    for c in cards_info:
        print(" ", c)

    page.screenshot(path="all_media_view.png")
    ctx.close()
