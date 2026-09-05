"""Debug: Navigate through Flow UI with proper waits."""
import sys, os, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright
from pathlib import Path

PROFILE_DIR = Path(r'C:\Users\ice\Desktop\youtube shorts project\browser\google_flow_profile')
BASE = r'C:\Users\ice\Desktop\youtube shorts project'

print('Launching browser...', flush=True)
p = sync_playwright().start()
context = p.chromium.launch_persistent_context(
    user_data_dir=str(PROFILE_DIR),
    headless=False,
    args=['--disable-blink-features=AutomationControlled','--no-first-run'],
    viewport={'width': 1280, 'height': 900},
    accept_downloads=True
)
page = context.pages[0] if context.pages else context.new_page()

# Step 1: Go to Flow
print('Step 1: Navigating...', flush=True)
page.goto('https://labs.google/fx/tools/flow', wait_until='domcontentloaded', timeout=60000)
page.wait_for_timeout(5000)

# Step 2: Click "New project"
print('Step 2: Clicking New project...', flush=True)
new_proj = page.locator('button:has-text("New project"), a:has-text("New project")').first
new_proj.click()

# Step 3: Wait for project to load (up to 20 seconds)
print('Step 3: Waiting for project editor to load...', flush=True)
page.wait_for_timeout(15000)

print(f'  URL: {page.url}', flush=True)
print(f'  Title: {page.title()}', flush=True)
page.screenshot(path=os.path.join(BASE, 'debug_loaded.png'))
print('  Screenshot: debug_loaded.png', flush=True)

# Dump full page structure
print('Step 4: Scanning page elements...', flush=True)

# Check for iframes
iframes = page.frames
print(f'  Total frames: {len(iframes)}', flush=True)
for i, frame in enumerate(iframes):
    print(f'  Frame [{i}]: name="{frame.name}" url="{frame.url[:100]}"', flush=True)

# Check all elements in all frames
for fi, frame in enumerate(iframes):
    print(f'\n  --- Frame {fi} ({frame.url[:60]}) ---', flush=True)
    
    # Inputs
    inputs = frame.locator('textarea, input[type="text"], [contenteditable="true"]').all()
    for i, el in enumerate(inputs):
        try:
            tag = el.evaluate('e => e.tagName')
            placeholder = el.get_attribute('placeholder') or ''
            visible = el.is_visible()
            print(f'    Input [{i}] <{tag}> placeholder="{placeholder}" visible={visible}', flush=True)
        except: pass
    
    # Buttons
    buttons = frame.locator('button').all()
    visible_buttons = []
    for btn in buttons:
        try:
            if btn.is_visible():
                text = btn.inner_text()[:60].replace('\n', ' ').strip()
                if text:
                    visible_buttons.append(text)
        except: pass
    if visible_buttons:
        print(f'    Visible buttons: {visible_buttons[:20]}', flush=True)
    
    # Links
    links = frame.locator('a').all()
    visible_links = []
    for link in links:
        try:
            if link.is_visible():
                text = link.inner_text()[:60].replace('\n', ' ').strip()
                href = link.get_attribute('href') or ''
                if text:
                    visible_links.append(f'{text} -> {href[:50]}')
        except: pass
    if visible_links:
        print(f'    Visible links: {visible_links[:20]}', flush=True)

    # Anything with "video" text
    video_els = frame.locator('*:has-text("video"), *:has-text("Video")').all()
    video_texts = []
    for el in video_els[:10]:
        try:
            if el.is_visible():
                tag = el.evaluate('e => e.tagName')
                text = el.inner_text()[:40].replace('\n', ' ').strip()
                video_texts.append(f'<{tag}> "{text}"')
        except: pass
    if video_texts:
        print(f'    Video-related: {video_texts[:10]}', flush=True)

context.close()
p.stop()
print('\nDone!', flush=True)
