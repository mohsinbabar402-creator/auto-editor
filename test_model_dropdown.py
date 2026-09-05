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

    # 1. Click on "Scenes" in the left sidebar
    print("Clicking 'Scenes' in the left navigation...")
    scenes_btn = page.locator('button:has-text("Scenes"), div:has-text("Scenes")').first
    if scenes_btn.is_visible(timeout=3000):
        scenes_btn.click()
        page.wait_for_timeout(2000)
        page.screenshot(path="flow_scenes_view.png")
        print("Saved flow_scenes_view.png")

    # 2. Click on the image to open editor and inspect the model dropdown
    card = page.locator('img[src*="getMediaUrlRedirect"]').first
    if card.is_visible(timeout=3000):
        card.click()
        page.wait_for_timeout(2000)
        
        # Click the model dropdown (Nano Banana 2)
        model_btn = page.locator('button:has-text("Nano Banana"), div:has-text("Nano Banana")').first
        if model_btn.is_visible(timeout=3000):
            model_btn.click()
            page.wait_for_timeout(1500)
            page.screenshot(path="flow_model_dropdown.png")
            print("Saved flow_model_dropdown.png")

    ctx.close()
