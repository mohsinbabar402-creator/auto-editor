from pathlib import Path
from playwright.sync_api import sync_playwright

p_dir = Path("browser/flow_profile_1").resolve()
for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
    f = p_dir / lk
    if f.exists():
        try: f.unlink()
        except Exception: pass

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        channel="chrome",
        headless=True,
        args=["--disable-blink-features=AutomationControlled"]
    )
    page = ctx.pages[0]
    credits_val = None

    def on_resp(res):
        global credits_val
        if "credits" in res.url:
            try:
                d = res.json()
                if "credits" in d or "subscriptionCredits" in d:
                    credits_val = d.get("credits") or d.get("subscriptionCredits")
                    print(f"Captured credits payload: {d}")
            except Exception: pass

    page.on("response", on_resp)
    page.goto("https://flow.google.com/", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    # Click New project or any project card
    new_btn = page.query_selector('button:has-text("New project"), a:has-text("New project")')
    if new_btn:
        print("Clicking 'New project'...")
        new_btn.click()
        page.wait_for_timeout(6000)

    print("SLOT 1 EXACT LIVE CREDITS:", credits_val)
    ctx.close()
