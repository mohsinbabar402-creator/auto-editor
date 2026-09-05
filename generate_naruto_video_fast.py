from playwright.sync_api import sync_playwright
from pathlib import Path
import time, subprocess, shutil
import config

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
real_dir = Path("projects/08_naruto_vs_sasuke/real_videos")
real_dir.mkdir(parents=True, exist_ok=True)
dest_file = real_dir / "naruto_real_motion_video.mp4"

known_urls = {
    "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=8d6c01ad-499c-4ebe-97ea-dec4b70566b1",
    "/fx/api/trpc/media.getMediaUrlRedirect?name=8d6c01ad-499c-4ebe-97ea-dec4b70566b1",
    "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=75af288f-86b1-48f8-b328-944f227a92fb",
    "/fx/api/trpc/media.getMediaUrlRedirect?name=75af288f-86b1-48f8-b328-944f227a92fb"
}

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

    # Click on input box
    inp = page.locator('div[role="textbox"]').first
    inp.click()
    page.wait_for_timeout(300)

    naruto_prompt = (
        "Create a 5-second cinematic video: "
        "Photorealistic live-action anime adaptation of Naruto Uzumaki crouched in pouring rain charging spinning cyan-gold Rasengan, "
        "dramatic camera push-in looking into camera with glowing orange Nine-Tails fox slit eyes."
    )
    print("Typing Naruto video prompt...")
    page.keyboard.type(naruto_prompt, delay=15)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2000)

    send_btn = page.locator('button:has(i:has-text("arrow_forward"))').first
    if send_btn.is_visible(timeout=1000) and send_btn.is_enabled():
        send_btn.click()

    # Check for approval
    page.wait_for_timeout(2000)
    try:
        appr = page.locator('button:has-text("Approve")').first
        if appr.is_visible(timeout=2000):
            appr.click()
    except: pass

    print("Waiting for Naruto video to render (approx 60-90s)...")
    naruto_url = None
    for sec in range(25): # 125s
        page.wait_for_timeout(5000)
        vids = page.locator('video').all()
        for v in vids:
            s = v.get_attribute("src") or v.get_attribute("currentSrc")
            if s and not any(k in s for k in ["8d6c01ad", "75af288f"]):
                if s.startswith('/'):
                    s = "https://labs.google" + s
                naruto_url = s
                break
        if naruto_url:
            print(f"Found Naruto video! URL: {naruto_url[:80]}...")
            break
        print(f"  Rendering Naruto ({ (sec+1)*5 }s)...")

    if naruto_url:
        resp = page.request.get(naruto_url)
        if resp.status == 200:
            dest_file.write_bytes(resp.body())
            print(f"SUCCESS: Downloaded {dest_file.name} ({dest_file.stat().st_size} bytes)")
    else:
        print("Naruto video timed out!")
        page.screenshot(path="naruto_final_timeout.png")

    ctx.close()
