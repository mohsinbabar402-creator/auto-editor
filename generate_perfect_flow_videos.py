import sys, os, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from playwright.sync_api import sync_playwright

def setup_and_generate_part(part_id: str):
    p_dir = config.PROJECTS_DIR / part_id
    sb_file = p_dir / "storyboard.json"
    with open(sb_file, "r", encoding="utf-8") as f:
        sb = json.load(f)

    print(f"\n{'='*60}")
    print(f" GENERATING VEO VIDEOS (10-20 CREDITS): {sb['title']}")
    print(f"{'='*60}")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(config.BROWSER_PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            viewport={"width": 1400, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print("[1] Opening Google Flow...", flush=True)
        page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Create New Project
        print("[2] Creating New Video Project...", flush=True)
        new_btn = page.locator('button:has-text("New project"), div:has-text("+ New project")').first
        if new_btn.is_visible(timeout=5000):
            new_btn.click(force=True)
            page.wait_for_timeout(5000)

        # Open Settings (Tune icon) to configure auto-generate & 9:16 video
        print("[3] Configuring Settings for Auto-Video Generation...", flush=True)
        tune_btn = page.locator('button:has-text("tune"), button[aria-label*="Settings"]').first
        if tune_btn.is_visible(timeout=3000):
            tune_btn.click(force=True)
            page.wait_for_timeout(1000)
            
            # Select "Never" confirm
            never_radio = page.locator('text="Never"').first
            if never_radio.is_visible(timeout=2000):
                never_radio.click(force=True)
                print("   Set 'Confirm before generating' -> Never", flush=True)
            
            # Select 9:16 vertical for video
            v_916 = page.locator('button:has-text("9:16")').all()
            for b in v_916:
                if b.is_visible():
                    b.click(force=True)
            
            # Click Save
            save_btn = page.locator('button:has-text("Save")').first
            if save_btn.is_visible(timeout=2000):
                save_btn.click(force=True)
                page.wait_for_timeout(1000)
                print("   Saved settings!", flush=True)

        # Submit each scene as an explicit VIDEO generation
        for sc in sb["scenes"]:
            num = sc["scene_number"]
            name = sc["name"]
            raw_prompt = sc["visual_prompt"]
            
            video_prompt = f"Generate video: 9:16 vertical cinematic video. {raw_prompt}"
            print(f"\n[Scene {num}/6] Generating Video for: {name}...", flush=True)

            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

            for attempt in range(3):
                try:
                    chat_in = page.locator('[contenteditable="true"]').first
                    if chat_in.is_visible(timeout=5000):
                        chat_in.click(force=True)
                        page.wait_for_timeout(300)
                        page.keyboard.type(video_prompt, delay=1)
                        page.wait_for_timeout(300)
                        page.keyboard.press("Enter")
                        print(f"   Submitted scene {num} to Veo video engine!", flush=True)
                        page.wait_for_timeout(3000)

                        # Look for Approve/Create if prompted
                        for _ in range(3):
                            btns = page.locator('button:has-text("Approve"), button:has-text("Create")').all()
                            for b in btns:
                                if b.is_visible():
                                    b.click(force=True)
                            page.wait_for_timeout(1000)
                        break
                except Exception as e:
                    print(f"   Retry scene {num}: {e}", flush=True)
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(2000)

            # Wait 8s for generation dispatch
            page.wait_for_timeout(8000)

        # Save project URL
        with open(p_dir / "flow_project_url.txt", "w", encoding="utf-8") as f:
            f.write(page.url)
        print(f"\nALL 6 VIDEO PROMPTS QUEUED! Project URL: {page.url}", flush=True)
        page.wait_for_timeout(10000)
        ctx.close()

if __name__ == "__main__":
    part = sys.argv[1] if len(sys.argv) > 1 else "part2_the_great_ocean_surge"
    setup_and_generate_part(part)
