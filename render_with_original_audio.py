import sys, os, json, subprocess, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from pipeline.stage4_subtitles import generate_ass_subtitles
from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration

def render_part_with_original_audio(part_id: str):
    p_dir = config.PROJECTS_DIR / part_id
    clips_dir = p_dir / "clips"
    output_dir = p_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    sb_file = p_dir / "storyboard.json"
    with open(sb_file, "r", encoding="utf-8") as f:
        sb = json.load(f)
        
    print(f"\n{'='*60}")
    print(f" EDITING & RENDERING (ORIGINAL VIDEO AUDIO INCLUDED): {sb['title']}")
    print(f"{'='*60}")
    
    words_file = p_dir / "words.json"
    with open(words_file, "r", encoding="utf-8") as f:
        words_data = json.load(f)
        
    word_list = words_data.get("words", [])
    scenes = sb["scenes"]
    
    w_idx = 0
    scene_cuts = []
    print("[1] Synchronizing Scene Timings:")
    for sc in scenes:
        words = sc["narration"].split()
        start_t = word_list[w_idx]["start"] if w_idx < len(word_list) else 0.0
        w_idx += len(words)
        end_t = word_list[min(w_idx-1, len(word_list)-1)]["end"] if w_idx-1 < len(word_list) else start_t + 8.0
        duration = max(3.0, end_t - start_t)
        scene_cuts.append((sc["scene_number"], duration, sc["name"]))
        print(f"   Scene {sc['scene_number']} ({sc['name']}): {duration:.2f}s")
        
    print("\n[2] Trimming 1080x1920 clips while keeping original audio tracks...")
    trimmed_clips = []
    for sc_num, dur, sc_name in scene_cuts:
        src = clips_dir / f"scene_{sc_num:02d}.mp4"
        dst = clips_dir / f"trimmed_scene_{sc_num:02d}.mp4"
        
        # Check if source has audio
        probe = subprocess.run([
            config.FFMPEG_EXE, "-i", str(src)
        ], capture_output=True, text=True)
        has_audio = "Audio:" in probe.stderr
        
        if has_audio:
            cmd = [
                config.FFMPEG_EXE, "-y", "-i", str(src),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
                "-t", f"{dur:.3f}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "128k",
                str(dst)
            ]
        else:
            # Add silent audio track so concat works seamlessly with audio
            cmd = [
                config.FFMPEG_EXE, "-y", "-i", str(src),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
                "-t", f"{dur:.3f}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                str(dst)
            ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        trimmed_clips.append(dst)
        print(f"   Trimmed scene {sc_num} -> {dst.name} (Audio included: {has_audio})")
        
    # Concat clips
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
    
    # Music
    narr_audio = p_dir / "narration.mp3"
    bg_music = clips_dir / "background_music.aac"
    total_dur = get_media_duration(narr_audio)
    generate_ambient_music_track(bg_music, total_dur + 2.0)
    
    # Final Output Render with 3-way Audio Mixing:
    # 1. Voiceover (Dominant, 0dB)
    # 2. Original Video Audio (Background ambient, -16dB)
    # 3. Background Music (-20dB with sidechain ducking under voice)
    final_output = output_dir / f"{part_id}.mp4"
    desktop_output = Path("C:/Users/ice/Desktop/FINISHED_YOUTUBE_SHORTS") / f"{part_id}.mp4"
    desktop_output.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"\n[4] Rendering 3-Way Audio Master (Dominant Voice + Subtle Video Audio + Music)...")
    
    ass_path_clean = str(captions_file).replace("\\", "/").replace(":", "\\:")
    
    # [0:a] = Original clip audio
    # [1:a] = Elevenlabs voiceover
    # [2:a] = Ambient music
    audio_filter = (
        f"[0:a]volume=-15.0dB[orig_audio];"
        f"[1:a]volume=0.0dB,asplit=2[v0][vs];"
        f"[2:a]volume=-20.0dB[m];"
        f"[m][vs]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[m_ducked];"
        f"[v0][orig_audio][m_ducked]amix=inputs=3:duration=first:dropout_transition=2[ao]"
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
        
    shutil.copy2(final_output, desktop_output)
    print(f"\nSUCCESS! Rendered {final_output.name} with original background audio mix!")
    print(f"Saved to: {desktop_output}")
    
    # Sync to Google Drive
    drive_dst = Path("G:/My Drive/YouTube Shorts") / f"{part_id}.mp4"
    try:
        shutil.copy2(final_output, drive_dst)
        print(f"Synced to Google Drive: {drive_dst}")
    except Exception as e:
        print(f"Google Drive sync note: {e}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "part2_the_great_ocean_surge"
    render_part_with_original_audio(target)
