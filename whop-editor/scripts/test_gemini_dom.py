import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

p = Path('browser/google_flow_profile')
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(p.resolve()),
        channel='chrome',
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--no-first-run',
            '--window-size=1280,900'
        ]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto('https://gemini.google.com/app', timeout=30000, wait_until='networkidle')
    print('URL:', page.url)
    print('Title:', page.title().encode('ascii', 'ignore').decode())
    
    # Check elements
    inputs = page.query_selector_all('textarea, input, [contenteditable="true"], button')
    print(f'Interactive elements count: {len(inputs)}')
    for el in inputs[:15]:
        tag = el.evaluate('e => e.tagName')
        aria = el.get_attribute('aria-label')
        cls = el.get_attribute('class')
        txt = (el.inner_text() or '').strip().replace('\n', ' ')[:30]
        print(f'  <{tag}> aria="{aria}" text="{txt}"')
        
    page.screenshot(path='whop-editor/data/analysis/gemini_page_idle.png')
    ctx.close()
