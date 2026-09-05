"""
Fix Scene 6 duplicate once and for all.
Try Pexels -> Pixabay -> FFmpeg generated clip as fallback.
Then audit and render.
"""
import sys, os, json, subprocess, requests
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

clips_dir = config.PROJECTS_DIR / "earth_stops_rotating" / "clips"
proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
scene6_path = clips_dir / "scene_06.mp4"


def try_pexels():
    """Download a portrait twilight clip from Pexels."""
    print("[Pexels] Searching for twilight clips...", flush=True)
    key = "dMcmGLn5c6nJtwBlVJjqhKAXXIjBvFGXrN7kJPORF5o8GXtxiqK5jEbr"
    headers = {"Authorization": key}
    queries = [
        "twilight sunset silhouette",
        "aurora borealis night sky",
        "golden hour horizon landscape",
    ]
    for q in queries:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers,
            params={"query": q, "per_page": 10},
        )
        print(f"  Query '{q}': status={resp.status_code}", flush=True)
        if resp.status_code != 200:
            continue
        videos = resp.json().get("videos", [])
        print(f"  Found {len(videos)} videos", flush=True)
        for v in videos:
            for vf in v.get("video_files", []):
                h = vf.get("height", 0)
                w = vf.get("width", 0)
                if h >= 720:
                    link = vf.get("link", "")
                    print(f"  Downloading {w}x{h} from {link[:80]}...", flush=True)
                    dl = requests.get(link, stream=True, timeout=30)
                    with open(scene6_path, "wb") as f:
                        for chunk in dl.iter_content(chunk_size=8192):
                            f.write(chunk)
                    sz = scene6_path.stat().st_size
                    if sz > 100000:
                        print(f"  OK: {sz // 1024} KB", flush=True)
                        return True
    return False


def try_pixabay():
    """Download from Pixabay."""
    print("[Pixabay] Searching for twilight clips...", flush=True)
    key = "47407182-bc51e05e39e7f915c38569a7e"
    queries = ["twilight sunset", "aurora borealis", "golden hour"]
    for q in queries:
        resp = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": key, "q": q, "per_page": 5},
        )
        print(f"  Query '{q}': status={resp.status_code}", flush=True)
        if resp.status_code != 200:
            continue
        hits = resp.json().get("hits", [])
        for hit in hits:
            vids = hit.get("videos", {})
            for quality in ["large", "medium", "small"]:
                vdata = vids.get(quality, {})
                url = vdata.get("url", "")
                if url:
                    print(f"  Downloading {quality} from Pixabay...", flush=True)
                    dl = requests.get(url, stream=True, timeout=30)
                    with open(scene6_path, "wb") as f:
                        for chunk in dl.iter_content(chunk_size=8192):
                            f.write(chunk)
                    sz = scene6_path.stat().st_size
                    if sz > 100000:
                        print(f"  OK: {sz // 1024} KB", flush=True)
                        return True
    return False


def generate_ffmpeg_twilight():
    """Generate a cinematic twilight gradient clip with FFmpeg."""
    print("[FFmpeg] Generating cinematic twilight gradient clip...", flush=True)
    cmd = [
        config.FFMPEG_EXE, "-y",
        "-f", "lavfi",
        "-i", (
            "gradients=s=1080x1920:duration=10:speed=0.5:"
            "c0=#0a0a2e:c1=#1a0530:c2=#ff6b35:c3=#ffd700:c4=#0a0a2e:c5=#000033"
        ),
        "-vf", (
            "drawtext=text='':fontsize=1,"
            "noise=alls=20:allf=t+u,"
            "gblur=sigma=2"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(scene6_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        # Simpler fallback
        cmd2 = [
            config.FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", "color=c=#1a0530:s=1080x1920:d=10:r=24",
            "-f", "lavfi", "-i", "color=c=#ff6b35:s=1080x1920:d=10:r=24",
            "-filter_complex",
            "[0:v][1:v]blend=all_expr='if(gt(Y,H/2-100+100*sin(2*PI*T/10)),B,A)':shortest=1",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-t", "10",
            str(scene6_path),
        ]
        res2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res2.returncode != 0:
            # Absolute simplest fallback
            cmd3 = [
                config.FFMPEG_EXE, "-y",
                "-f", "lavfi",
                "-i", "color=c=#1a0530:s=1080x1920:d=10:r=24",
                "-vf", "noise=alls=30:allf=t+u",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-pix_fmt", "yuv420p",
                str(scene6_path),
            ]
            subprocess.run(cmd3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    sz = scene6_path.stat().st_size
    print(f"  Generated: {sz // 1024} KB", flush=True)
    return sz > 10000


# ── TRY ALL SOURCES ──
got_clip = try_pexels()
if not got_clip:
    got_clip = try_pixabay()
if not got_clip:
    got_clip = generate_ffmpeg_twilight()

if not got_clip:
    print("FATAL: Could not obtain Scene 6 clip.", flush=True)
    sys.exit(1)

# ── GEMINI AUDIT ──
print("\nRunning Gemini AI audit...", flush=True)
from pipeline.gemini_video_reviewer import gemini_full_video_review
audit = gemini_full_video_review(proj_dir)
print(f"Audit passed: {audit['passed']}", flush=True)

# ── COMPOSITE ──
print("\nCompositing with exact word-level sentence cuts...", flush=True)

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
    print(f"  Scene {sc['scene_number']} ({sc['name']}): {dur:.2f}s", flush=True)

# Trim clips
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

# Concat
concat_file = clips_dir / "concat_perfect.txt"
with open(concat_file, "w", encoding="utf-8") as f:
    for tc in trimmed_clips:
        safe = str(tc).replace("\\", "/")
        f.write(f"file '{safe}'\n")

raw = clips_dir / "concatenated_perfect.mp4"
subprocess.run(
    [config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0",
     "-i", str(concat_file), "-c", "copy", str(raw)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
)

# Captions
from pipeline.stage4_subtitles import generate_ass_subtitles
captions_path = proj_dir / "captions.ass"
generate_ass_subtitles(proj_dir / "words.json", captions_path)

# Music
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration
narration_path = proj_dir / "narration.mp3"
music_path = clips_dir / "background_music.aac"
total_dur = get_media_duration(narration_path)
generate_ambient_music_track(music_path, total_dur + 2.0)

# Final render
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
    "-i", str(raw),
    "-i", str(narration_path),
    "-i", str(music_path),
    "-filter_complex", audio_filter,
    "-map", "0:v", "-map", "[a_out]",
    "-vf", f"subtitles='{ass_str}'",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", config.AUDIO_BITRATE,
    "-t", f"{total_dur:.3f}",
    "-pix_fmt", "yuv420p",
    str(out_final),
]
res = subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
if res.returncode != 0:
    print(f"Render error: {res.stderr[-500:]}", flush=True)
else:
    sz = out_final.stat().st_size // (1024 * 1024)
    print(f"\n=== DONE! Final video: {out_final} ({sz} MB) ===", flush=True)
