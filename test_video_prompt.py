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
    page.goto(proj_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)

    # If inside a card view, click back arrow
    back_btn = page.locator('button:has(svg), button').filter(has_text="").first
    try:
        # Check if back arrow exists
        arrow = page.locator('header button, [aria-label*="Back"], button:has-text("arrow_back")').first
        if arrow.is_visible(timeout=1000):
            arrow.click()
            page.wait_for_timeout(2000)
    except: pass

    # Check the chat panel on the right
    inp = page.locator('[contenteditable="true"]').first
    if not inp.is_visible(timeout=3000):
        # Maybe click chat button or collapse
        chat_btn = page.locator('button[aria-label*="chat"], button:has-text("chat")').first
        if chat_btn.is_visible(timeout=1000):
            chat_btn.click()
            page.wait_for_timeout(2000)

    prompt = (
        "Generate a 5-second vertical 9:16 cinematic video: "
        "Hyper-realistic live-action anime adaptation of Sasuke Uchiha charging purple-black "
        "lightning Chidori on stone cliff. Pouring rain, wet hair blowing in the wind, dynamic lightning flashing, "
        "dramatic head turn looking straight into camera with glowing crimson Sharingan and purple Rinnegan. "
        "Smooth fluid human motion, 8k cinematic."
    )

    print("Typing video generation prompt...")
    inp = page.locator('[contenteditable="true"]').first
    inp.click()
    inp.fill(prompt)
    page.wait_for_timeout(1000)
    page.keyboard.press("Enter")
    page.wait_for_timeout(3000)

    send_btn = page.locator('button:has-text("arrow_forward"), button[aria-label*="Submit"]').first
    try:
        if send_btn.is_visible(timeout=1000):
            send_btn.click()
    except: pass

    print("Prompt submitted! Waiting 10s to capture agent response...")
    page.wait_for_timeout(10000)
    page.screenshot(path="flow_video_prompt_submitted.png")
    print("Screenshot saved to flow_video_prompt_submitted.png")

    ctx.close()
