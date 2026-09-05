import logging
from pathlib import Path
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

p_dir = Path("browser/flow_profile_1").resolve()
for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
    f = p_dir / lk
    if f.exists():
        try:
            f.unlink()
        except Exception:
            pass

print("Opening flow_profile_1 to https://gemini.google.com/app ...")
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        channel="chrome",
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://gemini.google.com/app", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Check if there is a 'Sign in' button
    signin_btn = page.query_selector('a:has-text("Sign in"), button:has-text("Sign in")')
    if signin_btn:
        print("Found 'Sign in' button on Gemini. Clicking to see if Google SSO auto-authenticates...")
        signin_btn.click()
        page.wait_for_timeout(6000)

    # Check state after click
    body = page.inner_text("body")
    avatar = page.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
    print(f"Current URL: {page.url}")
    if avatar and "Sign in" not in body:
        print(f"[✓] SUCCESS: Gemini auto-authenticated with existing Google session!")
        print(f"Avatar: {avatar.get_attribute('aria-label')}")
    else:
        print(f"[-] Needs manual login: URL={page.url}")

    ctx.close()
