import time, json, requests
from playwright.sync_api import sync_playwright
from pathlib import Path

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_dir = Path("projects/08_naruto_vs_sasuke/renders")
out_dir.mkdir(parents=True, exist_ok=True)

prompt_text = (
    "Vertical 9:16 cinematic action film scene. Hyper-realistic live-action adaptation of Sasuke Uchiha standing atop "
    "a massive ancient stone monument during a violent midnight thunderstorm. Torrential pouring rain drenching his black spiky hair "
    "and battle-torn shinobi tunic. Intense macro close-up of his eyes: glowing crimson red Sharingan with three-tomoe in right eye, "
    "glowing purple ripple-patterned Rinnegan in left eye. Violent arcs of pitch-black lightning and electric purple plasma crackling "
    "across his right hand with blinding flashes illuminating the wet stone. 8k, photorealistic, anamorphic 35mm lens, "
    "atmospheric volumetric haze, moody dark cinematic lighting."
)

print(f"Connecting to Google Flow Project with Blazing Soul (Profile 4)...")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run", "--disable-blink-features=AutomationControlled"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    captured_videos = []
    def on_response(res):
        u = res.url
        if "flow-content.google/video" in u or "videofx" in u and ".mp4" in u:
            print(f"[Captured Video URL]: {u[:90]}...")
            captured_videos.append(u)
    page.on("response", on_response)

    print("Navigating to project editor...")
    page.goto(proj_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)

    # Find prompt input
    inp = page.locator('[contenteditable="true"]').first
    if not inp.is_visible(timeout=8000):
        print("Prompt input not visible!")
        ctx.close()
        exit(1)

    print("Typing prompt into Google Flow...")
    inp.click()
    inp.fill(prompt_text)
    page.wait_for_timeout(1000)

    # Click submit or press Enter
    print("Submitting prompt for generation...")
    page.keyboard.press("Enter")
    page.wait_for_timeout(3000)

    # Also try clicking the arrow submit button if Enter didn't trigger
    send_btn = page.locator('button:has-text("arrow_forward"), button[aria-label*="Submit"], button[aria-label*="Create"]').first
    try:
        if send_btn.is_visible(timeout=1000):
            send_btn.click()
            print("Clicked submit button.")
    except: pass

    # Take screenshot of generation starting
    page.screenshot(path="projects/08_naruto_vs_sasuke/generating_step1.png")
    print("Prompt submitted! Waiting for Veo 2 generation...")

    # Wait for generation to complete (up to 3 minutes)
    for minute in range(1, 30):
        page.wait_for_timeout(6000)
        print(f"  Checking progress ({minute * 6}s)... captured: {len(captured_videos)}")
        if captured_videos:
            break
            
    page.screenshot(path="projects/08_naruto_vs_sasuke/generating_step2.png")
    print("Finished wait cycle.")
    ctx.close()
