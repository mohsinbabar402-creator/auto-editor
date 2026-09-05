from pathlib import Path
from playwright.sync_api import sync_playwright

profiles = sorted([p for p in Path('browser').glob('flow_profile_*') if p.is_dir()])
profiles.append(Path('browser/google_flow_profile'))

print(f'Checking {len(profiles)} browser profiles for active Gemini login...')

for p in profiles:
    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(p.resolve()),
                channel='chrome',
                headless=True,
                args=['--headless=new', '--disable-blink-features=AutomationControlled']
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto('https://gemini.google.com/app', timeout=15000, wait_until='networkidle')
            page.wait_for_timeout(2000)
            
            body_text = page.inner_text('body')
            has_sign_in = 'Sign in' in body_text and ('Sign in to try' in body_text or 'Sign in with Google' in body_text)
            
            # Check user avatar / account button
            user_elem = page.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
            account_label = user_elem.get_attribute('aria-label') if user_elem else None
            
            print(f'[{p.name}] account={account_label}, needs_sign_in={has_sign_in}')
            ctx.close()
            if account_label and not has_sign_in:
                print(f'===> FOUND ACTIVE GEMINI SESSION IN {p.name}: {account_label}')
                break
        except Exception as e:
            print(f'[{p.name}] error: {e}')
