from pathlib import Path
from playwright.sync_api import sync_playwright

p = Path("browser/google_flow_profile")
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(p.resolve()),
        channel="chrome",
        headless=True,
        args=["--headless=new", "--disable-blink-features=AutomationControlled"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://gemini.google.com/app", timeout=25000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Find and click Sign in
    signin_btn = page.query_selector('a:has-text("Sign in"), button:has-text("Sign in")')
    print("Sign in element found:", signin_btn is not None)
    if signin_btn:
        signin_btn.click()
        page.wait_for_timeout(4000)
        print("Page URL after clicking Sign in:", page.url)
        page.screenshot(path="whop-editor/data/analysis/after_signin_click.png")
    ctx.close()
