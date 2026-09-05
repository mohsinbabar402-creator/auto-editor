"""
Download Aurora Borealis for Scene 6, align exact sentence timestamps, and render final short
"""
import sys, os, time, json, subprocess
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from playwright.sync_api import sync_playwright
from pipeline.gemini_video_reviewer import gemini_full_video_review

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"
PROJECT_URL = "https://labs.google/fx/tools/flow/project/5ae3acfb-ba6d-45d5-b325-88f3d9ee1b91"

print("="*65, flush=True)
print("📥 1. DOWNLOADING AURORA VIDEO FOR SCENE 6", flush=True)
print("="*65, flush=True)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(config.BROWSER_PROFILE_DIR),
        headless=False,
        args=['--disable-blink-features=AutomationControlled', '--no-first-run'],
        viewport={'width': 1280, 'height': 900},
        accept_downloads=True
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(PROJECT_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    # Click Card 4 (Aurora) at (650, 250)
    page.mouse.click(650, 250)
    page.wait_for_timeout(2500)

    dl = page.locator('button:has-text("download"), button[aria-label*="Download" i]').first
    if dl.is_visible(timeout=3000):
        t6 = clips_dir / "scene_06.mp4"
        try:
            with page.expect_download(timeout=15000) as dl_info:
                dl.click()
            dl_info.value.save_as(str(t6))
            print(f"✅ Saved Aurora clip for Scene 6: {t6.stat().st_size // 1024} KB", flush=True)
        except Exception as e:
            print(f"Download notice: {e}")

    context.close()

# Ensure all 6 distinct clips are assigned
import shutil
shutil.copy(str(clips_dir / "temp_earth.mp4"), str(clips_dir / "scene_01.mp4"))
shutil.copy(str(clips_dir / "temp_city.mp4"), str(clips_dir / "scene_02.mp4"))
shutil.copy(str(clips_dir / "temp_tsunami.mp4"), str(clips_dir / "scene_03.mp4"))
shutil.copy(str(clips_dir / "temp_shockwave.mp4"), str(clips_dir / "scene_04.mp4"))
shutil.copy(str(clips_dir / "temp_splitplanet.mp4"), str(clips_dir / "scene_05.mp4"))

print("\n" + "="*65, flush=True)
print("🤖 2. RUNNING GEMINI AI MULTI-PASS AUDIT", flush=True)
print("="*65, flush=True)
audit = gemini_full_video_review(proj_dir)
print(f"Gemini Audit Passed: {audit['passed']}", flush=True)

# 3. Millisecond-Accurate Word Timestamp Alignment
print("\n" + "="*65, flush=True)
print("🎬 3. COMPOSITING WITH MILLISECOND SENTENCE CUTS", flush=True)
print("="*65, flush=True)

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
    e_time = words_list[min(word_idx-1, len(words_list)-1)]["end"] if word_idx-1 < len(words_list) else s_time + 8.0
    dur = max(3.0, e_time - s_time)
    scene_durations.append((sc["scene_number"], dur, sc["name"]))

print("Exact Scene Durations based on ElevenLabs word cadence:")
for num, dur, name in scene_durations:
    print(f"  • Scene {num} ({name}): {dur:.2f}s")

# Trim / scale each clip to its exact sentence duration
trimmed_clips = []
for num, dur, name in scene_durations:
    src_clip = clips_dir / f"scene_{num:02d}.mp4"
    out_trimmed = clips_dir / f"trimmed_scene_{num:02d}.mp4"

    # 1080x1920 scaling + exact duration trim
    cmd_trim = [
        config.FFMPEG_EXE, "-y",
        "-i", str(src_clip),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-an",
        str(out_trimmed)
    ]
    subprocess.run(cmd_trim, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    trimmed_clips.append(out_trimmed)

# Concat trimmed clips
concat_file = clips_dir / "concat_perfect.txt"
with open(concat_file, "w", encoding="utf-8") as f:
    for tc in trimmed_clips:
        safe_tc = str(tc).replace('\\', '/')
        f.write(f"file '{safe_tc}'\n")

raw_concat = clips_dir / "concatenated_perfect.mp4"
subprocess.run([
    config.FFMPEG_EXE, "-y",
    "-f", "concat", "-safe", "0",
    "-i", str(concat_file),
    "-c", "copy",
    str(raw_concat)
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

# Final render with voiceover, background music, ducking, and animated captions
narration_path = proj_dir / "narration.mp3"
captions_path = proj_dir / "captions.ass"
music_path = clips_dir / "background_music.aac"
out_final = proj_dir / "output" / "final_short.mp4"

# Generate animated captions
from pipeline.stage4_subtitles import generate_ass_subtitles
generate_ass_subtitles(proj_dir / "words.json", captions_path)

# Generate music if missing
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration
total_narration_dur = get_media_duration(narration_path)
generate_ambient_music_track(music_path, total_narration_dur + 2.0)

# Audio filter complex with sidechain ducking
audio_filter = (
    f"[1:a]volume={config.VOICE_VOLUME_DB}dB,asplit=2[v0_mix][v0_side];"
    f"[2:a]volume={config.MUSIC_VOLUME_DB}dB[m0];"
    f"[m0][v0_side]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[m_ducked];"
    f"[v0_mix][m_ducked]amix=inputs=2:duration=first:dropout_transition=2[a_out]"
)

ass_path_str = str(captions_path).replace('\\', '/').replace(':', '\\:')
vf_arg = f"subtitles='{ass_path_str}'"

cmd_final = [
    config.FFMPEG_EXE, "-y",
    "-i", str(raw_concat),
    "-i", str(narration_path),
    "-i", str(music_path),
    "-filter_complex", audio_filter,
    "-map", "0:v",
    "-map", "[a_out]",
    "-vf", vf_arg,
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-c:a", "aac",
    "-b:a", config.AUDIO_BITRATE,
    "-t", f"{total_narration_dur:.3f}",
    "-pix_fmt", "yuv420p",
    str(out_final)
]

res = subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
if res.returncode != 0:
    print(f"Error rendering: {res.stderr}")
else:
    print(f"🎉 PERFECT FINAL SHORT RENDERED AT {out_final}!")

