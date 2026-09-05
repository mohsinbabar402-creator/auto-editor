import sys, os, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from playwright.sync_api import sync_playwright

def submit_part_to_flow(part_id: str):
    p_dir = config.PROJECTS_DIR / part_id
    sb_file = p_dir / "storyboard.json"
    with open(sb_file, "r", encoding="utf-8") as f:
        sb = json.load(f)
    
    print(f"\n{'='*60}")
    print(f" SUBMITTING ALL 6 PROMPTS: {sb['title']}")
    print(f"{'='*60}")
    
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(config.BROWSER_PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            viewport={"width": 1400, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        
        print("Opening Google Flow...", flush=True)
        page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        
        # Click "+ New project"
        print("Creating New Project...", flush=True)
        new_btn = page.locator('button:has-text("New project"), div:has-text("+ New project")').first
        if new_btn.is_visible(timeout=5000):
            new_btn.click(force=True)
            page.wait_for_timeout(5000)
        
        for sc in sb["scenes"]:
            num = sc["scene_number"]
            name = sc["name"]
            prompt = sc["visual_prompt"]
            
            print(f"\n[Scene {num}/6] Submitting: {name}...")
            
            # Dismiss any active modal or overlay
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)
            
            # Find chat input
            submitted = False
            for attempt in range(5):
                try:
                    chat_in = page.locator('[contenteditable="true"]').first
                    if chat_in.is_visible(timeout=5000):
                        chat_in.click(force=True)
                        page.wait_for_timeout(500)
                        # Type prompt
                        page.keyboard.type(prompt, delay=2)
                        page.wait_for_timeout(500)
                        page.keyboard.press("Enter")
                        print(f"   Enter pressed for scene {num}!", flush=True)
                        page.wait_for_timeout(3000)
                        
                        # Look for Approve/Generate button
                        for _ in range(6):
                            btns = page.locator('button:has-text("Approve"), button:has-text("Generate"), button:has-text("Create")')
                            if btns.count() > 0:
                                btns.last.click(force=True)
                                print("   Clicked Approve/Generate!", flush=True)
                                break
                            page.wait_for_timeout(1000)
                        
                        submitted = True
                        break
                except Exception as e:
                    print(f"   Attempt {attempt+1} retry: {e}")
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(2000)
            
            if submitted:
                print(f"   Scene {num} successfully queued!")
            else:
                print(f"   FAILED to queue scene {num}!")
            
            # Give Flow 6 seconds between prompts
            page.wait_for_timeout(6000)
        
        print(f"\nAll 6 scenes submitted for {part_id}!")
        page.wait_for_timeout(10000)
        
        with open(p_dir / "flow_project_url.txt", "w", encoding="utf-8") as f:
            f.write(page.url)
        print(f"Project URL saved: {page.url}")
        
        ctx.close()

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "part2_the_great_ocean_surge"
    submit_part_to_flow(target)
