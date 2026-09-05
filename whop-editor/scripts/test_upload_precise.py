import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

p = Path("browser/flow_profile_2").resolve()
vid = Path("whop-editor/data/output/version_1.mp4").resolve()

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(p),
        channel="chrome",
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://gemini.google.com/app", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    # Find the button specifically
    btn = page.query_selector('button[aria-label*="Upload" i], button[aria-label*="tools" i]')
    print("Found button:", btn is not None, "aria:", btn.get_attribute("aria-label") if btn else None)
    if btn:
        btn.click()
        page.wait_for_timeout(2000)

    # Check for Upload files menuitem
    upload_item = page.locator('button:has-text("Upload files"), [role="menuitem"]:has-text("Upload files"), [aria-label*="Upload files" i]').first
    print("Upload item visible:", upload_item.is_visible())
    if upload_item.is_visible():
        with page.expect_file_chooser(timeout=8000) as fc_info:
            upload_item.click()
        fc_info.value.set_files(str(vid))
        print("SUCCESS: Attached video!")
        page.wait_for_timeout(5000)

    page.screenshot(path="whop-editor/data/analysis/test_upload_working.png")
    ctx.close()
