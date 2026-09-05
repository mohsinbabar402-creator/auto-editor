from playwright.sync_api import sync_playwright
from pathlib import Path

p_dir = Path("browser/flow_profile_4").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    has_pro = page.locator('text="PRO"').first.is_visible(timeout=3000)
    print("Blazing Soul Profile 4 PRO Active:", has_pro)
    print("Page URL:", page.url)
    ctx.close()
