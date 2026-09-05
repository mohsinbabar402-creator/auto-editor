"""
Download Aurora video directly from CDN URL, replace Scene 6, audit, and re-render.
"""
import sys, os, json, subprocess, requests
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

# ── 1. Open Aurora card and intercept CDN URL, then download via requests ──
print("1. Extracting Aurora CDN URL and downloading...", flush=True)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900},
        accept_downloads=True,
    )
    page = context.pages[0] if context.pages else context.new_page()

    video_urls = []
    def on_response(response):
        ct = response.headers.get("content-type", "")
        if "video" in ct or response.url.endswith(".mp4") or "flow-content.google/video" in response.url:
            video_urls.append(response.url)

    page.on("response", on_response)

    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    # Click Aurora card (Card 4)
    page.mouse.click(650, 250)
    page.wait_for_timeout(3000)

    # Play video to trigger CDN fetch
    page.mouse.click(640, 400)
    page.wait_for_timeout(3000)
    page.evaluate("document.querySelector('video')?.play()")
    page.wait_for_timeout(3000)

    # Get cookies for authenticated download
    cookies = context.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

    context.close()

if video_urls:
    cdn_url = video_urls[0]
    print(f"   CDN URL: {cdn_url[:100]}...", flush=True)

    # Download with cookies
    headers = {"Cookie": cookie_str}
    resp = requests.get(cdn_url, headers=headers, stream=True, timeout=30)
    print(f"   Download status: {resp.status_code}", flush=True)
    if resp.status_code == 200:
        with open(scene6_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        sz = scene6_path.stat().st_size
        print(f"   Saved scene_06.mp4: {sz // 1024} KB", flush=True)
    else:
        print(f"   Failed to download: {resp.status_code}", flush=True)
        sys.exit(1)
else:
    print("   No video URLs captured!", flush=True)
    sys.exit(1)

# ── 2. Gemini Audit ──
print("\n2. Running Gemini AI audit...", flush=True)
from pipeline.gemini_video_reviewer import gemini_full_video_review
audit = gemini_full_video_review(proj_dir)
print(f"   Audit passed: {audit['passed']}", flush=True)

# ── 3. Composite ──
print("\n3. Compositing with exact sentence cuts...", flush=True)

with open(proj_dir / "words.json", "r", encoding="utf-8") as f:
    words_data = json.load(f)
with open(proj_dir / "storyboard.json", "r", encoding="utf-8") as f:
    sb = json.load(f)

words_list = words_data.get("words", [])
word_idx = 0
scene_durations = []
for sc in sb["scenes"]:
    sc_words = sc["narration"].split()
    s_time = words_list[word_idx]["start"] if word_idx < len(words_list) else 0.0
    word_idx += len(sc_words)
    e_idx = min(word_idx - 1, len(words_list) - 1)
    e_time = words_list[e_idx]["end"] if e_idx >= 0 else s_time + 8.0
    dur = max(3.0, e_time - s_time)
    scene_durations.append((sc["scene_number"], dur, sc["name"]))
    print(f"   Scene {sc['scene_number']} ({sc['name']}): {dur:.2f}s", flush=True)

trimmed_clips = []
for num, dur, name in scene_durations:
    src = clips_dir / f"scene_{num:02d}.mp4"
    out = clips_dir / f"trimmed_scene_{num:02d}.mp4"
    cmd = [
        config.FFMPEG_EXE, "-y", "-i", str(src),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an",
        str(out),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    trimmed_clips.append(out)

concat_file = clips_dir / "concat_perfect.txt"
with open(concat_file, "w", encoding="utf-8") as f:
    for tc in trimmed_clips:
        f.write(f"file '{str(tc).replace(chr(92), '/')}'\n")

raw = clips_dir / "concatenated_perfect.mp4"
subprocess.run(
    [config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0",
     "-i", str(concat_file), "-c", "copy", str(raw)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
)

from pipeline.stage4_subtitles import generate_ass_subtitles
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration

captions_path = proj_dir / "captions.ass"
generate_ass_subtitles(proj_dir / "words.json", captions_path)

narration_path = proj_dir / "narration.mp3"
music_path = clips_dir / "background_music.aac"
total_dur = get_media_duration(narration_path)
generate_ambient_music_track(music_path, total_dur + 2.0)

out_final = proj_dir / "output" / "final_short.mp4"
audio_filter = (
    f"[1:a]volume={config.VOICE_VOLUME_DB}dB,asplit=2[v0_mix][v0_side];"
    f"[2:a]volume={config.MUSIC_VOLUME_DB}dB[m0];"
    f"[m0][v0_side]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[m_ducked];"
    f"[v0_mix][m_ducked]amix=inputs=2:duration=first:dropout_transition=2[a_out]"
)
ass_str = str(captions_path).replace("\\", "/").replace(":", "\\:")

cmd_final = [
    config.FFMPEG_EXE, "-y",
    "-i", str(raw), "-i", str(narration_path), "-i", str(music_path),
    "-filter_complex", audio_filter,
    "-map", "0:v", "-map", "[a_out]",
    "-vf", f"subtitles='{ass_str}'",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", config.AUDIO_BITRATE,
    "-t", f"{total_dur:.3f}", "-pix_fmt", "yuv420p",
    str(out_final),
]
res = subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
if res.returncode != 0:
    print(f"Render error: {res.stderr[-500:]}", flush=True)
else:
    sz = out_final.stat().st_size // (1024 * 1024)
    print(f"\n=== DONE! {out_final} ({sz} MB) ===", flush=True)
