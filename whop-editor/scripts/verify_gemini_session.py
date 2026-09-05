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
    page.goto('https://gemini.google.com/app', timeout=20000, wait_until='domcontentloaded')
    page.wait_for_timeout(3000)
    
    upload_btn = page.query_selector('button[aria-label*="Upload" i], button[aria-label*="add" i]')
    text_box = page.query_selector('rich-textarea, .ql-editor, [role="textbox"]')
    user_avatar = page.query_selector('[aria-label*="Google Account" i]')
    
    print('Gemini URL:', page.url)
    print('Upload button found:', upload_btn is not None)
    if upload_btn:
        print('Upload button aria:', upload_btn.get_attribute('aria-label'))
    print('Text box found:', text_box is not None)
    print('User avatar found:', user_avatar is not None)
    
    page.screenshot(path='whop-editor/data/analysis/gemini_verified_session.png')
    ctx.close()
