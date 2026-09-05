import sys, os, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from playwright.sync_api import sync_playwright

# Let us open the project and inspect the UI buttons
project_url = "https://labs.google/fx/tools/flow/project/f6e13565-47a8-4f72-bb4a-36e497bfc34f"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1400, "height": 900}
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    print("Navigating to project...", flush=True)
    page.goto(project_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    
    # Take screenshot of the project view
    screenshot_path = config.PROJECTS_DIR / "flow_editor_debug.png"
    page.screenshot(path=str(screenshot_path))
    print(f"Screenshot saved to: {screenshot_path}")
    
    # Inspect what buttons are visible
    btns = page.locator('button, div[role="button"], span').all()
    print("Listing visible button texts:")
    for b in btns:
        try:
            if b.is_visible():
                t = b.inner_text().strip().replace("\n", " ")
                if t and len(t) < 40:
                    print(f"   [{t}]")
        except:
            pass
            
    ctx.close()
