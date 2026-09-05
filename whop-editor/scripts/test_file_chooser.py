from pathlib import Path
from playwright.sync_api import sync_playwright

p = Path("browser/flow_profile_2").resolve()
vid = Path("whop-editor/data/output/controlled_test_short.mp4").resolve()

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

    area = page.query_selector('rich-textarea [contenteditable="true"], [contenteditable="true"]')
    if area:
        area.click()
        page.wait_for_timeout(1000)

    plus_btn = page.query_selector('button[aria-label*="Add files" i], button[aria-label*="Upload" i]')
    if plus_btn:
        print("Clicking plus button...")
        plus_btn.click()
        page.wait_for_timeout(2000)

    upload_btn = page.query_selector('button:has-text("Upload files"), [aria-label*="Upload files" i]')
    print("Found upload_btn:", upload_btn is not None)
    if upload_btn:
        try:
            with page.expect_file_chooser(timeout=8000) as fc_info:
                upload_btn.click()
            fc_info.value.set_files(str(vid))
            print("File set via file chooser!")
        except Exception as e:
            print("File chooser error:", e)

    page.wait_for_timeout(6000)
    page.screenshot(path="whop-editor/data/analysis/test_file_chooser_result.png")
    ctx.close()
