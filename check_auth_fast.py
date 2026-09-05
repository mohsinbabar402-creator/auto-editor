from playwright.sync_api import sync_playwright
from pathlib import Path

for p_num in [1, 2, 3]:
    p_dir = Path(f"browser/flow_profile_{p_num}").resolve()
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(p_dir),
                headless=True,
                channel="chrome",
                args=["--no-first-run"]
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
            is_login = "accounts.google.com" in page.url
            has_pro = page.locator('text="PRO"').first.is_visible(timeout=2000)
            print(f"Profile {p_num}: URL={page.url[:45]}... | LoginRedirect={is_login} | PRO={has_pro}")
            ctx.close()
    except Exception as e:
        print(f"Profile {p_num}: Error {e}")
