from pathlib import Path
from playwright.sync_api import sync_playwright

p = Path("browser/flow_profile_2").resolve()
print(f"Testing Gemini on {p.name}...")

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(p),
        channel="chrome",
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900}
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://gemini.google.com/app", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    
    print("URL:", page.url)
    user_btn = page.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
    account_label = user_btn.get_attribute("aria-label") if user_btn else None
    print("Account Label:", account_label)
    
    body = page.inner_text("body")
    needs_signin = "Sign in" in body and ("Sign in to try" in body or "Sign in with Google" in body)
    print("Needs signin:", needs_signin)
    
    # Check upload button
    upload_btn = page.query_selector('button[aria-label*="Upload & tools" i], button[aria-label*="Upload" i]')
    print("Upload button found:", upload_btn is not None)
    if upload_btn:
        upload_btn.click()
        page.wait_for_timeout(1500)
        menu_items = page.query_selector_all('[role="menuitem"], .mat-mdc-menu-item')
        print(f"Menu items count: {len(menu_items)}")
        for mi in menu_items:
            txt = mi.inner_text().strip().replace('\n', ' ')
            dis = mi.get_attribute("disabled") is not None or mi.get_attribute("aria-disabled") == "true"
            print(f"  Item: '{txt}', disabled={dis}")
            
    page.screenshot(path="whop-editor/data/analysis/flow2_gemini_test.png")
    ctx.close()
