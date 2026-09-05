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

    # Check all buttons inside or near input
    all_btns = page.query_selector_all("button, [role='button']")
    print(f"\nAll buttons count: {len(all_btns)}")
    for b in all_btns:
        if b.is_visible():
            aria = b.get_attribute("aria-label")
            txt = b.inner_text().strip().replace("\n", " ") if b.inner_text() else ""
            html = b.evaluate("e => e.outerHTML")[:150]
            print(f"  VISIBLE BTN: aria='{aria}' text='{txt}' html={html}")

    ctx.close()
