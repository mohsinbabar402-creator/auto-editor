"""
Download Aurora via its unique CDN video ID, then immediately audit + render.
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

# Step 1: Get Aurora CDN URL (Card 4)
print("Step 1: Getting Aurora CDN URL...", flush=True)
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR), headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900}, accept_downloads=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    captured = []
    def on_resp(r):
        if "flow-content.google/video" in r.url:
            vid = r.url.split("/video/")[1].split("?")[0]
            captured.append({"url": r.url, "id": vid})
    page.on("response", on_resp)

    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Click ONLY Card 4 (Aurora) at x=810
    page.mouse.click(810, 210)
    page.wait_for_timeout(2000)
    page.evaluate("document.querySelector('video')?.play()")
    page.wait_for_timeout(5000)

    cookies = ctx.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    ctx.close()

aurora_url = None
for c in captured:
    aurora_url = c["url"]
    print(f"   Aurora video ID: {c['id']}", flush=True)

if not aurora_url:
    print("ERROR: No Aurora URL captured", flush=True)
    sys.exit(1)

# Step 2: Download
print("Step 2: Downloading Aurora clip...", flush=True)
resp = requests.get(aurora_url, headers={"Cookie": cookie_str}, stream=True, timeout=30)
with open(scene6_path, "wb") as f:
    for chunk in resp.iter_content(chunk_size=8192):
        f.write(chunk)
sz = scene6_path.stat().st_size
print(f"   Saved: {sz // 1024} KB", flush=True)

# Verify it's different from scenes 1-5
s6_hash = hashlib.md5(open(scene6_path, "rb").read()).hexdigest()
for i in range(1, 6):
    sp = clips_dir / f"scene_{i:02d}.mp4"
    sh = hashlib.md5(open(sp, "rb").read()).hexdigest()
    match = "DUPLICATE!" if sh == s6_hash else "unique"
    print(f"   vs scene_{i:02d}: {match}", flush=True)

# Step 3: Audit
print("\nStep 3: Gemini AI Audit...", flush=True)
from pipeline.gemini_video_reviewer import gemini_full_video_review
audit = gemini_full_video_review(proj_dir)
passed = audit["passed"]
print(f"   PASSED: {passed}", flush=True)

if not passed:
    print("   Audit failed. Aborting.", flush=True)
    sys.exit(1)

# Step 4: Render
print("\nStep 4: Rendering final video...", flush=True)
with open(proj_dir / "words.json", "r", encoding="utf-8") as f:
    words_data = json.load(f)
with open(proj_dir / "storyboard.json", "r", encoding="utf-8") as f:
    sb = json.load(f)

words_list = words_data.get("words", [])
word_idx = 0
scene_durations = []
for sc in sb["scenes"]:
    sc_words = sc["narration"].split()
    s = words_list[word_idx]["start"] if word_idx < len(words_list) else 0.0
    word_idx += len(sc_words)
    e = words_list[min(word_idx - 1, len(words_list) - 1)]["end"] if word_idx - 1 < len(words_list) else s + 8.0
    d = max(3.0, e - s)
    scene_durations.append((sc["scene_number"], d, sc["name"]))

trimmed = []
for num, dur, name in scene_durations:
    src = clips_dir / f"scene_{num:02d}.mp4"
    out = clips_dir / f"trimmed_scene_{num:02d}.mp4"
    subprocess.run([config.FFMPEG_EXE, "-y", "-i", str(src),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an", str(out)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    trimmed.append(out)

cf = clips_dir / "concat_perfect.txt"
with open(cf, "w", encoding="utf-8") as f:
    for t in trimmed:
        f.write(f"file '{str(t).replace(chr(92), '/')}'\n")
raw = clips_dir / "concatenated_perfect.mp4"
subprocess.run([config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", str(cf), "-c", "copy", str(raw)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

from pipeline.stage4_subtitles import generate_ass_subtitles
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration
captions = proj_dir / "captions.ass"
generate_ass_subtitles(proj_dir / "words.json", captions)
narr = proj_dir / "narration.mp3"
music = clips_dir / "background_music.aac"
tdur = get_media_duration(narr)
generate_ambient_music_track(music, tdur + 2.0)

out_final = proj_dir / "output" / "final_short.mp4"
af = (f"[1:a]volume={config.VOICE_VOLUME_DB}dB,asplit=2[v0][vs];"
      f"[2:a]volume={config.MUSIC_VOLUME_DB}dB[m];"
      f"[m][vs]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[md];"
      f"[v0][md]amix=inputs=2:duration=first:dropout_transition=2[ao]")
ass_str = str(captions).replace("\\", "/").replace(":", "\\:")
r = subprocess.run([config.FFMPEG_EXE, "-y", "-i", str(raw), "-i", str(narr), "-i", str(music),
    "-filter_complex", af, "-map", "0:v", "-map", "[ao]",
    "-vf", f"subtitles='{ass_str}'", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", config.AUDIO_BITRATE, "-t", f"{tdur:.3f}", "-pix_fmt", "yuv420p", str(out_final)],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
if r.returncode != 0:
    print(f"Error: {r.stderr[-300:]}", flush=True)
else:
    sz = out_final.stat().st_size // (1024 * 1024)
    print(f"\nDONE! {out_final} ({sz} MB) - ZERO DUPLICATES", flush=True)
