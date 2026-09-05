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
    
    page.screenshot(path="current_project_state.png")
    print("Saved current_project_state.png")
    
    # Check all elements with role or placeholder
    inputs = page.evaluate('''() => {
        const list = [];
        document.querySelectorAll('input, textarea, div[contenteditable="true"], [role="textbox"]').forEach(el => {
            list.push({
                tag: el.tagName,
                ph: el.getAttribute('placeholder') || '',
                vis: el.offsetWidth > 0 && el.offsetHeight > 0,
                html: el.outerHTML.substring(0, 100)
            });
        });
        return list;
    }''')
    print("Found inputs:", inputs)
    ctx.close()
