from playwright.sync_api import sync_playwright
from pathlib import Path

proj_url = "https://labs.google/fx/tools/flow/project/785f3e5a-d280-4540-853b-5420f90f475d"
p_dir = Path("browser/flow_profile_4").resolve()

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

    # Screenshot the current screen and chat
    page.screenshot(path="flow_latest_status.png")
    print("Saved flow_latest_status.png")

    # Check the chat messages
    messages = page.evaluate('''() => {
        const list = [];
        document.querySelectorAll('div').forEach(d => {
            const t = d.innerText;
            if (t && (t.includes('video') || t.includes('Naruto') || t.includes('credits') || t.includes('Approve'))) {
                list.push(t.substring(0, 150));
            }
        });
        return list;
    }''')
    print("Chat snippets:", len(messages))

    # Check all video elements
    vids = page.evaluate('''() => {
        const list = [];
        document.querySelectorAll('video').forEach(v => {
            list.push({
                src: v.src || v.currentSrc,
                width: v.videoWidth,
                height: v.videoHeight,
                duration: v.duration
            });
        });
        return list;
    }''')
    print("Video elements on page:", vids)

    ctx.close()
