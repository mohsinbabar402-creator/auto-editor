from pathlib import Path
from playwright.sync_api import sync_playwright

p = Path("browser/flow_profile_2").resolve()

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
    page.screenshot(path="whop-editor/data/analysis/fresh_overlay_dialog.png")
    
    dialog = page.query_selector('.cdk-overlay-container [role="dialog"], .mat-mdc-dialog-container, [role="alertdialog"]')
    if dialog:
        print("Dialog found! Text:")
        print(dialog.inner_text())
        btns = dialog.query_selector_all("button")
        for b in btns:
            print("  Dialog button:", b.inner_text(), b.get_attribute("aria-label"))
    else:
        print("No dialog element matched with role=dialog.")
        # print all in overlay container
        container = page.query_selector('.cdk-overlay-container')
        if container:
            print("Overlay container text:")
            print(container.inner_text())
            btns = container.query_selector_all("button")
            for b in btns:
                print("  Overlay button:", b.inner_text(), b.get_attribute("aria-label"))
    ctx.close()
