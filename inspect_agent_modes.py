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
    
    # Click the Agent button in the prompt bar
    agent_pill = page.locator('button:has-text("Agent"), div:has-text("Agent")').first
    if agent_pill.is_visible():
        agent_pill.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(config.PROJECTS_DIR / "agent_pill_menu.png"))
        print("Clicked Agent pill button!")
        
    # Also click Tools on the left sidebar
    tools_tab = page.locator('button:has-text("Tools"), div:has-text("Tools")').first
    if tools_tab.is_visible():
        tools_tab.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(config.PROJECTS_DIR / "tools_sidebar.png"))
        print("Clicked Tools sidebar!")
        
    ctx.close()
