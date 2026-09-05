from playwright.sync_api import sync_playwright
from pathlib import Path

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

    # Click on the input container
    inp = page.locator('div[role="textbox"]').first
    print("Clicking chat input...")
    inp.click()
    page.wait_for_timeout(500)

    prompt = "Create a 5-second cinematic video of Naruto charging his golden Rasengan in the rain with Kurama fox eyes"
    print("Typing prompt with keyboard.type...")
    page.keyboard.type(prompt, delay=20)
    page.wait_for_timeout(1000)

    page.screenshot(path="typed_prompt.png")
    print("Saved typed_prompt.png")

    # Check the send button
    btn = page.locator('button:has(i:has-text("arrow_forward"))').first
    if btn.is_visible(timeout=1000):
        print("Send button is visible! Enabled?:", btn.is_enabled())
        btn.click()
        print("Clicked send button!")
    else:
        print("Send button not found, pressing Enter...")
        page.keyboard.press("Enter")

    page.wait_for_timeout(4000)
    page.screenshot(path="after_send_click.png")
    print("Saved after_send_click.png")

    ctx.close()
