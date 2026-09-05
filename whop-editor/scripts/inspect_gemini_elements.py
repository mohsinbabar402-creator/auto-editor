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
    page.goto('https://gemini.google.com/app', timeout=30000, wait_until='networkidle')
    page.wait_for_timeout(4000)
    
    tags = page.evaluate('''() => {
        const all = Array.from(document.querySelectorAll('*'));
        const custom = all.filter(el => el.tagName.includes('-')).map(el => el.tagName.toLowerCase());
        return Array.from(new Set(custom));
    }''')
    print('Custom tags in Gemini UI:', tags[:20])
    
    chat_input = page.query_selector('rich-textarea, .ql-editor, [role="textbox"], textarea')
    print('Chat input found:', chat_input is not None)
    if chat_input:
        print('Chat input tag:', chat_input.evaluate('e => e.tagName'))
        print('Chat input aria:', chat_input.get_attribute('aria-label'))

    file_inputs = page.query_selector_all('input[type="file"]')
    print('File inputs found:', len(file_inputs))

    # Look for add files / upload button
    upload_btns = page.query_selector_all('button[aria-label*="upload" i], button[aria-label*="file" i], button[aria-label*="add" i]')
    print('Potential upload buttons:', len(upload_btns))
    for b in upload_btns:
        print('  Upload btn aria:', b.get_attribute('aria-label'))

    ctx.close()
