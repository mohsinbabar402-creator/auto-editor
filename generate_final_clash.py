from playwright.sync_api import sync_playwright
from pathlib import Path
import shutil

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_dir = Path("projects/08_naruto_vs_sasuke/renders")

# First, rename current clash_realistic_8k.png (which is actually Naruto) to naruto_realistic_8k.png
src_naruto = out_dir / "clash_realistic_8k.png"
dst_naruto = out_dir / "naruto_realistic_8k.png"
if src_naruto.exists():
    shutil.copy2(src_naruto, dst_naruto)
    print("Properly saved Naruto asset as naruto_realistic_8k.png")

clash_prompt = (
    "Vertical 9:16 cinematic IMAX action climax. Hyper-realistic live-action adaptation of Naruto Uzumaki "
    "and Sasuke Uchiha colliding in mid-air in slow motion over a stormy waterfall chasm in pouring rain. "
    "Extreme impact moment: Sasuke thrusting his pitch-black lightning and purple plasma Chidori directly "
    "into Naruto's roaring spiraling cyan and golden Rasengan sphere dead center frame. "
    "Titanic blinding spherical shockwave explosion tearing the rain apart into glowing energy droplets, "
    "plasma shockwave rings radiating outward, blinding contrast, 8k, photorealistic live-action movie frame, "
    "hyper-realistic facial battle expressions."
)

print("Connecting to Google Flow to generate the mid-air Rasengan vs Chidori clash...")

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

    # Count existing media
    before_urls = set(page.evaluate('''() => {
        const list = [];
        document.querySelectorAll('img[src*="getMediaUrlRedirect"]').forEach(el => list.push(el.src));
        return list;
    }'''))
    print(f"Existing media items in project: {len(before_urls)}")

    inp = page.locator('[contenteditable="true"]').first
    inp.click()
    inp.fill(clash_prompt)
    page.wait_for_timeout(1000)
    page.keyboard.press("Enter")
    page.wait_for_timeout(3000)

    send_btn = page.locator('button:has-text("arrow_forward"), button[aria-label*="Submit"]').first
    try:
        if send_btn.is_visible(timeout=1000):
            send_btn.click()
    except: pass

    print("Prompt submitted! Waiting for Google Flow to render the clash scene...")
    clash_url = None
    for i in range(25):
        page.wait_for_timeout(6000)
        current_urls = page.evaluate('''() => {
            const list = [];
            document.querySelectorAll('img[src*="getMediaUrlRedirect"]').forEach(el => list.push(el.src));
            return list;
        }''')
        new_ones = [u for u in current_urls if u not in before_urls]
        if new_ones:
            clash_url = new_ones[-1]
            print(f"Detected new clash render! URL: {clash_url[:80]}...")
            break
        print(f"  Rendering clash ({ (i+1)*6 }s)...")

    if clash_url:
        dest = out_dir / "clash_explosion_8k.png"
        resp = page.request.get(clash_url)
        if resp.status == 200:
            dest.write_bytes(resp.body())
            print(f"SUCCESS! Downloaded {dest.name} ({dest.stat().st_size} bytes)")
        else:
            print("Download failed status:", resp.status)
    else:
        print("Clash render timed out.")

    ctx.close()
