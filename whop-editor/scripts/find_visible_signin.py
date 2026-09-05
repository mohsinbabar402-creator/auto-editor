from pathlib import Path
from playwright.sync_api import sync_playwright

p = Path("browser/google_flow_profile").resolve()

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(p),
        channel="chrome",
        headless=True,
        args=["--headless=new", "--disable-blink-features=AutomationControlled"],
        viewport={"width": 1280, "height": 900}
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://gemini.google.com/app", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    elements = page.query_selector_all('a, button, [role="button"]')
    print(f"Checking {len(elements)} clickable elements for visible Sign in...")
    for idx, el in enumerate(elements):
        txt = (el.inner_text() or "").strip()
        aria = (el.get_attribute("aria-label") or "").strip()
        href = (el.get_attribute("href") or "").strip()
        box = el.bounding_box()
        if "sign in" in txt.lower() or "sign in" in aria.lower() or "accounts.google.com" in href.lower():
            is_vis = el.is_visible()
            print(f"  #{idx} tag={el.evaluate('e => e.tagName')}, txt='{txt}', is_visible={is_vis}, box={box}, href='{href[:60]}'")
            if is_vis and box and box["width"] > 10 and box["height"] > 10:
                print(f"===> CLICKING VISIBLE SIGN IN ELEMENT #{idx}")
                el.click()
                page.wait_for_timeout(4000)
                print("New URL:", page.url)
                page.screenshot(path="whop-editor/data/analysis/signin_clicked_result.png")
                break
    ctx.close()
