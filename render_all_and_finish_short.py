from playwright.sync_api import sync_playwright
from pathlib import Path
import time, subprocess, shutil
import config

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
real_dir = Path("projects/08_naruto_vs_sasuke/real_videos")
real_dir.mkdir(parents=True, exist_ok=True)

naruto_vid_file = real_dir / "naruto_real_motion_video.mp4"
clash_vid_file = real_dir / "clash_real_motion_video.mp4"
sasuke_vid_file = real_dir / "sasuke_real_motion_video.mp4"

print("Starting pipeline: Wait for Naruto -> Prompt Clash -> Wait for Clash -> Compile Final Short!")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(proj_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)

    # Helper to download media by checking network or video elements
    def get_latest_video(known_urls):
        vids = page.locator('video').all()
        for v in vids:
            s = v.get_attribute("src") or v.get_attribute("currentSrc")
            if s and s not in known_urls:
                if s.startswith('/'):
                    s = "https://labs.google" + s
                return s
        return None

    known_urls = {
        "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=8d6c01ad-499c-4ebe-97ea-dec4b70566b1",
        "/fx/api/trpc/media.getMediaUrlRedirect?name=8d6c01ad-499c-4ebe-97ea-dec4b70566b1"
    }

    # 1. Wait for Naruto video
    print("\n[Step 1] Waiting for Naruto video rendering to complete (up to 120s)...")
    naruto_url = None
    for sec in range(25): # 125s
        page.wait_for_timeout(5000)
        v = get_latest_video(known_urls)
        if v:
            naruto_url = v
            known_urls.add(v)
            print(f"Found Naruto video: {v[:80]}...")
            break
        print(f"  Rendering Naruto... ({ (sec+1)*5 }s)")

    if naruto_url:
        resp = page.request.get(naruto_url)
        if resp.status == 200:
            naruto_vid_file.write_bytes(resp.body())
            print(f"SUCCESS: Downloaded {naruto_vid_file.name} ({naruto_vid_file.stat().st_size} bytes)")
    else:
        print("Naruto video not detected yet, taking screenshot...")
        page.screenshot(path="naruto_wait_debug.png")

    # 2. Submit Clash prompt
    print("\n[Step 2] Submitting Clash video prompt...")
    inp = page.locator('div[role="textbox"]').first
    inp.click()
    page.wait_for_timeout(300)
    clash_prompt = "Create a 5-second cinematic video of Naruto and Sasuke colliding in mid-air over waterfall, Rasengan clashing into Chidori with massive explosion"
    page.keyboard.type(clash_prompt, delay=15)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2000)
    
    send_btn = page.locator('button:has(i:has-text("arrow_forward"))').first
    if send_btn.is_visible(timeout=1000) and send_btn.is_enabled():
        send_btn.click()

    # Check for approval button if it asks
    page.wait_for_timeout(2000)
    try:
        appr = page.locator('button:has-text("Approve")').first
        if appr.is_visible(timeout=2000):
            appr.click()
    except: pass

    # 3. Wait for Clash video
    print("\n[Step 3] Waiting for Clash video rendering (up to 120s)...")
    clash_url = None
    for sec in range(25): # 125s
        page.wait_for_timeout(5000)
        v = get_latest_video(known_urls)
        if v:
            clash_url = v
            print(f"Found Clash video: {v[:80]}...")
            break
        print(f"  Rendering Clash... ({ (sec+1)*5 }s)")

    if clash_url:
        resp = page.request.get(clash_url)
        if resp.status == 200:
            clash_vid_file.write_bytes(resp.body())
            print(f"SUCCESS: Downloaded {clash_vid_file.name} ({clash_vid_file.stat().st_size} bytes)")

    ctx.close()

print("\nAll videos gathered! Proceeding to final short assembly...")
