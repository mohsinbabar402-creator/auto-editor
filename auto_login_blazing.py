from playwright.sync_api import sync_playwright
from pathlib import Path

p_dir = Path("browser/flow_profile_4").resolve()
print("Checking Google Flow login on Profile 4 (Blazing Soul)...")

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
    print("Initial URL:", page.url)

    if "accountchooser" in page.url or "signin" in page.url:
        print("At account chooser. Looking for Blazing Soul...")
        # Check for blazing soul button
        blazing_btn = page.locator("text=blazingsoul451@gmail.com, text=Blazing soul").first
        if blazing_btn.is_visible(timeout=3000):
            print("Clicking Blazing Soul account button...")
            blazing_btn.click()
            page.wait_for_timeout(4000)
            print("New URL after click:", page.url)

    # Check for Continue or Next buttons
    for btn_text in ["Continue", "Next", "Allow"]:
        btn = page.locator(f"button:has-text('{btn_text}'), div[role='button']:has-text('{btn_text}')").first
        try:
            if btn.is_visible(timeout=2000):
                print(f"Clicking '{btn_text}'...")
                btn.click()
                page.wait_for_timeout(3000)
        except Exception:
            pass

    page.wait_for_timeout(3000)
    print("Final URL:", page.url)
    has_pro = page.locator("text=PRO").first.is_visible(timeout=3000)
    print("PRO Badge Active on Google Flow:", has_pro)
    ctx.close()
