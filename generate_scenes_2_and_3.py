from playwright.sync_api import sync_playwright
from pathlib import Path
import time

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_dir = Path("projects/08_naruto_vs_sasuke/renders")
out_dir.mkdir(parents=True, exist_ok=True)

prompts = [
    {
        "name": "naruto_realistic_8k",
        "text": (
            "Vertical 9:16 cinematic action film scene. Hyper-realistic live-action adaptation of Naruto Uzumaki standing atop "
            "a massive ancient weathered stone monument during a midnight thunderstorm in torrential pouring rain. "
            "Intense dramatic close-up of his face: spiky wet blonde hair, whisker marks on his cheeks, glowing feral golden-orange "
            "Nine-Tails fox slit eyes. Battle-damaged orange and black shinobi outfit soaked in rain. In his right palm, "
            "he holds a violently spinning, turbulent cyan and golden Rasengan chakra vortex sphere, radiating howling wind distortion, "
            "blinding white-blue sparks, and water droplets exploding outward. 8k, photorealistic, anamorphic 35mm lens, "
            "atmospheric volumetric haze, moody dark cinematic lighting."
        )
    },
    {
        "name": "clash_realistic_8k",
        "text": (
            "Vertical 9:16 cinematic epic action climax. Hyper-realistic live-action adaptation of Naruto and Sasuke leaping "
            "toward each other in mid-air in slow motion over a massive waterfall canyon in pouring rain. Extreme collision moment: "
            "Sasuke thrusting his pitch-black lightning and purple plasma Chidori directly into Naruto's violently churning "
            "blue and golden Rasengan sphere in dead center frame. Massive blinding shockwave explosion expanding between them, "
            "tearing raindrops apart into glowing plasma mist, electrical arcs shattering stone debris, blinding spherical gravitational distortion. "
            "8k, photorealistic, IMAX action cinematography, intense cinematic lighting."
        )
    }
]

print("Connecting to Flow to generate Naruto and Clash scenes...")

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

    for item in prompts:
        name = item["name"]
        prompt_text = item["text"]
        print(f"\n--- Submitting prompt for: {name} ---")
        
        # Get count of media before submission
        before_count = page.evaluate("() => document.querySelectorAll('img[src*=\"getMediaUrlRedirect\"]').length")
        
        inp = page.locator('[contenteditable="true"]').first
        inp.click()
        inp.fill(prompt_text)
        page.wait_for_timeout(1000)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)
        
        send_btn = page.locator('button:has-text("arrow_forward"), button[aria-label*="Submit"]').first
        try:
            if send_btn.is_visible(timeout=1000):
                send_btn.click()
        except: pass
        
        print("Waiting for generation to complete (approx 60-90s)...")
        # Wait until a new media item appears
        new_media_url = None
        for i in range(25): # 25 * 6s = 150s max
            page.wait_for_timeout(6000)
            media_list = page.evaluate('''() => {
                const list = [];
                document.querySelectorAll('img[src*="getMediaUrlRedirect"]').forEach(el => list.push(el.src));
                return list;
            }''')
            if len(media_list) > before_count:
                new_media_url = media_list[-1]
                print(f"Detected new media render! URL: {new_media_url[:80]}...")
                break
            print(f"  Still rendering ({ (i+1)*6 }s)...")
            
        if new_media_url:
            dest_file = out_dir / f"{name}.png"
            resp = page.request.get(new_media_url)
            if resp.status == 200:
                dest_file.write_bytes(resp.body())
                print(f"SUCCESS! Downloaded {dest_file.name} ({dest_file.stat().st_size} bytes)")
            else:
                print("Download failed status:", resp.status)
        else:
            print(f"Timed out waiting for {name} render.")
            page.screenshot(path=f"projects/08_naruto_vs_sasuke/timeout_{name}.png")

    ctx.close()
print("\nAll prompt cycles completed!")
