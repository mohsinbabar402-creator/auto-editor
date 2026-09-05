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

    inputs = page.query_selector_all('input[type="file"]')
    print("Found file inputs:", len(inputs))
    success = False
    for i, fi in enumerate(inputs):
        try:
            fi.set_input_files(str(vid))
            print(f"Input {i} accepted file!")
            success = True
            break
        except Exception as e:
            print(f"Input {i} failed: {e}")

    page.wait_for_timeout(5000)
    page.screenshot(path="whop-editor/data/analysis/test_file_input_result.png")
    ctx.close()
    print("Final result:", success)
