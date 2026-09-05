import sys
from pathlib import Path
import time
from playwright.sync_api import sync_playwright

p = Path("browser/google_flow_profile").resolve()

print("Launching Chrome to verify Gemini sign-in...")
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
    
    # Check for top-right Sign in button
    signin_link = page.query_selector('header a[href*="accounts.google.com"], a:has-text("Sign in")')
    print("Found header Sign in button:", signin_link is not None)
    if signin_link:
        print("Clicking Sign in...")
        signin_link.click()
        page.wait_for_timeout(5000)
        print("Current URL after click:", page.url)
        page.screenshot(path="whop-editor/data/analysis/signin_flow_page.png")
        
    # Wait a bit to observe
    page.wait_for_timeout(5000)
    ctx.close()
