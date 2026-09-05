from playwright.sync_api import sync_playwright
from pathlib import Path

# Test Profile 17 directly from your real Chrome installation!
chrome_user_data = Path(r"C:\Users\ice\AppData\Local\Google\Chrome\User Data")
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(chrome_user_data),
        headless=True,
        channel="chrome",
        args=["--profile-directory=Profile 17", "--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    print("Profile 17 (Blazing Soul) URL:", page.url)
    has_pro = page.locator('text="PRO"').first.is_visible(timeout=3000)
    print("Profile 17 PRO Active:", has_pro)
    ctx.close()
