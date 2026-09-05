import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

profiles = [
    Path("browser/google_flow_profile"),
    Path("browser/whop_profile")
] + sorted([p for p in Path("browser").glob("flow_profile_*") if p.is_dir()])

for p in profiles:
    print(f"Testing {p.name}...")
    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(p.resolve()),
                channel="chrome",
                headless=True,
                args=["--headless=new", "--disable-blink-features=AutomationControlled"],
                timeout=10000
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://gemini.google.com/app", timeout=15000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            # Check for upload button
            btn = page.query_selector('button[aria-label*="Upload"]')
            if not btn:
                print(f"  {p.name}: No upload button found")
                ctx.close()
                continue
                
            btn.click()
            page.wait_for_timeout(1500)
            
            body = page.inner_text("body")
            needs_login = "Sign in to try" in body or "Sign in with Google" in body
            print(f"  {p.name}: needs_login={needs_login}")
            
            # Check if input[type=file] exists
            file_inputs = page.query_selector_all('input[type="file"]')
            print(f"  {p.name}: file inputs count={len(file_inputs)}")
            
            ctx.close()
            if not needs_login:
                print(f"===> SUCCESS! ACTIVE AUTHENTICATED GEMINI SESSION: {p.name}")
                break
        except Exception as e:
            print(f"  {p.name}: error {e}")
