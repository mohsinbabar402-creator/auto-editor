from playwright.sync_api import sync_playwright
from pathlib import Path
import json

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

    trpc_data = []
    def on_response(res):
        if "trpc" in res.url:
            try:
                ct = res.headers.get("content-type", "")
                if "json" in ct:
                    data = res.json()
                    trpc_data.append({"url": res.url, "data": data})
            except: pass
    page.on("response", on_response)

    print("Navigating to Flow project and capturing API responses...")
    page.goto(proj_url, wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(3000)

    print(f"Captured {len(trpc_data)} tRPC responses:")
    for item in trpc_data:
        u = item["url"]
        print("  API URL:", u[:100])
        # Check if project data or media assets are returned
        d = item["data"]
        # Save to file if it contains assets
        if "result" in d:
            r = d["result"].get("data", {})
            if isinstance(r, dict) and any(k in r for k in ["assets", "nodes", "media", "project", "canvas"]):
                print(f"    Found rich project data with keys: {list(r.keys())}")
                with open("flow_project_dump.json", "w", encoding="utf-8") as f:
                    json.dump(d, f, indent=2)

    page.screenshot(path="project_loaded_clean.png")
    ctx.close()
