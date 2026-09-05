from playwright.sync_api import sync_playwright
from pathlib import Path

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_file = Path("projects/08_naruto_vs_sasuke/renders/sasuke_realistic_8k.png")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(p_dir),
        headless=True,
        channel="chrome",
        args=["--no-first-run"]
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(proj_url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Fetch with browser session
    media_url = "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=8487c67e-a806-4535-bf14-6780ee4a07a8"
    response = page.request.get(media_url)
    if response.status == 200:
        out_file.write_bytes(response.body())
        print(f"SUCCESS! Downloaded full resolution asset to {out_file.name} ({out_file.stat().st_size} bytes)")
    else:
        print("Fetch failed with status:", response.status)

    ctx.close()
