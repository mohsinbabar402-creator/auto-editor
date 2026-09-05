import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

p = Path("browser/flow_profile_1")
test_video = Path("whop-editor/data/input/justin_clouted_whop_12s.mp4").resolve()

print(f"Testing file chooser upload on {p.name} with {test_video.name}...")

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(p.resolve()),
        channel="chrome",
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900}
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://gemini.google.com/app", timeout=30000, wait_until="domcontentloaded")
    
    # 1. Wait for upload button
    page.wait_for_selector('button[aria-label*="Upload" i], button[aria-label*="tools" i]', timeout=25000)
    upload_btn = page.query_selector('button[aria-label*="Upload" i], button[aria-label*="tools" i]')
    print("Found upload button:", upload_btn is not None)
    upload_btn.click()
    page.wait_for_timeout(1500)
    
    # 2. Click 'Upload files' with file chooser
    menu_item = page.query_selector('[role="menuitem"]:has-text("Upload files"), button:has-text("Upload files"), .mat-mdc-menu-item:has-text("Upload files")')
    print("Found 'Upload files' menu option:", menu_item is not None)
    
    if menu_item:
        with page.expect_file_chooser() as fc_info:
            menu_item.click()
        chooser = fc_info.value
        chooser.set_files(str(test_video))
        print("Set files via file chooser: SUCCESS!")
    else:
        file_input = page.query_selector('input[type="file"]')
        if file_input:
            file_input.set_input_files(str(test_video))
            print("Set files via direct input[type=file]: SUCCESS!")
            
    page.wait_for_timeout(6000)
    page.screenshot(path="whop-editor/data/analysis/upload_chooser_result.png")
    print("Screenshot saved to whop-editor/data/analysis/upload_chooser_result.png")
    ctx.close()
