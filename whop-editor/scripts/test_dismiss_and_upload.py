import os
from pathlib import Path
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

p = Path("browser/flow_profile_2").resolve()
video_file = Path("whop-editor/data/output/whop_campaign_final_approved.mp4").resolve()

print(f"Profile: {p.name}")
print(f"Video: {video_file.name}")

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(p),
        channel="chrome",
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://gemini.google.com/app", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    # Dismiss 'Got it' popup if present
    got_it_btn = page.query_selector('button:has-text("Got it")')
    if got_it_btn and got_it_btn.is_visible():
        print("Dismissing 'Got it' dialog...")
        got_it_btn.click()
        page.wait_for_timeout(1500)

    # Click the '+' upload button on the pill
    plus_btn = page.query_selector('button[aria-label*="Upload & tools" i], button[aria-label*="Add files" i], button:has-text("+")')
    print("Found plus button:", plus_btn is not None)
    if plus_btn:
        plus_btn.click()
        page.wait_for_timeout(2000)

    page.screenshot(path="whop-editor/data/analysis/after_gotit_and_plus.png")
    
    # Check menu items
    menu_items = page.query_selector_all('[role="menuitem"], .mat-mdc-menu-item')
    print(f"Menu items count: {len(menu_items)}")
    for idx, mi in enumerate(menu_items):
        txt = (mi.inner_text() or "").strip().replace('\n', ' ')
        dis = mi.get_attribute("disabled") is not None or mi.get_attribute("aria-disabled") == "true"
        print(f"  Item #{idx}: '{txt}', disabled={dis}")

    # Check file inputs
    file_inputs = page.query_selector_all('input[type="file"]')
    print(f"File inputs: {len(file_inputs)}")
    for fi in file_inputs:
        print("  input[type=file] accept:", fi.get_attribute("accept"))

    ctx.close()
