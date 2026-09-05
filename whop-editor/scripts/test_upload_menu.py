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
    page.wait_for_timeout(3000)

    btn = page.query_selector('button[aria-label*="Upload & tools" i], button[aria-label*="Upload" i]')
    print('Upload button found:', btn is not None)
    if btn:
        print('Clicking upload button...')
        btn.click()
        page.wait_for_timeout(2000)
        
        # Check for menu items or file input
        file_inputs = page.query_selector_all('input[type="file"]')
        print('File inputs after click:', len(file_inputs))
        for fi in file_inputs:
            print('  File input name/accept:', fi.get_attribute('accept'))
            
        menu_items = page.query_selector_all('[role="menuitem"], .mat-mdc-menu-item, button')
        print('Menu items found:', len(menu_items))
        for mi in menu_items[:20]:
            txt = (mi.inner_text() or '').strip().replace('\n', ' ')
            if any(k in txt.lower() for k in ['upload', 'file', 'image', 'video', 'drive']):
                print(f'  Option: "{txt}"')
                
    ctx.close()
