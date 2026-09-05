from playwright.sync_api import sync_playwright
from pathlib import Path
import json

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

    # Inspect all buttons in and around the chat input
    btns = page.evaluate('''() => {
        const list = [];
        document.querySelectorAll('button').forEach(b => {
            list.push({
                text: b.innerText.trim(),
                aria: b.getAttribute('aria-label'),
                title: b.getAttribute('title'),
                html: b.outerHTML.substring(0, 150)
            });
        });
        return list;
    }''')
    print(f"Found {len(btns)} buttons:")
    for b in btns:
        if any(w in (b['aria'] or '').lower() or w in (b['text'] or '').lower() for w in ['video', 'model', 'mode', 'tool', 'setting', 'tune', 'scene']):
            print(" ", b)

    # Take screenshot of the bottom input area
    page.screenshot(path="flow_input_inspection.png")
    print("Screenshot saved to flow_input_inspection.png")

    ctx.close()
