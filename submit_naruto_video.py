from playwright.sync_api import sync_playwright
from pathlib import Path
import time

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_dir = Path("projects/08_naruto_vs_sasuke/real_videos")
dest_file = out_dir / "naruto_real_motion_video.mp4"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(proj_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)

    # Find existing videos before
    existing_vids = set(page.evaluate('''() => {
        const list = [];
        document.querySelectorAll('video').forEach(v => {
            if (v.src) list.push(v.src);
        });
        return list;
    }'''))
    print(f"Existing video tags: {len(existing_vids)}")

    inp = page.locator('div[role="textbox"]').first
    print("Found input, clicking...")
    inp.click()
    page.wait_for_timeout(500)

    prompt = (
        "Create a 5-second cinematic video: "
        "Hyper-realistic live-action anime adaptation of Naruto Uzumaki crouched on wet stone in pouring rain. "
        "Spiky blonde wet hair blowing in wind, dramatic camera push-in to his face with glowing feral orange Nine-Tails "
        "fox slit eyes, whisker marks, raising right hand as violently spinning cyan and golden Rasengan chakra sphere "
        "churns with wind distortion and blinding electrical arcs. Fluid realistic human motion, 8k cinematic."
    )

    inp.fill(prompt)
    page.wait_for_timeout(1000)
    page.keyboard.press("Enter")
    page.wait_for_timeout(3000)

    send_btn = page.locator('button:has(i:has-text("arrow_forward")), button[aria-label*="Submit"]').first
    try:
        if send_btn.is_visible(timeout=1000):
            send_btn.click()
    except: pass

    # Check if approval button appears
    try:
        appr = page.locator('button:has-text("Approve")').first
        if appr.is_visible(timeout=3000):
            print("Clicking approve...")
            appr.click()
            page.wait_for_timeout(2000)
    except: pass

    print("Prompt submitted! Waiting for Naruto Veo 2 video to generate (approx 90-120s)...")
    page.screenshot(path="naruto_video_generating.png")

    new_video_src = None
    for sec in range(25): # 150s
        page.wait_for_timeout(6000)
        vids = page.locator('video').all()
        for v in vids:
            s = v.get_attribute("src")
            if s and s not in existing_vids:
                new_video_src = s
                break
        if new_video_src:
            print(f"Found new video element! URL: {new_video_src[:80]}...")
            break
        print(f"  Rendering Naruto video ({ (sec+1)*6 }s)...")

    if new_video_src:
        resp = page.request.get(new_video_src)
        if resp.status == 200:
            dest_file.write_bytes(resp.body())
            print(f"SUCCESS! Downloaded {dest_file.name} ({dest_file.stat().st_size} bytes)")
    else:
        print("Naruto video generation timed out or still rendering.")
        page.screenshot(path="naruto_video_wait_end.png")

    ctx.close()
