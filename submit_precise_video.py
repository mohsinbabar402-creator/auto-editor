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

    # Find the prompt input element
    print("Finding prompt input element...")
    inp = page.locator('textarea, [contenteditable="true"], input[type="text"]').all()
    print(f"Found {len(inp)} potential input elements:")
    target_inp = None
    for el in inp:
        try:
            vis = el.is_visible()
            ph = el.get_attribute('placeholder') or ''
            txt = el.inner_text()
            print(f"  Tag: {el.evaluate('e => e.tagName')} | Visible: {vis} | Placeholder: '{ph}'")
            if vis and ('create' in ph.lower() or 'want' in ph.lower() or el.evaluate('e => e.isContentEditable')):
                target_inp = el
                break
        except Exception as e:
            pass

    if target_inp:
        print("Found target input! Submitting video prompt...")
        prompt = (
            "Create a 5-second cinematic video: "
            "Hyper-realistic live-action anime adaptation of Sasuke Uchiha charging purple-black "
            "lightning Chidori on stone cliff in pouring rain. Wet hair blowing in the wind, lightning violently flashing, "
            "dramatic head turn looking straight into camera with glowing crimson Sharingan and purple Rinnegan. "
            "Fluid realistic human motion, 8k cinematic."
        )
        target_inp.click()
        target_inp.fill(prompt)
        page.wait_for_timeout(1000)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)

        # Look for send button
        send = page.locator('button:has(i:has-text("arrow_forward")), button[aria-label*="Submit"]').first
        if send.is_visible(timeout=1000):
            send.click()
        
        page.wait_for_timeout(5000)
        page.screenshot(path="video_submitted_success.png")
        print("Video prompt submitted successfully! Saved video_submitted_success.png")
    else:
        print("Could not find target input!")
        page.screenshot(path="failed_find_input.png")

    ctx.close()
