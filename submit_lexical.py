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
    print("Clicking input...")
    inp.click()
    page.wait_for_timeout(300)

    # Use execCommand to insert text cleanly into Lexical editor
    page.evaluate('''(text) => {
        const el = document.querySelector('div[role="textbox"]');
        if (el) {
            el.focus();
            document.execCommand('insertText', false, text);
        }
    }''', prompt)
    page.wait_for_timeout(1000)

    page.screenshot(path="after_insert_text.png")
    print("Screenshot saved to after_insert_text.png")

    # Click the send button
    print("Clicking submit button...")
    send_btn = page.locator('button:has(i:has-text("arrow_forward")), button[aria-label*="Submit"]').first
    if send_btn.is_visible(timeout=2000):
        send_btn.click()
        print("Submit button clicked via locator!")
    else:
        print("Pressing Enter...")
        page.keyboard.press("Enter")

    page.wait_for_timeout(4000)
    page.screenshot(path="after_submit_text.png")
    print("Saved after_submit_text.png")

    ctx.close()
