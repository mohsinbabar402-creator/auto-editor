import sys, os, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from playwright.sync_api import sync_playwright

proj_url = "https://labs.google/fx/tools/flow/project/3dac8aee-48c7-423c-ab8a-95e7f8e48d38"
prompt = "Generate video: 9:16 vertical cinematic video. High-altitude orbital view of supersonic hurricane cloud bands and atmospheric shockwaves wrapping tightly around the spinning globe with glowing red friction edges, National Geographic 8k photorealistic."

print("Opening Part 3 project to generate missing Scene 1...", flush=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1400, "height": 900}
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(proj_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    page.keyboard.press("Escape")
    page.wait_for_timeout(1000)

    chat_in = page.locator('[contenteditable="true"]').first
    if chat_in.is_visible(timeout=5000):
        chat_in.click(force=True)
        page.wait_for_timeout(300)
        page.keyboard.type(prompt, delay=1)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        print("Submitted Scene 1 prompt to Veo!", flush=True)
        page.wait_for_timeout(3000)

        for _ in range(4):
            btns = page.locator('button:has-text("Approve"), button:has-text("Create")').all()
            for b in btns:
                if b.is_visible():
                    b.click(force=True)
            page.wait_for_timeout(1000)

    page.wait_for_timeout(8000)
    ctx.close()
print("Done triggering Scene 1 generation!")
