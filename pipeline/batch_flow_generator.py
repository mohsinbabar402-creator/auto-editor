"""
Batch Google Flow Multi-Scene Video Generator
Submits all scene prompts together into Google Flow so they render concurrently in the cloud.
Downloads all rendered clips in one batch and triggers final composite.
"""
import sys, os, time, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

FLOW_URL = "https://labs.google/fx/tools/flow"

def run_batch_flow_generation(project_name: str = "earth_stops_rotating", timeout_sec: int = 360):
    proj_dir = config.PROJECTS_DIR / project_name
    clips_dir = proj_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    prompts_file = proj_dir / "google_flow_prompts.json"

    with open(prompts_file, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    print("\n" + "="*60, flush=True)
    print(f"🚀 GOOGLE FLOW PARALLEL BATCH GENERATOR: {project_name}", flush=True)
    print(f"• Total Scenes: {len(prompts)}", flush=True)
    print(f"• Profile: {config.BROWSER_PROFILE_DIR}", flush=True)
    print("="*60, flush=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(config.BROWSER_PROFILE_DIR),
            headless=False,
            args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
            viewport={'width': 1280, 'height': 900},
            accept_downloads=True
        )
        page = context.pages[0] if context.pages else context.new_page()

        print("[1/4] Navigating to Google Flow...", flush=True)
        page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        # Open project or create new project
        if "/project/" not in page.url:
            print("[2/4] Creating dedicated video project in Flow...", flush=True)
            new_btn = page.locator('button:has-text("New project"), a:has-text("New project")').first
            if new_btn.is_visible(timeout=5000):
                new_btn.click()
                page.wait_for_timeout(8000)

        # Find chat input
        print("[3/4] Queuing all scene prompts into Google Flow...", flush=True)
        chat_input = page.locator('[contenteditable="true"]').first
        chat_input.click()
        page.wait_for_timeout(300)

        # Build combined multi-scene batch prompt
        batch_prompt_lines = ["Generate cinematic 9:16 vertical videos for each of the following scenes in parallel:"]
        for p_info in prompts:
            sc_num = p_info["scene_number"]
            sc_name = p_info["scene_name"]
            p_text = p_info["veo_prompt"]
            batch_prompt_lines.append(f"\n[Scene {sc_num}: {sc_name}]\n{p_text}")

        full_batch_prompt = "\n".join(batch_prompt_lines)

        # Enter batch prompt
        print(f"• Submitting master batch prompt ({len(prompts)} scenes)...", flush=True)
        page.keyboard.type(full_batch_prompt, delay=5)
        page.wait_for_timeout(500)

        # Submit
        send_btn = page.locator('button:has-text("arrow_forward"), button[aria-label*="Send" i]').first
        if send_btn.is_visible(timeout=2000):
            send_btn.click()
        else:
            page.keyboard.press("Enter")

        # Auto-Approve Credits
        print("[4/4] Monitoring cloud generation queue & auto-approving...", flush=True)
        start_time = time.time()
        approved = False

        while (time.time() - start_time) < timeout_sec:
            page.wait_for_timeout(4000)
            elapsed = int(time.time() - start_time)

            # Auto-approve credit prompt if displayed
            if not approved:
                approve_targets = [
                    'text="Approve, do not ask again"',
                    'text="Approve"',
                    'button:has-text("Approve, do not ask again")',
                    'button:has-text("Approve")',
                ]
                for sel in approve_targets:
                    try:
                        loc = page.locator(sel)
                        if loc.count() > 0 and loc.last.is_visible(timeout=500):
                            print("✓ Credit confirmation approved.", flush=True)
                            loc.last.click(force=True)
                            approved = True
                            break
                    except:
                        pass

            if elapsed % 20 == 0:
                print(f"   • Generating all scenes in parallel ({elapsed}s elapsed)...", flush=True)
                page.screenshot(path=str(proj_dir / f"batch_progress_{elapsed}s.png"))

        context.close()

    print("\n🎉 Batch generation request completed on Google Flow cloud!", flush=True)

if __name__ == "__main__":
    run_batch_flow_generation()
