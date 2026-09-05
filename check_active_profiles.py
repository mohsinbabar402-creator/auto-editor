import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
from pathlib import Path
import json

base_dir = Path(r'c:\Users\ice\Desktop\youtube shorts project\browser')
profiles = [1, 2, 3, 4, 7]

print("=== LIVE GOOGLE FLOW VERIFICATION ===")
for p_num in profiles:
    p_dir = base_dir / f"flow_profile_{p_num}"
    if not p_dir.exists():
        continue
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(p_dir),
                headless=True,
                channel="chrome",
                args=["--no-first-run", "--no-default-browser-check"]
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            
            page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)
            
            has_pro = page.locator('button:has-text("PRO"), span:has-text("PRO"), div:has-text("PRO")').first.is_visible(timeout=3000)
            
            email = None
            pref_file = p_dir / "Default" / "Preferences"
            if pref_file.exists():
                try:
                    with open(pref_file, "r", encoding="utf-8") as f:
                        d = json.load(f)
                        accs = d.get("account_info", [])
                        if accs: email = accs[0].get("email")
                except: pass
                
            status = "PRO ACTIVE" if has_pro else ("LOGGED IN" if "fx/tools/flow" in page.url else "NEEDS LOGIN")
            print(f"Profile {p_num:>2} | Status: {status:<12} | Email: {email}")
            ctx.close()
    except Exception as e:
        print(f"Profile {p_num:>2} | Error: {e}")
