"""
Generate Scene 6 directly inside Google Flow project 5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91,
download the new clip via CDN, verify uniqueness, and composite all 6 scenes.
"""
import sys, os, json, subprocess, requests, hashlib, time
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"
scene6_path = clips_dir / "scene_06.mp4"
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

# Existing 5 clips hashes
existing_hashes = {}
for i in range(1, 6):
    p = clips_dir / f"scene_{i:02d}.mp4"
    if p.exists():
        existing_hashes[i] = hashlib.md5(open(p, "rb").read()).hexdigest()

print("Existing clip hashes:", flush=True)
for k, v in existing_hashes.items():
    print(f"  Scene {k}: {v[:12]}", flush=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900},
        accept_downloads=True
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    all_video_responses = []
    def on_resp(r):
        if "flow-content.google/video" in r.url:
            vid = r.url.split("/video/")[1].split("?")[0]
            all_video_responses.append({"url": r.url, "id": vid})
            print(f"  [NET] Captured video ID: {vid}", flush=True)
    page.on("response", on_resp)

    print(f"Navigating to project {PROJECT_URL}...", flush=True)
    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    # Initial known IDs
    initial_ids = set(v["id"] for v in all_video_responses)
    print(f"Initial video IDs on page: {initial_ids}", flush=True)

    # Find the prompt input box in project
    chat_input = page.locator('[contenteditable="true"], textarea, input[type="text"]').first
    if not chat_input.is_visible(timeout=5000):
        # Click near bottom chat bar area
        page.mouse.click(640, 850)
        page.wait_for_timeout(1000)
        chat_input = page.locator('[contenteditable="true"], textarea').first

    prompt_text = (
        "Cinematic vertical 9:16 video: A lone human silhouette stands on a rocky cliff overlooking a twilight horizon. "
        "The sky is dramatically split between starry icy twilight on the left and glowing volcanic amber on the right. "
        "Photorealistic 8K National Geographic documentary, slow epic camera push-in."
    )

    print("Typing Scene 6 prompt...", flush=True)
    chat_input.click()
    page.keyboard.type(prompt_text, delay=2)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    print("Submitted prompt. Approving generation...", flush=True)
    page.wait_for_timeout(4000)

    # Look for approve / generate button
    for _ in range(8):
        btns = page.locator('button:has-text("Approve"), button:has-text("Generate"), button:has-text("Create")')
        if btns.count() > 0:
            btns.last.click(force=True)
            print("Clicked Approve button!", flush=True)
            break
        page.wait_for_timeout(2000)

    # Wait for the newly generated video card
    print("Waiting for generation to finish (~90-120s)...", flush=True)
    new_video_url = None
    for i in range(20):
        page.wait_for_timeout(10000)
        # Check if new video ID appeared in network responses
        new_items = [v for v in all_video_responses if v["id"] not in initial_ids]
        if new_items:
            new_video_url = new_items[-1]["url"]
            print(f"New video ready! ID: {new_items[-1]['id']}", flush=True)
            break
        print(f"  Waiting... {(i+1)*10}s", flush=True)

    # If not triggered automatically, click on the right-most (newest) card on the canvas
    if not new_video_url:
        print("Clicking latest card on canvas...", flush=True)
        cards = page.locator('img[src*="googleusercontent"]')
        if cards.count() > 0:
            cards.last.click(force=True)
            page.wait_for_timeout(2000)
            page.evaluate("document.querySelector('video')?.play()")
            page.wait_for_timeout(5000)
            new_items = [v for v in all_video_responses if v["id"] not in initial_ids]
            if new_items:
                new_video_url = new_items[-1]["url"]

    cookies = ctx.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    ctx.close()

if not new_video_url:
    print("ERROR: Could not get new video URL", flush=True)
    sys.exit(1)

print(f"Downloading Scene 6 from: {new_video_url[:80]}...", flush=True)
resp = requests.get(new_video_url, headers={"Cookie": cookie_str}, stream=True, timeout=60)
if resp.status_code == 200:
    with open(scene6_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    sz = scene6_path.stat().st_size
    print(f"Scene 6 saved: {sz // 1024} KB", flush=True)
else:
    print(f"Download failed: {resp.status_code}", flush=True)
    sys.exit(1)

# Check uniqueness
s6_hash = hashlib.md5(open(scene6_path, "rb").read()).hexdigest()
is_dup = False
for k, v in existing_hashes.items():
    if v == s6_hash:
        print(f"WARNING: Matches Scene {k}!", flush=True)
        is_dup = True

if is_dup:
    print("Failed uniqueness check.", flush=True)
    sys.exit(1)
else:
    print("SUCCESS: Scene 6 is 100% unique!", flush=True)

# Update Storyboard to 6 Scenes
sb_6 = {
    "title": "What If Earth Stopped Spinning?",
    "target_duration_sec": 52,
    "scenes": [
        {"scene_number": 1, "name": "The Instant Cataclysm",
         "narration": "If Earth stopped spinning for even one second, you wouldn't just fall over. You would be launched east at a thousand miles per hour.",
         "visual_prompt": "Earth in space", "estimated_duration_sec": 7},
        {"scene_number": 2, "name": "Supersonic Atmospheric Winds",
         "narration": "Because the atmosphere keeps moving at rotational speed, supersonic winds over 1,000 miles an hour would instantly wipe entire cities off the map.",
         "visual_prompt": "City destruction", "estimated_duration_sec": 9},
        {"scene_number": 3, "name": "The Mega-Tsunami Ocean Surge",
         "narration": "The oceans would slosh violently toward the poles, creating colossal global tsunamis towering miles high, swallowing continents in minutes.",
         "visual_prompt": "Mega tsunami", "estimated_duration_sec": 10},
        {"scene_number": 4, "name": "Magnetic Shield Collapse",
         "narration": "Without rotation, Earth's liquid metal core stops churning, destroying our magnetic shield and exposing the surface to deadly cosmic radiation.",
         "visual_prompt": "Aurora collapse", "estimated_duration_sec": 10},
        {"scene_number": 5, "name": "Half Frozen, Half Scorched",
         "narration": "One side of the planet would endure six months of scorching daylight, while the other freezes in eternal darkness.",
         "visual_prompt": "Split planet", "estimated_duration_sec": 9},
        {"scene_number": 6, "name": "The Twilight Payoff",
         "narration": "The only place you could survive? A narrow, twilight strip between fire and ice. Would you make it?",
         "visual_prompt": "Twilight silhouette", "estimated_duration_sec": 7}
    ]
}
with open(proj_dir / "storyboard.json", "w", encoding="utf-8") as f:
    json.dump(sb_6, f, indent=2)

# Generate 6-scene voiceover with ElevenLabs
print("Generating 6-scene voiceover...", flush=True)
from pipeline.stage3_voiceover import build_full_script, generate_voiceover_elevenlabs
script = build_full_script(sb_6)
generate_voiceover_elevenlabs(script, proj_dir / "narration.mp3", proj_dir / "words.json")

# Compute word-level sentence cuts
with open(proj_dir / "words.json", "r", encoding="utf-8") as f:
    wd = json.load(f)
wl = wd.get("words", [])
wi = 0
sd = []
for sc in sb_6["scenes"]:
    sw = sc["narration"].split()
    s = wl[wi]["start"] if wi < len(wl) else 0.0
    wi += len(sw)
    e = wl[min(wi-1, len(wl)-1)]["end"] if wi-1 < len(wl) else s+8.0
    d = max(3.0, e - s)
    sd.append((sc["scene_number"], d, sc["name"]))
    print(f"  Scene {sc['scene_number']} ({sc['name']}): {d:.2f}s", flush=True)

# Trim clips to exact narration
trimmed = []
for num, dur, nm in sd:
    src = clips_dir / f"scene_{num:02d}.mp4"
    out = clips_dir / f"trimmed_scene_{num:02d}.mp4"
    subprocess.run([
        config.FFMPEG_EXE, "-y", "-i", str(src),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an", str(out)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    trimmed.append(out)

cf = clips_dir / "concat_perfect.txt"
with open(cf, "w", encoding="utf-8") as f:
    for t in trimmed:
        f.write(f"file '{str(t).replace(chr(92), '/')}'\n")

raw = clips_dir / "concatenated_perfect.mp4"
subprocess.run([
    config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0",
    "-i", str(cf), "-c", "copy", str(raw)
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

from pipeline.stage4_subtitles import generate_ass_subtitles
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration
cap = proj_dir / "captions.ass"
generate_ass_subtitles(proj_dir / "words.json", cap)
narr = proj_dir / "narration.mp3"
mus = clips_dir / "background_music.aac"
td = get_media_duration(narr)
generate_ambient_music_track(mus, td + 2.0)

out = proj_dir / "output" / "final_short.mp4"
af = (
    f"[1:a]volume={config.VOICE_VOLUME_DB}dB,asplit=2[v0][vs];"
    f"[2:a]volume={config.MUSIC_VOLUME_DB}dB[m];"
    f"[m][vs]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[md];"
    f"[v0][md]amix=inputs=2:duration=first:dropout_transition=2[ao]"
)
ass = str(cap).replace("\\", "/").replace(":", "\\:")
r = subprocess.run([
    config.FFMPEG_EXE, "-y",
    "-i", str(raw), "-i", str(narr), "-i", str(mus),
    "-filter_complex", af, "-map", "0:v", "-map", "[ao]",
    "-vf", f"subtitles='{ass}'",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", config.AUDIO_BITRATE,
    "-t", f"{td:.3f}", "-pix_fmt", "yuv420p", str(out)
], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

if r.returncode != 0:
    print(f"Render error: {r.stderr[-300:]}", flush=True)
    sys.exit(1)

# Sync to Google Drive
drive_dir = Path("G:/My Drive/YouTube Shorts")
if drive_dir.exists():
    import shutil
    shutil.copy2(out, drive_dir / "earth_stops_rotating_6scenes.mp4")
    print(f"Copied to Drive: {drive_dir / 'earth_stops_rotating_6scenes.mp4'}", flush=True)

print(f"\n=======================================================", flush=True)
print(f"ALL 6 UNIQUE SCENES GENERATED & RENDERED SUCCESSFULLY!", flush=True)
print(f"File: {out} ({out.stat().st_size // (1024*1024)} MB)", flush=True)
print(f"=======================================================", flush=True)
