from playwright.sync_api import sync_playwright
from pathlib import Path

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()
out_dir = Path("projects/08_naruto_vs_sasuke/real_videos")
out_dir.mkdir(parents=True, exist_ok=True)
dest_file = out_dir / "sasuke_real_motion_video.mp4"

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

    video_url = "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=8d6c01ad-499c-4ebe-97ea-dec4b70566b1"
    print("Fetching real AI video stream from Google Flow...")
    resp = page.request.get(video_url)
    print(f"Status: {resp.status} | Content-Type: {resp.headers.get('content-type')}")
    
    if resp.status == 200:
        dest_file.write_bytes(resp.body())
        print(f"SUCCESS! Downloaded real motion video: {dest_file.name} ({dest_file.stat().st_size} bytes)")
    else:
        print("Failed to download video directly.")

    ctx.close()
