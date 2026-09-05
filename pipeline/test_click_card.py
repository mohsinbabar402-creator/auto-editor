"""
Interact with canvas video card to open video player modal and download
"""
import sys, os, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
        viewport={'width': 1280, 'height': 900},
        accept_downloads=True
    )
    page = context.pages[0] if context.pages else context.new_page()

    page.goto("https://labs.google/fx/tools/flow/project/2ba51534-92bc-447e-bc77-9d6d33c40f16", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    # Click on the canvas video card directly at coordinate (270, 300)
    print("Clicking video card on canvas...", flush=True)
    page.mouse.click(270, 300)
    page.wait_for_timeout(3000)

    # Take screenshot of open player
    page.screenshot(path=str(proj_dir / "card_clicked_state.png"))
    print("Screenshot saved: card_clicked_state.png", flush=True)

    # Check for all buttons now visible
    buttons = page.locator('button').all()
    print(f"Total buttons after click: {len(buttons)}", flush=True)
    for i, btn in enumerate(buttons):
        try:
            if btn.is_visible():
                t = btn.inner_text().strip().replace('\n', ' ')
                aria = btn.get_attribute('aria-label') or ''
                tooltip = btn.get_attribute('data-tooltip') or ''
                print(f"  Btn [{i}]: text='{t}' aria='{aria}' tooltip='{tooltip}'", flush=True)
        except: pass

    # Check if a <video> element now exists
    vids = page.locator('video').all()
    print(f"Video elements found: {len(vids)}", flush=True)
    for i, v in enumerate(vids):
        try:
            src = v.get_attribute('src') or ''
            print(f"  Video [{i}] src={src[:80]}", flush=True)
        except: pass

    context.close()

print("Inspection complete.", flush=True)
