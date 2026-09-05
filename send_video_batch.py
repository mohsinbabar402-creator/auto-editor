from playwright.sync_api import sync_playwright
from pathlib import Path
import time

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(proj_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    # Click directly on the input box
    print("Clicking chat input at (850, 920)...")
    page.mouse.click(850, 920)
    page.wait_for_timeout(500)

    prompt = (
        "Create two 5-second cinematic 9:16 videos: "
        "1. Photorealistic live-action Naruto Uzumaki crouched in pouring rain charging spinning cyan-gold Rasengan, "
        "dramatic camera push-in looking into camera with glowing orange Nine-Tails fox slit eyes. "
        "2. Mid-air slow-motion collision of Naruto and Sasuke over waterfall, Rasengan clashing into Chidori with massive explosion."
    )

    page.keyboard.type(prompt, delay=5)
    page.wait_for_timeout(1000)
    page.keyboard.press("Enter")
    print("Prompt typed and Enter pressed!")

    page.wait_for_timeout(4000)
    page.screenshot(path="batch_videos_submitted.png")
    print("Saved batch_videos_submitted.png")

    ctx.close()
