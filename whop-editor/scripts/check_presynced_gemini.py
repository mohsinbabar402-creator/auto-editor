import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

profiles = ["flow_profile_2", "flow_profile_3", "flow_profile_5"]

for p_name in profiles:
    p_dir = Path("browser") / p_name
    print(f"Checking {p_name}...")
    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(p_dir.resolve()),
                channel="chrome",
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"]
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://gemini.google.com/app", timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            body = page.inner_text("body")
            has_sign_in = "Sign in" in body and ("Sign in to try" in body or "Sign in with Google" in body)
            avatar = page.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
            aria = avatar.get_attribute("aria-label") if avatar else None
            
            print(f"  [{p_name}] avatar={aria}, has_sign_in={has_sign_in}")
            ctx.close()
            if avatar and not has_sign_in:
                print(f"===> PRE-AUTHENTICATED ACTIVE GEMINI SESSION IN {p_name}: {aria}")
                break
        except Exception as e:
            print(f"  [{p_name}] error: {e}")
