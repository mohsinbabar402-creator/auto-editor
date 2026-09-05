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

    # 1. Click the 'tune' (settings) button next to prompt input
    print("Clicking 'tune' settings button...")
    tune_btn = page.locator('button:has(i:has-text("tune"))').first
    if tune_btn.is_visible(timeout=3000):
        tune_btn.click()
        page.wait_for_timeout(2000)
        page.screenshot(path="flow_tune_settings.png")
        print("Settings screenshot saved.")

    # 2. Check what's inside the settings popup
    popups = page.evaluate('''() => {
        const list = [];
        document.querySelectorAll('[role="dialog"], [role="menu"], [data-radix-popper-content-wrapper]').forEach(el => {
            list.push(el.innerText);
        });
        return list;
    }''')
    print("Popup contents:", popups)

    # 3. Click the first image card on canvas
    print("Clicking first image on canvas...")
    card = page.locator('img[src*="getMediaUrlRedirect"]').first
    if card.is_visible(timeout=3000):
        card.click()
        page.wait_for_timeout(2000)
        page.screenshot(path="flow_card_selected.png")
        print("Card selected screenshot saved.")
        
        card_actions = page.evaluate('''() => {
            const list = [];
            document.querySelectorAll('button').forEach(b => {
                if (b.innerText.trim()) list.push(b.innerText.trim());
            });
            return list;
        }''')
        print("Visible buttons after card click:", card_actions)

    ctx.close()
