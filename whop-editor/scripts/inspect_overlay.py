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
    page.wait_for_timeout(5000)

    page.screenshot(path="whop-editor/data/analysis/overlay_check.png")

    overlays = page.query_selector_all(".cdk-overlay-container *")
    print(f"Overlay elements: {len(overlays)}")
    
    buttons = page.query_selector_all(".cdk-overlay-container button, button")
    for b in buttons:
        if b.is_visible():
            aria = (b.get_attribute("aria-label") or "").strip()
            txt = (b.inner_text() or "").strip().replace('\n', ' ')
            print(f"  Visible Button: text='{txt}', aria='{aria}'")

    ctx.close()
