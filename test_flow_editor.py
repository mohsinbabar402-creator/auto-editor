from playwright.sync_api import sync_playwright
from pathlib import Path

p_dir = Path("browser/flow_profile_4").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    print("Clicking '+ New project' button...")
    # The button has text "+ New project"
    btn = page.locator('text="New project"').first
    if btn.is_visible(timeout=5000):
        btn.click()
        page.wait_for_timeout(6000)
        print("Current URL:", page.url)

        # Check prompt input
        inp = page.locator('[contenteditable="true"]').first
        vis = inp.is_visible(timeout=5000)
        print("Prompt input visible:", vis)
    else:
        print("Button not visible!")
        page.screenshot(path="flow_home_debug.png")
    ctx.close()
