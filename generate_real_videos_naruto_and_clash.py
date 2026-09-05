from playwright.sync_api import sync_playwright
from pathlib import Path
import time

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_dir = Path("projects/08_naruto_vs_sasuke/real_videos")
out_dir.mkdir(parents=True, exist_ok=True)

prompts = [
    {
        "name": "naruto_real_motion_video.mp4",
        "text": (
            "Create a 5-second cinematic video: "
            "Hyper-realistic live-action anime adaptation of Naruto Uzumaki crouched on wet stone in pouring rain. "
            "Spiky blonde wet hair blowing in wind, dramatic camera push-in to his face with glowing feral orange Nine-Tails "
            "fox slit eyes, whisker marks, raising right hand as violently spinning cyan and golden Rasengan chakra sphere "
            "churns with wind distortion and blinding electrical arcs. Fluid human motion, 8k cinematic."
        )
    },
    {
        "name": "clash_real_motion_video.mp4",
        "text": (
            "Create a 5-second cinematic video: "
            "Hyper-realistic live-action adaptation of Naruto Uzumaki and Sasuke Uchiha colliding in mid-air over massive "
            "waterfall in pouring rain. Slow motion collision of Sasuke's pitch-black lightning Chidori clashing directly into "
            "Naruto's glowing golden-blue Rasengan sphere, blinding spherical shockwave explosion erupting between them, "
            "plasma arcs tearing through the waterfalls and rain. Dynamic IMAX camera motion, 8k cinematic."
        )
    }
]

print("Connecting to Google Flow to generate Naruto and Clash real motion videos...")

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

    # Click back if inside card view
    page.mouse.click(35, 35)
    page.wait_for_timeout(2000)

    for item in prompts:
        out_name = item["name"]
        prompt_text = item["text"]
        dest = out_dir / out_name
        print(f"\n==========================================")
        print(f"Submitting real video prompt for: {out_name}")
        print(f"==========================================")

        # Count videos before
        existing_vids = set(page.evaluate('''() => {
            const list = [];
            document.querySelectorAll('video, a[href*="getMediaUrlRedirect"]').forEach(el => {
                const s = el.src || el.href;
                if (s) list.push(s);
            });
            return list;
        }'''))
        print(f"Existing video elements: {len(existing_vids)}")

        inp = page.locator('[contenteditable="true"]').first
        inp.click()
        inp.fill(prompt_text)
        page.wait_for_timeout(1000)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)

        # Check if approval button appears or if auto-approved
        approve = page.locator('button:has-text("Approve")').first
        if approve.is_visible(timeout=3000):
            print("Clicking Approve...")
            approve.click()
            page.wait_for_timeout(3000)

        print("Waiting for Veo 2 video rendering (approx 90-120s)...")
        new_video_url = None
        for sec in range(25): # 25 * 6s = 150s
            page.wait_for_timeout(6000)
            current_vids = page.evaluate('''() => {
                const list = [];
                document.querySelectorAll('video, [src*="getMediaUrlRedirect"]').forEach(el => {
                    const s = el.src || el.currentSrc;
                    if (s) list.push(s);
                });
                return list;
            }''')
            # Look for video elements
            v_elements = page.locator('video').all()
            for v in v_elements:
                s = v.get_attribute("src")
                if s and s not in existing_vids:
                    new_video_url = s
                    break
            if new_video_url:
                print(f"Found new video element! URL: {new_video_url[:80]}...")
                break
            print(f"  Rendering ({ (sec+1)*6 }s)...")

        if new_video_url:
            resp = page.request.get(new_video_url)
            if resp.status == 200:
                dest.write_bytes(resp.body())
                print(f"SUCCESS! Downloaded {dest.name} ({dest.stat().st_size} bytes)")
            else:
                print("Download failed status:", resp.status)
        else:
            print(f"Timed out waiting for {out_name}.")
            page.screenshot(path=f"timeout_{out_name}.png")

    ctx.close()
print("\nAll video generation finished!")
