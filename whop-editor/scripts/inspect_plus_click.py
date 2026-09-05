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

    plus_btn = page.query_selector('button[aria-label*="Upload & tools" i], button[aria-label*="Add files" i]')
    print("Found plus button:", plus_btn is not None)
    if plus_btn:
        print("Clicking plus button normal...")
        plus_btn.click()
        page.wait_for_timeout(2000)
    
    page.screenshot(path="whop-editor/data/analysis/inspect_plus_menu.png")

    menu_elements = page.query_selector_all('[role="menu"], [role="menuitem"], .mat-mdc-menu-panel, .mat-mdc-menu-item, input[type="file"]')
    print(f"Matched menu/input elements: {len(menu_elements)}")
    for m in menu_elements:
        tag = m.evaluate("e => e.tagName")
        txt = (m.inner_text() or "").replace("\n", " ")
        aria = m.get_attribute("aria-label") or ""
        print(f"  <{tag}> text='{txt}', aria='{aria}'")

    ctx.close()
