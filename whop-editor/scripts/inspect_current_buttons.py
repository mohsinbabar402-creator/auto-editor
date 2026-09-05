from pathlib import Path
from playwright.sync_api import sync_playwright

p = Path('browser/google_flow_profile')
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(p.resolve()),
        channel='chrome',
        headless=True,
        args=['--headless=new', '--disable-blink-features=AutomationControlled']
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto('https://gemini.google.com/app', timeout=30000, wait_until='domcontentloaded')
    page.wait_for_timeout(4000)
    
    buttons = page.query_selector_all('button, [role="button"]')
    print(f"Total buttons found: {len(buttons)}")
    for b in buttons:
        aria = b.get_attribute('aria-label') or ''
        txt = (b.inner_text() or '').strip().replace('\n', ' ')
        if aria or txt:
            print(f"  Button: aria='{aria}', text='{txt}'")
    page.screenshot(path='whop-editor/data/analysis/gemini_current_ui.png')
    ctx.close()
