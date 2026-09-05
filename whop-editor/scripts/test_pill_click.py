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

    # Click the center pill to focus/expand
    center_pill = page.query_selector('rich-textarea, .ql-editor, [contenteditable="true"], [role="textbox"], .input-area')
    if center_pill:
        print("Found center pill:", center_pill.evaluate("e => e.tagName"))
        center_pill.click()
    else:
        # Click by text
        el = page.get_by_text("Ask Gemini")
        print("Found text 'Ask Gemini'")
        el.click()

    page.wait_for_timeout(2000)
    page.screenshot(path="whop-editor/data/analysis/after_pill_focus.png")
    
    # Check all buttons now visible
    buttons = page.query_selector_all("button, [role='button']")
    print(f"Buttons count after focus: {len(buttons)}")
    for b in buttons:
        aria = (b.get_attribute("aria-label") or "").strip()
        txt = (b.inner_text() or "").strip().replace('\n', ' ')
        if aria or txt:
            print(f"  Button: aria='{aria}', text='{txt}'")

    # Check for file inputs
    file_inputs = page.query_selector_all('input[type="file"]')
    print(f"File inputs count after focus: {len(file_inputs)}")
    
    ctx.close()
