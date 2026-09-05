import sys, os, json, subprocess, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from pipeline.stage4_subtitles import generate_ass_subtitles
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration

def render_part(part_id: str):
    p_dir = config.PROJECTS_DIR / part_id
    clips_dir = p_dir / "clips"
    output_dir = p_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    sb_file = p_dir / "storyboard.json"
    with open(sb_file, "r", encoding="utf-8") as f:
        sb = json.load(f)
        
    print(f"\n{'='*60}")
    print(f" EDITING & RENDERING SHORT: {sb['title']}")
    print(f"{'='*60}")
    
    words_file = p_dir / "words.json"
    with open(words_file, "r", encoding="utf-8") as f:
        words_data = json.load(f)
        
    word_list = words_data.get("words", [])
    scenes = sb["scenes"]
    
    # Calculate exact duration for each scene based on word timestamps
    w_idx = 0
    scene_cuts = []
    print("[1] Synchronizing Scene Timings to ElevenLabs Voiceover:")
    for sc in scenes:
        words = sc["narration"].split()
        start_t = word_list[w_idx]["start"] if w_idx < len(word_list) else 0.0
        w_idx += len(words)
        end_t = word_list[min(w_idx-1, len(word_list)-1)]["end"] if w_idx-1 < len(word_list) else start_t + 8.0
        duration = max(3.0, end_t - start_t)
        scene_cuts.append((sc["scene_number"], duration, sc["name"]))
        print(f"   Scene {sc['scene_number']} ({sc['name']}): {duration:.2f}s")
        
    # Trim and scale each clip to 1080x1920 9:16
    print("\n[2] Trimming and formatting 1080x1920 clips...")
    trimmed_clips = []
    for sc_num, dur, sc_name in scene_cuts:
        src = clips_dir / f"scene_{sc_num:02d}.mp4"
        dst = clips_dir / f"trimmed_scene_{sc_num:02d}.mp4"
        
        # Check source duration
        res = subprocess.run([config.FFMPEG_EXE, "-i", str(src)], capture_output=True, text=True)
        # Scale, crop to 1080x1920 vertical, trim duration
        cmd = [
            config.FFMPEG_EXE, "-y", "-i", str(src),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
            "-t", f"{dur:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-an", str(dst)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        trimmed_clips.append(dst)
        print(f"   Trimmed scene {sc_num} -> {dst.name}")
        
    # Concatenate video clips
    concat_txt = clips_dir / "concat_list.txt"
    with open(concat_txt, "w", encoding="utf-8") as f:
        for c in trimmed_clips:
            f.write(f"file '{str(c).replace(chr(92), '/')}'\n")
            
    concat_video = clips_dir / "concatenated_raw.mp4"
    subprocess.run([
        config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_txt), "-c", "copy", str(concat_video)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    
    # Subtitles
    print("\n[3] Generating Animated ASS Subtitles...")
    captions_file = p_dir / "captions.ass"
    generate_ass_subtitles(words_file, captions_file)
    
    # Music & Ducking
    print("\n[4] Composing Audio & Sidechain Ducking...")
    narr_audio = p_dir / "narration.mp3"
    bg_music = clips_dir / "background_music.aac"
    total_dur = get_media_duration(narr_audio)
    generate_ambient_music_track(bg_music, total_dur + 2.0)
    
    # Final Output Render
    final_output = output_dir / f"{part_id}.mp4"
    print(f"\n[5] Rendering Final 9:16 Short to: {final_output.name}...")
    
    ass_path_clean = str(captions_file).replace("\\", "/").replace(":", "\\:")
    audio_filter = (
        f"[1:a]volume={config.VOICE_VOLUME_DB}dB,asplit=2[v0][vs];"
        f"[2:a]volume={config.MUSIC_VOLUME_DB}dB[m];"
        f"[m][vs]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[md];"
        f"[v0][md]amix=inputs=2:duration=first:dropout_transition=2[ao]"
    )
    
    render_cmd = [
        config.FFMPEG_EXE, "-y",
        "-i", str(concat_video),
        "-i", str(narr_audio),
        "-i", str(bg_music),
        "-filter_complex", audio_filter,
        "-map", "0:v", "-map", "[ao]",
        "-vf", f"subtitles='{ass_path_clean}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", config.AUDIO_BITRATE,
        "-t", f"{total_dur:.3f}",
        "-pix_fmt", "yuv420p",
        str(final_output)
    ]
    
    res = subprocess.run(render_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Render Error:", res.stderr[-500:])
        sys.exit(1)
        
    print(f"\n{'='*60}")
    print(f"SUCCESS! Rendered {final_output.name} ({final_output.stat().st_size // (1024*1024)} MB)")
    print(f"File Path: {final_output}")
    print(f"{'='*60}\n")
    
    # Auto-copy to Google Drive if available
    drive_candidates = [Path("G:/My Drive/YouTube Shorts"), Path("G:/YouTube Shorts")]
    for d in drive_candidates:
        if d.parent.exists():
            d.mkdir(parents=True, exist_ok=True)
            dst_drive = d / f"{part_id}.mp4"
            shutil.copy2(final_output, dst_drive)
            print(f"Copied directly to Google Drive: {dst_drive}")
            break

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "part2_the_great_ocean_surge"
    render_part(target)
