from playwright.sync_api import sync_playwright
from pathlib import Path

p_dir = Path("browser/flow_profile_1").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    print("Profile 1 Page title:", page.title())
    print("Profile 1 URL:", page.url)

    ss_path = Path("projects/08_naruto_vs_sasuke/profile1_studio.png")
    page.screenshot(path=str(ss_path))
    print("Screenshot saved to:", ss_path.name)

    new_proj = page.locator('text="New project"').first.is_visible(timeout=3000)
    print("New Project Button Visible:", new_proj)

    # Let's check credits via API call
    credits = page.evaluate('''async () => {
        try {
            const r = await fetch('https://aisandbox-pa.googleapis.com/v1/credits');
            return await r.json();
        } catch(e) { return null; }
    }''')
    print("Live Credits:", credits)
    ctx.close()
