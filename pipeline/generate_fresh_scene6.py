"""
Generate Scene 6 in Google Flow: submit prompt, wait for render, intercept CDN, download, audit, render final.
"""
import sys, os, json, subprocess, requests, hashlib
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

clips_dir = config.PROJECTS_DIR / "earth_stops_rotating" / "clips"
proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
scene6_path = clips_dir / "scene_06.mp4"
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

# Known video IDs for existing clips (so we skip them)
known_ids = set()

print("=== GENERATING UNIQUE SCENE 6 ===", flush=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR), headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900}, accept_downloads=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    # Track all video IDs
    all_ids = []
    def on_resp(r):
        if "flow-content.google/video" in r.url:
            vid = r.url.split("/video/")[1].split("?")[0]
            all_ids.append({"url": r.url, "id": vid})
    page.on("response", on_resp)

    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Record existing video IDs by clicking each card
    for cx in [300, 470, 640, 810]:
        page.mouse.click(cx, 210)
        page.wait_for_timeout(2000)
        page.evaluate("document.querySelector('video')?.play()")
        page.wait_for_timeout(3000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

    known_ids = set(v["id"] for v in all_ids)
    print(f"Known video IDs (4 existing): {known_ids}", flush=True)

    # Submit Scene 6 prompt
    print("\nSubmitting Scene 6 prompt...", flush=True)
    chat_in = page.locator('[contenteditable="true"]').first
    if chat_in.is_visible(timeout=5000):
        chat_in.click()
        prompt = (
            "Create a cinematic 9:16 vertical video: "
            "A lone silhouetted human figure standing on a mountain ridge at twilight. "
            "One side of the sky is deep violet-blue with stars, the other is warm amber-gold. "
            "A thin glowing golden line divides the horizon. Slow dramatic camera movement. "
            "Photorealistic National Geographic documentary quality."
        )
        page.keyboard.type(prompt, delay=2)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(4000)

        # Auto-approve
        for _ in range(6):
            btns = page.locator('button:has-text("Approve"), button:has-text("Generate")')
            if btns.count() > 0:
                btns.last.click(force=True)
                print("Approved!", flush=True)
                break
            page.wait_for_timeout(2000)

    # Wait for render (check for NEW video ID)
    print("Waiting for new video to render...", flush=True)
    new_url = None
    for i in range(24):  # up to 4 minutes
        page.wait_for_timeout(10000)
        new_ids = [v for v in all_ids if v["id"] not in known_ids]
        if new_ids:
            new_url = new_ids[-1]["url"]
            new_id = new_ids[-1]["id"]
            print(f"   NEW video ID detected at {(i+1)*10}s: {new_id}", flush=True)
            break
        print(f"   {(i+1)*10}s - still waiting...", flush=True)

    cookies = ctx.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    ctx.close()

if not new_url:
    print("ERROR: No new video generated after 4 min", flush=True)
    sys.exit(1)

# Download the new Scene 6
print(f"\nDownloading new Scene 6...", flush=True)
resp = requests.get(new_url, headers={"Cookie": cookie_str}, stream=True, timeout=30)
with open(scene6_path, "wb") as f:
    for chunk in resp.iter_content(chunk_size=8192):
        f.write(chunk)
print(f"Saved: {scene6_path.stat().st_size // 1024} KB", flush=True)

# Verify unique
s6h = hashlib.md5(open(scene6_path, "rb").read()).hexdigest()
for i in range(1, 6):
    sp = clips_dir / f"scene_{i:02d}.mp4"
    sh = hashlib.md5(open(sp, "rb").read()).hexdigest()
    status = "DUPLICATE!" if sh == s6h else "unique"
    print(f"   vs scene_{i:02d}: {status}", flush=True)

# Audit
print("\nGemini AI Audit...", flush=True)
from pipeline.gemini_video_reviewer import gemini_full_video_review
audit = gemini_full_video_review(proj_dir)
passed = audit["passed"]
print(f"PASSED: {passed}", flush=True)
if not passed:
    print("Audit failed.", flush=True)
    sys.exit(1)

# Render
print("\nRendering final video...", flush=True)
with open(proj_dir / "words.json", "r", encoding="utf-8") as f:
    wd = json.load(f)
with open(proj_dir / "storyboard.json", "r", encoding="utf-8") as f:
    sb = json.load(f)
wl = wd.get("words", [])
wi = 0
sd = []
for sc in sb["scenes"]:
    sw = sc["narration"].split()
    s = wl[wi]["start"] if wi < len(wl) else 0.0
    wi += len(sw)
    e = wl[min(wi-1, len(wl)-1)]["end"] if wi-1 < len(wl) else s+8.0
    d = max(3.0, e - s)
    sd.append((sc["scene_number"], d))

tr = []
for num, dur in sd:
    src = clips_dir / f"scene_{num:02d}.mp4"
    out = clips_dir / f"trimmed_scene_{num:02d}.mp4"
    subprocess.run([config.FFMPEG_EXE, "-y", "-i", str(src),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an", str(out)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    tr.append(out)

cf = clips_dir / "concat_perfect.txt"
with open(cf, "w", encoding="utf-8") as f:
    for t in tr:
        f.write(f"file '{str(t).replace(chr(92), '/')}'\n")
raw = clips_dir / "concatenated_perfect.mp4"
subprocess.run([config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", str(cf), "-c", "copy", str(raw)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

from pipeline.stage4_subtitles import generate_ass_subtitles
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration
cap = proj_dir / "captions.ass"
generate_ass_subtitles(proj_dir / "words.json", cap)
narr = proj_dir / "narration.mp3"
mus = clips_dir / "background_music.aac"
td = get_media_duration(narr)
generate_ambient_music_track(mus, td + 2.0)

out = proj_dir / "output" / "final_short.mp4"
af = (f"[1:a]volume={config.VOICE_VOLUME_DB}dB,asplit=2[v0][vs];"
      f"[2:a]volume={config.MUSIC_VOLUME_DB}dB[m];"
      f"[m][vs]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[md];"
      f"[v0][md]amix=inputs=2:duration=first:dropout_transition=2[ao]")
ass = str(cap).replace("\\", "/").replace(":", "\\:")
r = subprocess.run([config.FFMPEG_EXE, "-y", "-i", str(raw), "-i", str(narr), "-i", str(mus),
    "-filter_complex", af, "-map", "0:v", "-map", "[ao]",
    "-vf", f"subtitles='{ass}'", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", config.AUDIO_BITRATE, "-t", f"{td:.3f}", "-pix_fmt", "yuv420p", str(out)],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
if r.returncode != 0:
    print(f"Error: {r.stderr[-300:]}", flush=True)
else:
    print(f"\nDONE! {out} ({out.stat().st_size//(1024*1024)} MB)", flush=True)
