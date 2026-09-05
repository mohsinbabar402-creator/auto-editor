"""
Generate Scene 6 in a BRAND NEW Google Flow project (no shared cards).
Then intercept CDN, download, audit, render.
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

FLOW_HOME = "https://labs.google/fx/tools/flow"

print("=== GENERATING SCENE 6 IN NEW GOOGLE FLOW PROJECT ===", flush=True)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        viewport={"width": 1280, "height": 900},
        accept_downloads=True,
    )
    page = context.pages[0] if context.pages else context.new_page()

    # Go to Flow home and start new project
    page.goto(FLOW_HOME, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    # Click "+" or "New" button to create a new project
    new_btn = page.locator('button[aria-label*="New"], button[aria-label*="Create"], button:has-text("+")').first
    if new_btn.is_visible(timeout=3000):
        new_btn.click()
        page.wait_for_timeout(3000)
    else:
        # Try the "+" icon in top bar
        page.mouse.click(1003, 38)
        page.wait_for_timeout(3000)

    # Type the Scene 6 prompt
    chat_in = page.locator('[contenteditable="true"]').first
    if chat_in.is_visible(timeout=5000):
        chat_in.click()
        prompt = (
            "Generate a cinematic 9:16 vertical video: "
            "A lone human silhouette stands on a rocky cliff edge at golden hour. "
            "Behind them, the left half of the sky is deep frozen blue with stars and ice particles, "
            "while the right half is blazing orange-red with heat waves and volcanic glow. "
            "A narrow golden twilight strip divides the two halves at the horizon. "
            "National Geographic documentary quality, photorealistic 8K, slow dramatic camera push."
        )
        page.keyboard.type(prompt, delay=2)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        print("Prompt submitted. Waiting for approval...", flush=True)
        page.wait_for_timeout(4000)

        # Auto-approve credit usage
        for _ in range(6):
            approve_btns = page.locator('button:has-text("Approve"), button:has-text("Generate"), button:has-text("Create")')
            if approve_btns.count() > 0:
                approve_btns.last.click(force=True)
                print("Approved!", flush=True)
                break
            page.wait_for_timeout(2000)

    # Wait for video to render (up to 2 min)
    print("Waiting for video render (~90s)...", flush=True)
    for i in range(12):
        page.wait_for_timeout(10000)
        # Check if a video card appeared
        play_btns = page.locator('button[aria-label*="Play"], div[class*="play"]')
        video_cards = page.locator('img[src*="googleusercontent"]')
        if play_btns.count() > 0 or video_cards.count() > 0:
            print(f"   Video card detected at {(i+1)*10}s!", flush=True)
            break

    page.wait_for_timeout(3000)

    # Set up CDN interception
    video_urls = []
    def on_response(response):
        if "flow-content.google/video" in response.url:
            video_urls.append(response.url)
    page.on("response", on_response)

    # Click the video card to open player
    cards = page.locator('img[src*="googleusercontent"]')
    if cards.count() > 0:
        cards.first.click(force=True)
        page.wait_for_timeout(3000)
        page.evaluate("document.querySelector('video')?.play()")
        page.wait_for_timeout(5000)
    else:
        # Try clicking center of canvas
        page.mouse.click(400, 300)
        page.wait_for_timeout(3000)
        page.evaluate("document.querySelector('video')?.play()")
        page.wait_for_timeout(5000)

    cookies = context.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

    context.close()

# Download from CDN
if video_urls:
    cdn_url = video_urls[-1]
    print(f"CDN URL: {cdn_url[:80]}...", flush=True)
    resp = requests.get(cdn_url, headers={"Cookie": cookie_str}, stream=True, timeout=30)
    if resp.status_code == 200:
        with open(scene6_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Saved scene_06.mp4: {scene6_path.stat().st_size // 1024} KB", flush=True)
    else:
        print(f"Download failed: {resp.status_code}", flush=True)
        sys.exit(1)
else:
    print("No video URL captured. Video may still be rendering.", flush=True)
    sys.exit(1)

# ── GEMINI AUDIT ──
print("\nRunning Gemini AI audit...", flush=True)
from pipeline.gemini_video_reviewer import gemini_full_video_review
audit = gemini_full_video_review(proj_dir)
print(f"Audit passed: {audit['passed']}", flush=True)

if not audit["passed"]:
    print("WARNING: Audit failed. Check report above.", flush=True)
    sys.exit(1)

# ── COMPOSITE ──
print("\nCompositing with exact sentence cuts...", flush=True)
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

trimmed_clips = []
for num, dur, name in scene_durations:
    src = clips_dir / f"scene_{num:02d}.mp4"
    out = clips_dir / f"trimmed_scene_{num:02d}.mp4"
    subprocess.run([
        config.FFMPEG_EXE, "-y", "-i", str(src),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an", str(out),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    trimmed_clips.append(out)

concat_file = clips_dir / "concat_perfect.txt"
with open(concat_file, "w", encoding="utf-8") as f:
    for tc in trimmed_clips:
        f.write(f"file '{str(tc).replace(chr(92), '/')}'\n")

raw = clips_dir / "concatenated_perfect.mp4"
subprocess.run([config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0",
    "-i", str(concat_file), "-c", "copy", str(raw)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

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
res = subprocess.run([
    config.FFMPEG_EXE, "-y",
    "-i", str(raw), "-i", str(narration_path), "-i", str(music_path),
    "-filter_complex", audio_filter,
    "-map", "0:v", "-map", "[a_out]",
    "-vf", f"subtitles='{ass_str}'",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", config.AUDIO_BITRATE,
    "-t", f"{total_dur:.3f}", "-pix_fmt", "yuv420p", str(out_final),
], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

if res.returncode != 0:
    print(f"Render error: {res.stderr[-500:]}", flush=True)
else:
    sz = out_final.stat().st_size // (1024 * 1024)
    print(f"\n=== DONE! {out_final} ({sz} MB) - ZERO DUPLICATES ===", flush=True)
