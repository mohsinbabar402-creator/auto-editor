import json
import logging
from pathlib import Path
import re
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

BROWSER_DIR = Path("browser").resolve()

PROFILES = [
    (1, "flow_profile_1"),
    (2, "flow_profile_2"),
    (3, "flow_profile_3"),
    (4, "flow_profile_4"),
]

def clean_locks(p_dir: Path):
    for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        f = p_dir / lk
        if f.exists():
            try:
                f.unlink()
            except Exception:
                pass

def inspect_profile(slot: int, prof_name: str):
    p_dir = BROWSER_DIR / prof_name
    if not p_dir.exists():
        return {"slot": slot, "profile": prof_name, "error": "Folder missing"}

    clean_locks(p_dir)

    result = {
        "slot": slot,
        "profile": prof_name,
        "email": "Unknown",
        "account_name": "Unknown",
        "flow_logged_in": False,
        "credits": None,
        "tier": "Unknown",
        "gemini_logged_in": False,
        "gemini_account": "Unknown",
    }

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(p_dir),
                channel="chrome",
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check"
                ],
                viewport={"width": 1280, "height": 900}
            )

            # 1. Inspect Flow
            page_flow = ctx.pages[0] if ctx.pages else ctx.new_page()
            credits_captured = {}

            def handle_flow_response(res):
                if "aisandbox-pa.googleapis.com/v1/credits" in res.url:
                    try:
                        d = res.json()
                        credits_captured["credits"] = d.get("credits") or d.get("subscriptionCredits")
                        credits_captured["tier"] = d.get("userPaygateTier")
                        logger.info(f"Captured credits API response: {credits_captured}")
                    except Exception:
                        pass

            page_flow.on("response", handle_flow_response)

            try:
                page_flow.goto("https://labs.google/fx/tools/flow", timeout=45000, wait_until="load")
                page_flow.wait_for_timeout(6000)

                # If not caught by listener, attempt direct fetch in context
                if not credits_captured:
                    try:
                        eval_res = page_flow.evaluate('''async () => {
                            const r = await fetch('https://aisandbox-pa.googleapis.com/v1/credits');
                            return r.ok ? await r.json() : null;
                        }''')
                        if eval_res:
                            credits_captured["credits"] = eval_res.get("credits") or eval_res.get("subscriptionCredits")
                            credits_captured["tier"] = eval_res.get("userPaygateTier")
                    except Exception:
                        pass

                if "credits" in credits_captured and credits_captured["credits"] is not None:
                    result["flow_logged_in"] = True
                    result["credits"] = credits_captured["credits"]
                    tier = credits_captured.get("tier", "")
                    result["tier"] = "PRO" if "ONE" in str(tier) or result["credits"] >= 500 else "FREE"
                else:
                    body_f = page_flow.inner_text("body")
                    if "Sign in" not in body_f and ("Create" in body_f or "New project" in body_f or "PRO" in body_f):
                        result["flow_logged_in"] = True
                        result["tier"] = "PRO" if "PRO" in body_f else "ACTIVE"

            except Exception as e:
                result["flow_error"] = str(e)

            # 2. Inspect Gemini
            page_gemini = ctx.new_page()
            try:
                page_gemini.goto("https://gemini.google.com/app", timeout=30000, wait_until="domcontentloaded")
                page_gemini.wait_for_timeout(3500)

                avatar = page_gemini.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
                body_g = page_gemini.inner_text("body")

                if avatar and "Sign in to try" not in body_g and "Sign in with Google" not in body_g:
                    result["gemini_logged_in"] = True
                    aria_g = avatar.get_attribute("aria-label") or ""
                    result["gemini_account"] = aria_g

                    # Parse account name and email
                    # Typical aria-label: "Google Account: Octal Accounts \n(aoctal522@gmail.com)"
                    # or "Google Account: Mohsin Mughal (mohsinmughal1771@gmail.com)"
                    m_email = re.search(r'[\w\.-]+@[\w\.-]+', aria_g)
                    if m_email:
                        result["email"] = m_email.group(0)

                    # Extract display name
                    clean_name = aria_g.replace("Google Account:", "").strip()
                    if "(" in clean_name:
                        clean_name = clean_name.split("(")[0].strip()
                    if clean_name:
                        result["account_name"] = clean_name

            except Exception as e:
                result["gemini_error"] = str(e)

            ctx.close()

        except Exception as e:
            result["error"] = str(e)

    return result

def main():
    print("=" * 80)
    print(" LIVE AUDIT: CHECKING ACTUAL CREDITS, GMAIL NAMES, AND GEMINI ACROSS PROFILES")
    print("=" * 80)

    results = []
    for slot, p_name in PROFILES:
        print(f">> Inspecting {p_name} (Slot {slot})...", flush=True)
        res = inspect_profile(slot, p_name)
        results.append(res)
        time.sleep(1)

    print("\n" + "=" * 80)
    print(f"{'Slot':<5} | {'Profile':<15} | {'Account Name':<20} | {'Email':<28} | {'Flow Credits':<12} | {'Gemini'}")
    print("-" * 80)

    for r in results:
        slot = r.get("slot")
        prof = r.get("profile")
        name = (r.get("account_name") or "Unknown")[:20]
        email = r.get("email") or "Unknown"
        credits = f"{r.get('credits')} ({r.get('tier')})" if r.get("credits") is not None else "No credits"
        gemini = "🟢 Logged In" if r.get("gemini_logged_in") else "⚪ Signed Out"
        print(f"{slot:<5} | {prof:<15} | {name:<20} | {email:<28} | {credits:<12} | {gemini}")

    print("=" * 80 + "\n")

    # Also save the verified live data to a clean JSON file
    out_file = Path("live_accounts_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Detailed audit results saved to {out_file.resolve()}")

if __name__ == "__main__":
    main()
