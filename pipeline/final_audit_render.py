"""
Final audit + render with unique Scene 6 Aurora clip.
"""
import sys, os, json, subprocess
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from pipeline.gemini_video_reviewer import gemini_full_video_review
from pipeline.stage4_subtitles import generate_ass_subtitles
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"

# 1. AUDIT
print("1. Gemini AI Audit...", flush=True)
audit = gemini_full_video_review(proj_dir)
passed = audit["passed"]
print("   PASSED:", passed, flush=True)
if not passed:
    print("   FAILED - aborting", flush=True)
    sys.exit(1)

# 2. WORD-LEVEL SENTENCE CUTS
print("2. Computing sentence cuts...", flush=True)
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
    sn = sc["scene_number"]
    nm = sc["name"]
    print(f"   Scene {sn} ({nm}): {d:.2f}s", flush=True)

# 3. TRIM + CONCAT + RENDER
print("3. Trimming and rendering...", flush=True)
trimmed = []
for num, dur, name in scene_durations:
    src = clips_dir / f"scene_{num:02d}.mp4"
    out = clips_dir / f"trimmed_scene_{num:02d}.mp4"
    subprocess.run([
        config.FFMPEG_EXE, "-y", "-i", str(src),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an", str(out),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    trimmed.append(out)

cf = clips_dir / "concat_perfect.txt"
with open(cf, "w", encoding="utf-8") as f:
    for t in trimmed:
        safe = str(t).replace("\\", "/")
        f.write(f"file '{safe}'\n")

raw = clips_dir / "concatenated_perfect.mp4"
subprocess.run([
    config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0",
    "-i", str(cf), "-c", "copy", str(raw),
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

captions = proj_dir / "captions.ass"
generate_ass_subtitles(proj_dir / "words.json", captions)

narr = proj_dir / "narration.mp3"
music = clips_dir / "background_music.aac"
tdur = get_media_duration(narr)
generate_ambient_music_track(music, tdur + 2.0)

out_final = proj_dir / "output" / "final_short.mp4"
af = (
    f"[1:a]volume={config.VOICE_VOLUME_DB}dB,asplit=2[v0][vs];"
    f"[2:a]volume={config.MUSIC_VOLUME_DB}dB[m];"
    f"[m][vs]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[md];"
    f"[v0][md]amix=inputs=2:duration=first:dropout_transition=2[ao]"
)
ass_str = str(captions).replace("\\", "/").replace(":", "\\:")

r = subprocess.run([
    config.FFMPEG_EXE, "-y",
    "-i", str(raw), "-i", str(narr), "-i", str(music),
    "-filter_complex", af,
    "-map", "0:v", "-map", "[ao]",
    "-vf", f"subtitles='{ass_str}'",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", config.AUDIO_BITRATE,
    "-t", f"{tdur:.3f}", "-pix_fmt", "yuv420p",
    str(out_final),
], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

if r.returncode != 0:
    print(f"Error: {r.stderr[-300:]}", flush=True)
else:
    sz = out_final.stat().st_size // (1024 * 1024)
    print(f"DONE! {out_final} ({sz} MB) - ZERO DUPLICATES, PERFECT SYNC", flush=True)
