"""
List all project cards on Google Flow home page and inspect their thumbnails
"""
import sys, os, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
        viewport={'width': 1280, 'height': 900},
        accept_downloads=True
    )
    page = context.pages[0] if context.pages else context.new_page()

    page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Scroll down to see all project cards
    page.mouse.wheel(0, 500)
    page.wait_for_timeout(2000)

    page.screenshot(path=str(proj_dir / "all_home_projects.png"), full_page=True)
    print("Screenshot saved to all_home_projects.png", flush=True)

    links = page.locator('a[href*="/project/"]').all()
    print(f"Found {len(links)} project links on Home:", flush=True)
    for i, l in enumerate(links):
        try:
            href = l.get_attribute('href') or ''
            text = l.inner_text().replace('\n', ' ')
            print(f"  [{i}] href={href} text='{text}'", flush=True)
        except: pass

    context.close()

print("Home inspection complete.", flush=True)
