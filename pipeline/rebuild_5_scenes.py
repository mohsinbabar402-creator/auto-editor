"""
Rebuild storyboard to 5 scenes (matching our 5 unique clips), re-render immediately.
"""
import sys, os, json, subprocess, hashlib
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
clips_dir = proj_dir / "clips"

# === 1. VERIFY WE HAVE 5 UNIQUE CLIPS ===
print("1. Verifying 5 unique clips...", flush=True)
hashes = {}
for i in range(1, 6):
    p = clips_dir / f"scene_{i:02d}.mp4"
    h = hashlib.md5(open(p, "rb").read()).hexdigest()
    hashes[i] = h
    print(f"   scene_{i:02d}.mp4: {p.stat().st_size // 1024} KB | {h[:12]}", flush=True)

unique = len(set(hashes.values()))
print(f"   Unique clips: {unique}/5", flush=True)
assert unique == 5, "Not all clips are unique!"

# === 2. REBUILD STORYBOARD TO 5 SCENES ===
print("\n2. Rebuilding storyboard to 5 scenes...", flush=True)
new_storyboard = {
    "title": "What If Earth Stopped Spinning?",
    "target_duration_sec": 50,
    "scenes": [
        {
            "scene_number": 1,
            "name": "The Instant Cataclysm",
            "narration": "If Earth stopped spinning for even one second, you wouldn't just fall over. You would be launched east at a thousand miles per hour.",
            "visual_prompt": "Earth in space with sunrise flare, dramatic cinematic",
            "estimated_duration_sec": 10
        },
        {
            "scene_number": 2,
            "name": "Supersonic Winds & City Destruction",
            "narration": "Because the atmosphere keeps moving at rotational speed, supersonic winds over 1,000 miles an hour would instantly wipe entire cities off the map.",
            "visual_prompt": "City skyscrapers being destroyed by supersonic winds",
            "estimated_duration_sec": 10
        },
        {
            "scene_number": 3,
            "name": "The Mega-Tsunami & Ocean Surge",
            "narration": "The oceans would slosh violently toward the poles, creating colossal global tsunamis towering miles high, swallowing continents in minutes.",
            "visual_prompt": "Mega tsunami water wall crashing over mountains",
            "estimated_duration_sec": 10
        },
        {
            "scene_number": 4,
            "name": "Magnetic Shield Collapse & Scorched Earth",
            "narration": "Without rotation, Earth's liquid metal core stops churning, destroying our magnetic shield and exposing the surface to deadly cosmic radiation. One side of the planet would endure six months of scorching daylight, while the other freezes in eternal darkness.",
            "visual_prompt": "Earth from space showing magnetic field collapse and radiation",
            "estimated_duration_sec": 12
        },
        {
            "scene_number": 5,
            "name": "The Twilight Strip Survival",
            "narration": "The only place you could survive? A narrow, twilight strip between fire and ice. Would you make it?",
            "visual_prompt": "Split planet half frozen half scorched with twilight strip",
            "estimated_duration_sec": 8
        }
    ]
}

with open(proj_dir / "storyboard.json", "w", encoding="utf-8") as f:
    json.dump(new_storyboard, f, indent=2)
print("   Saved 5-scene storyboard", flush=True)

# === 3. GENERATE VOICEOVER WITH ELEVENLABS ===
print("\n3. Generating ElevenLabs voiceover...", flush=True)
from pipeline.stage3_voiceover import build_full_script, generate_voiceover_elevenlabs

script = build_full_script(new_storyboard)
print(f"   Script ({len(script)} chars): {script[:80]}...", flush=True)

audio_path = proj_dir / "narration.mp3"
words_path = proj_dir / "words.json"
generate_voiceover_elevenlabs(script, audio_path, words_path)
print("   Voiceover generated!", flush=True)

# === 4. COMPUTE EXACT SENTENCE CUTS ===
print("\n4. Computing sentence cuts from word timestamps...", flush=True)
with open(words_path, "r", encoding="utf-8") as f:
    words_data = json.load(f)
words_list = words_data.get("words", [])

word_idx = 0
scene_durations = []
for sc in new_storyboard["scenes"]:
    sc_words = sc["narration"].split()
    s = words_list[word_idx]["start"] if word_idx < len(words_list) else 0.0
    word_idx += len(sc_words)
    e = words_list[min(word_idx - 1, len(words_list) - 1)]["end"] if word_idx - 1 < len(words_list) else s + 8.0
    d = max(3.0, e - s)
    scene_durations.append((sc["scene_number"], d, sc["name"]))
    print(f"   Scene {sc['scene_number']} ({sc['name']}): {d:.2f}s", flush=True)

# === 5. TRIM, CONCAT, RENDER ===
print("\n5. Trimming clips to exact sentence durations...", flush=True)
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
        f.write(f"file '{str(t).replace(chr(92), '/')}'\n")
raw = clips_dir / "concatenated_perfect.mp4"
subprocess.run([config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", str(cf), "-c", "copy", str(raw)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

# === 6. CAPTIONS + MUSIC + FINAL RENDER ===
print("\n6. Generating captions, music, and final render...", flush=True)
from pipeline.stage4_subtitles import generate_ass_subtitles
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration

cap = proj_dir / "captions.ass"
generate_ass_subtitles(words_path, cap)

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

r = subprocess.run([
    config.FFMPEG_EXE, "-y",
    "-i", str(raw), "-i", str(narr), "-i", str(mus),
    "-filter_complex", af, "-map", "0:v", "-map", "[ao]",
    "-vf", f"subtitles='{ass}'",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", config.AUDIO_BITRATE,
    "-t", f"{td:.3f}", "-pix_fmt", "yuv420p", str(out),
], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

if r.returncode != 0:
    print(f"Error: {r.stderr[-300:]}", flush=True)
else:
    sz = out.stat().st_size // (1024 * 1024)
    print(f"\n{'='*60}", flush=True)
    print(f"DONE! {out}", flush=True)
    print(f"Size: {sz} MB | 5 unique scenes | Zero duplicates", flush=True)
    print(f"{'='*60}", flush=True)
