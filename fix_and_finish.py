"""
Generate Scene 6 as a NEW card in Google Flow, download via CDN, verify unique, re-render 6-scene video.
"""
import sys, os, json, subprocess, requests, hashlib, time
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from playwright.sync_api import sync_playwright

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"
scene6_path = clips_dir / "scene_06.mp4"

# Get hashes of existing 5 clips to guarantee uniqueness
existing_hashes = {}
for i in range(1, 6):
    p = clips_dir / f"scene_{i:02d}.mp4"
    existing_hashes[i] = hashlib.md5(open(p, "rb").read()).hexdigest()

print("=" * 50, flush=True)
print("GENERATING UNIQUE SCENE 6 IN GOOGLE FLOW", flush=True)
print("=" * 50, flush=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR), headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900}, accept_downloads=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    # Track video network requests
    all_video_ids = []
    def on_resp(r):
        if "flow-content.google/video" in r.url:
            vid_id = r.url.split("/video/")[1].split("?")[0]
            all_video_ids.append({"url": r.url, "id": vid_id})
    page.on("response", on_resp)

    # Go to Flow home and start NEW project
    page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Record any existing video IDs on the page (from home)
    pre_ids = set(v["id"] for v in all_video_ids)
    print(f"Pre-existing video IDs: {len(pre_ids)}", flush=True)

    # Type the Scene 6 prompt
    prompt = (
        "Generate a cinematic 9:16 vertical video: "
        "A lone human silhouette stands on a rocky cliff at golden hour twilight. "
        "Behind them, one side of the sky is deep frozen blue with stars, "
        "the other side blazes orange-red with volcanic heat waves. "
        "A narrow golden twilight strip divides the horizon. "
        "Slow dramatic camera push-in. Photorealistic National Geographic 8K."
    )
    
    chat_in = page.locator('[contenteditable="true"]').first
    if chat_in.is_visible(timeout=5000):
        chat_in.click()
        page.keyboard.type(prompt, delay=2)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        print("Prompt submitted!", flush=True)
        page.wait_for_timeout(4000)

        # Auto-approve
        for _ in range(8):
            btns = page.locator('button:has-text("Approve"), button:has-text("Generate"), button:has-text("Create")')
            if btns.count() > 0:
                btns.last.click(force=True)
                print("Approved!", flush=True)
                break
            page.wait_for_timeout(2000)
    else:
        print("Chat input not found!", flush=True)

    # Wait for NEW video ID to appear (up to 3 min)
    print("Waiting for video to render...", flush=True)
    new_url = None
    for i in range(18):
        time.sleep(10)
        new_entries = [v for v in all_video_ids if v["id"] not in pre_ids]
        if new_entries:
            new_url = new_entries[-1]["url"]
            new_id = new_entries[-1]["id"]
            print(f"NEW video rendered at {(i+1)*10}s! ID: {new_id}", flush=True)
            break
        print(f"   {(i+1)*10}s...", flush=True)

    if not new_url:
        # Try clicking any visible card
        print("No new ID via network. Trying to click card...", flush=True)
        cards = page.locator('img[src*="googleusercontent"]')
        if cards.count() > 0:
            cards.last.click(force=True)
            page.wait_for_timeout(2000)
            page.evaluate("document.querySelector('video')?.play()")
            page.wait_for_timeout(5000)
            new_entries = [v for v in all_video_ids if v["id"] not in pre_ids]
            if new_entries:
                new_url = new_entries[-1]["url"]
                print(f"Got URL from card click!", flush=True)

    cookies = ctx.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    ctx.close()

if not new_url:
    print("FAILED: No new video generated.", flush=True)
    sys.exit(1)

# Download
print("\nDownloading Scene 6...", flush=True)
resp = requests.get(new_url, headers={"Cookie": cookie_str}, stream=True, timeout=30)
with open(scene6_path, "wb") as f:
    for chunk in resp.iter_content(chunk_size=8192):
        f.write(chunk)
sz = scene6_path.stat().st_size
print(f"Saved: {sz // 1024} KB", flush=True)

# Verify unique
s6h = hashlib.md5(open(scene6_path, "rb").read()).hexdigest()
is_unique = True
for i, h in existing_hashes.items():
    if h == s6h:
        print(f"DUPLICATE with scene_{i:02d}!", flush=True)
        is_unique = False
if is_unique:
    print("VERIFIED UNIQUE vs all 5 existing clips!", flush=True)
else:
    print("FAILED uniqueness check.", flush=True)
    sys.exit(1)

# Restore 6-scene storyboard
print("\nRestoring 6-scene storyboard...", flush=True)
storyboard = {
    "title": "What If Earth Stopped Spinning?",
    "target_duration_sec": 52,
    "scenes": [
        {"scene_number": 1, "name": "The Instant Cataclysm (Hook)",
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
    json.dump(storyboard, f, indent=2)

# Re-generate voiceover for 6 scenes
print("Generating 6-scene voiceover...", flush=True)
from pipeline.stage3_voiceover import build_full_script, generate_voiceover_elevenlabs
script = build_full_script(storyboard)
generate_voiceover_elevenlabs(script, proj_dir / "narration.mp3", proj_dir / "words.json")

# Compute sentence cuts
with open(proj_dir / "words.json", "r", encoding="utf-8") as f:
    wd = json.load(f)
wl = wd.get("words", [])
wi = 0
sd = []
for sc in storyboard["scenes"]:
    sw = sc["narration"].split()
    s = wl[wi]["start"] if wi < len(wl) else 0.0
    wi += len(sw)
    e = wl[min(wi-1, len(wl)-1)]["end"] if wi-1 < len(wl) else s+8.0
    d = max(3.0, e - s)
    sd.append((sc["scene_number"], d, sc["name"]))
    print(f"   Scene {sc['scene_number']} ({sc['name']}): {d:.2f}s", flush=True)

# Trim + concat
tr = []
for num, dur, nm in sd:
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

# Captions + music + final render
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
    print(f"Render error: {r.stderr[-300:]}", flush=True)
    sys.exit(1)

# Copy to Drive
import shutil
drive_out = Path("G:/My Drive/YouTube Shorts/earth_stops_rotating.mp4")
shutil.copy2(out, drive_out)

print(f"\n{'='*50}", flush=True)
print(f"DONE! 6 UNIQUE SCENES, ZERO DUPLICATES", flush=True)
print(f"Local: {out} ({out.stat().st_size//(1024*1024)} MB)", flush=True)
print(f"Drive: {drive_out}", flush=True)
print(f"{'='*50}", flush=True)
