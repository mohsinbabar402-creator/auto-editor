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

    prompt = (
        "Create a 5-second cinematic video: "
        "Photorealistic live-action anime adaptation of Naruto Uzumaki crouched in pouring rain charging spinning cyan-gold Rasengan, "
        "dramatic camera push-in looking into camera with glowing orange Nine-Tails fox slit eyes."
    )

    inp = page.locator('div[role="textbox"]').first
    inp.click()
    page.wait_for_timeout(300)

    # Focus and type space to wake up state, then insert text and space
    page.keyboard.type(" ", delay=10)
    page.evaluate('''(text) => {
        const el = document.querySelector('div[role="textbox"]');
        if (el) {
            el.focus();
            document.execCommand('insertText', false, text);
        }
    }''', prompt)
    page.wait_for_timeout(500)
    page.keyboard.press("Space")
    page.wait_for_timeout(500)

    # Check submit button
    page.screenshot(path="before_enter.png")
    page.keyboard.press("Enter")
    page.wait_for_timeout(2000)

    # Also try clicking submit button if enabled
    try:
        page.mouse.click(955, 920)
    except: pass

    page.wait_for_timeout(4000)
    page.screenshot(path="after_enter_submitted.png")
    print("Saved after_enter_submitted.png")

    ctx.close()
