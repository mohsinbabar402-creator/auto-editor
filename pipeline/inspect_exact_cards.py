"""
Inspect all videos in the project, take thumbnail previews, and map accurately to scene_01 through scene_06
"""
import sys, os, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"
PROJECT_URL = "https://labs.google/fx/tools/flow/project/9b78c938-72d2-4167-9edf-84dbc20ad57a"

print("="*60, flush=True)
print("🔍 INSPECTING PROJECT GALLERY AND MAPPING EXACT SCENES", flush=True)
print("="*60, flush=True)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
        viewport={'width': 1280, 'height': 900},
        accept_downloads=True
    )
    page = context.pages[0] if context.pages else context.new_page()

    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Screenshot the full canvas
    page.screenshot(path=str(proj_dir / "full_canvas_mapping.png"))
    print("Full canvas screenshot saved to full_canvas_mapping.png", flush=True)

    # List all video cards on canvas and their text/aria descriptions
    cards = page.locator('div:has(> button[aria-label*="Play" i]), div:has(> img[src*="googleusercontent"])').all()
    print(f"Found {len(cards)} card containers on canvas", flush=True)

    context.close()

print("Inspection done.", flush=True)
