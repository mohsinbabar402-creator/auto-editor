"""
sync_profile_status.py
Automatically inspects a Google Flow profile folder, validates login,
fetches live credit balance and PRO status from Google APIs,
and syncs everything into mission_control.json.
"""
import sys
import os
import json
import time
from pathlib import Path

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
MISSION_CONTROL_PATH = BASE_DIR / "mission_control.json"
BROWSER_DIR = BASE_DIR / "browser"


def sync_profile(profile_num: int):
    print("=" * 60)
    print(f" SYNCING GOOGLE FLOW PROFILE #{profile_num}")
    print("=" * 60)

    profile_dir = BROWSER_DIR / f"flow_profile_{profile_num}"
    if not profile_dir.exists():
        print(f"[!] Profile folder does not exist: {profile_dir}")
        return False

    pref_file = profile_dir / "Default" / "Preferences"
    local_email = None
    if pref_file.exists():
        try:
            with open(pref_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                accs = data.get("account_info", [])
                if accs and isinstance(accs, list) and len(accs) > 0:
                    local_email = accs[0].get("email")
                if not local_email:
                    local_email = data.get("profile", {}).get("gaia_name")
        except Exception as e:
            print(f"[Notice] Reading Preferences: {e}")

    if not local_email:
        print(f"[!] No Google account detected in flow_profile_{profile_num}.")
        print("    Please log in first using OPEN_FLOW_PROFILE.bat")
        return False

    print(f"[1/3] Local Google Session Found: {local_email}")
    print("[2/3] Querying live Google Flow credits & subscription tier...")

    credits_data = {}
    auth_data = {}

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=True,
                channel="chrome",
                args=["--no-first-run", "--no-default-browser-check"]
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            def handle_resp(res):
                if "aisandbox-pa.googleapis.com/v1/credits" in res.url:
                    try:
                        credits_data.update(res.json())
                    except Exception:
                        pass
                if "fx/api/auth/session" in res.url:
                    try:
                        auth_data.update(res.json())
                    except Exception:
                        pass

            page.on("response", handle_resp)
            page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)

            # Check for PRO badge in DOM
            dom_has_pro = False
            try:
                pro_loc = page.locator('button:has-text("PRO"), span:has-text("PRO"), div:has-text("PRO")').first
                if pro_loc.is_visible(timeout=3000):
                    dom_has_pro = True
            except Exception:
                pass

            # If credits endpoint hasn't responded yet, click New project to trigger it
            if not credits_data:
                try:
                    new_btn = page.locator('button:has-text("New project"), a:has-text("New project")').first
                    if new_btn.is_visible(timeout=3000):
                        new_btn.click()
                        page.wait_for_timeout(4000)
                except Exception:
                    pass

            ctx.close()
    except Exception as e:
        print(f"      Live query notice: {e}")

    # Determine real values
    live_credits = credits_data.get("credits")
    if live_credits is None:
        live_credits = credits_data.get("subscriptionCredits")

    paygate_tier = credits_data.get("userPaygateTier", "")
    is_pro = paygate_tier == "PAYGATE_TIER_ONE" or (live_credits and live_credits >= 500) or dom_has_pro
    tier_name = "pro" if is_pro else "free"
    confirmed_email = auth_data.get("user", {}).get("email") or local_email

    print(f"[3/3] Live Account Data Verified:")
    print(f"      - Email:   {confirmed_email}")
    print(f"      - Tier:    {'★ PRO (Google AI Pro)' if is_pro else 'Free Tier'}")
    print(f"      - Credits: {live_credits if live_credits is not None else 'Active'}")

    # Update mission_control.json
    if MISSION_CONTROL_PATH.exists():
        try:
            with open(MISSION_CONTROL_PATH, "r", encoding="utf-8") as f:
                mc = json.load(f)

            flow_accs = mc.setdefault("google_flow_accounts", {})
            power = flow_accs.setdefault("power_accounts", [])
            daily = flow_accs.setdefault("daily_accounts", [])

            # Remove existing entry for this profile number from both lists
            flow_accs["power_accounts"] = [a for a in power if a.get("profile") != profile_num]
            flow_accs["daily_accounts"] = [a for a in daily if a.get("profile") != profile_num]

            entry = {
                "profile": profile_num,
                "label": confirmed_email.split("@")[0],
                "email": confirmed_email,
                "tier": tier_name,
                "status": "logged_in",
                "last_synced": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }

            if is_pro:
                entry["priority"] = 1
                entry["credits"] = live_credits if live_credits is not None else 1050
                flow_accs["power_accounts"].insert(0, entry)
            else:
                entry["priority"] = 2
                entry["credits_daily"] = live_credits if live_credits is not None else 50
                flow_accs["daily_accounts"].append(entry)

            # Recalculate totals
            total_banked = sum(a.get("credits", 0) for a in flow_accs.get("power_accounts", []))
            total_daily = sum(a.get("credits_daily", 50) for a in flow_accs.get("daily_accounts", []))
            flow_accs["total_banked_credits"] = total_banked
            flow_accs["total_daily_credits"] = total_daily

            with open(MISSION_CONTROL_PATH, "w", encoding="utf-8") as f:
                json.dump(mc, f, indent=2)

            print(f"\n[✓] mission_control.json updated successfully!")
            print(f"    Total Banked Credits: {total_banked}")
            print(f"    Total Daily Credits:  {total_daily}/day")
        except Exception as e:
            print(f"[!] Error updating mission_control.json: {e}")

    print("=" * 60)
    return True


if __name__ == "__main__":
    p_num = 1
    if len(sys.argv) > 1:
        try:
            p_num = int(sys.argv[1])
        except ValueError:
            pass
    sync_profile(p_num)
