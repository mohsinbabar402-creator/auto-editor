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

    # Click top-left back arrow to return to main canvas
    print("Clicking top-left back arrow...")
    page.mouse.click(35, 35)
    page.wait_for_timeout(3000)
    page.screenshot(path="back_clicked.png")

    # Now check if [contenteditable="true"] is visible
    inp = page.locator('[contenteditable="true"]').first
    print("Is chat input visible now?:", inp.is_visible(timeout=5000))

    if inp.is_visible():
        prompt = (
            "Generate a 5-second cinematic video: "
            "Hyper-realistic live-action anime adaptation of Sasuke Uchiha charging purple-black "
            "lightning Chidori on stone cliff. Pouring rain, wet hair blowing in the wind, dynamic lightning flashing, "
            "dramatic head turn looking straight into camera with glowing crimson Sharingan and purple Rinnegan. "
            "Smooth fluid human motion, 8k cinematic."
        )
        print("Typing video generation prompt...")
        inp.click()
        inp.fill(prompt)
        page.wait_for_timeout(1000)
        page.keyboard.press("Enter")
        page.wait_for_timeout(4000)

        # Take screenshot of generation starting
        page.screenshot(path="video_generation_started.png")
        print("Saved video_generation_started.png")

    ctx.close()
