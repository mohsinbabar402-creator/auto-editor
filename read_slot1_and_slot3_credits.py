from pathlib import Path
import sys
import time
from playwright.sync_api import sync_playwright

BROWSER_DIR = Path("browser").resolve()

for slot, p_name in [(1, "flow_profile_1"), (3, "flow_profile_3")]:
    p_dir = BROWSER_DIR / p_name
    for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        f = p_dir / lk
        if f.exists():
            try: f.unlink()
            except Exception: pass

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(p_dir),
            channel="chrome",
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"]
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        credits_box = {"credits": None}
        def on_resp(res):
            if "credits" in res.url:
                try:
                    d = res.json()
                    credits_box["credits"] = d.get("credits") or d.get("subscriptionCredits")
                except Exception: pass

        page.on("response", on_resp)
        page.goto("https://labs.google/fx/tools/flow", timeout=45000, wait_until="load")
        page.wait_for_timeout(4000)

        # Click Create with Google Flow or New Project if visible
        for txt in ["Create with Google Flow", "New project", "Create project"]:
            btn = page.query_selector(f'button:has-text("{txt}"), a:has-text("{txt}")')
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(4000)
                break

        print(f"Slot {slot} ({p_name}) Live Credits: {credits_box['credits']}")
        ctx.close()
