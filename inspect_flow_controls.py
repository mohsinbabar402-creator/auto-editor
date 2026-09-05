import sys, os, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from playwright.sync_api import sync_playwright

project_url = "https://labs.google/fx/tools/flow/project/f6e13565-47a8-4f72-bb4a-36e497bfc34f"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1400, "height": 900}
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    page.goto(project_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    
    # Click the + button at bottom left of prompt bar
    plus_btn = page.locator('button[aria-label*="Create"], button:has-text("add_2"), div:has-text("+")').first
    if plus_btn.is_visible():
        plus_btn.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(config.PROJECTS_DIR / "plus_dropdown.png"))
        print("Clicked + button and took screenshot!")
        
    # Also inspect settings button (tune icon)
    tune_btn = page.locator('button:has-text("tune"), button[aria-label*="Settings"]').first
    if tune_btn.is_visible():
        tune_btn.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(config.PROJECTS_DIR / "tune_settings.png"))
        print("Clicked Settings button and took screenshot!")
        
    ctx.close()
