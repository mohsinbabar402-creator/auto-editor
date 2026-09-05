import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config

def get_media_duration(file_path: Path) -> float:
    """Gets duration in seconds of video or audio file using ffprobe/ffmpeg."""
    cmd = [
        config.FFMPEG_EXE,
        "-i", str(file_path)
    ]
    result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    for line in result.stderr.splitlines():
        if "Duration:" in line:
            # Duration: 00:00:52.45, start: ...
            parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return 0.0

def create_synthetic_test_clip(output_path: Path, duration: float, scene_info: Dict[str, Any]):
    """Creates a temporary test video clip for dry-run testing before spending Veo credits."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sc_num = scene_info.get("scene_number", 1)
    
    # Generate 1080x1920 animated test pattern with gradient
    colors = ["#1a1a2e", "#16213e", "#0f3460", "#533483", "#2c003e", "#180026"]
    color = colors[(sc_num - 1) % len(colors)]
    
    cmd = [
        config.FFMPEG_EXE, "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s=1080x1920:d={duration}:r=30",
        "-vf", "noise=c1s=8:c0s=8:allf=t",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def generate_ambient_music_track(output_path: Path, duration: float):
    """Generates a smooth cinematic ambient drone background music using FFmpeg synthesis."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Simple, rock-solid synth drone
    cmd = [
        config.FFMPEG_EXE, "-y",
        "-f", "lavfi",
        "-i", f"aevalsrc=sin(2*PI*55*t)*0.08+sin(2*PI*110*t)*0.04:s=44100:d={duration}",
        "-af", f"afade=t=in:ss=0:d=2.0,afade=t=out:st={max(0, duration-3)}:d=3.0",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def generate_sfx_impact(output_path: Path):
    """Generates a deep sub-bass cinematic impact sound effect."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.FFMPEG_EXE, "-y",
        "-f", "lavfi",
        "-i", "aevalsrc=sin(2*PI*60*exp(-4*t)*t)*exp(-3*t):s=44100:d=1.5",
        "-af", "lowpass=f=200,volume=3.0",
        "-c:a", "aac",
        str(output_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def compose_video(
    storyboard_path: Path,
    narration_audio_path: Path,
    captions_ass_path: Optional[Path],
    clips_dir: Path,
    output_video_path: Path,
    music_track_path: Optional[Path] = None,
    allow_synthetic_clips: bool = True
) -> Path:
    """
    Assembles final 1080x1920 video:
    - Scales/crops clips to 1080x1920
    - Synchronizes scene transitions with narration length
    - Mixes voice, music (with ducking), and SFX
    - Burns ASS subtitles into video
    """
    with open(storyboard_path, "r", encoding="utf-8") as f:
        sb = json.load(f)

    total_narration_dur = get_media_duration(narration_audio_path)
    if total_narration_dur <= 0:
        total_narration_dur = sb.get("target_duration_sec", 50.0)

    scenes = sb.get("scenes", [])
    num_scenes = len(scenes)

    # Calculate proportional duration for each scene
    estimated_total = sum(sc.get("estimated_duration_sec", 8.0) for sc in scenes)
    scene_durations = [
        (sc.get("estimated_duration_sec", 8.0) / estimated_total) * total_narration_dur
        for sc in scenes
    ]

    # Check / prepare clips
    clips_dir.mkdir(parents=True, exist_ok=True)
    processed_clip_paths = []
    
    for i, sc in enumerate(scenes):
        target_name = f"scene_{sc['scene_number']:02d}.mp4"
        clip_path = clips_dir / target_name
        
        if not clip_path.exists():
            if allow_synthetic_clips:
                print(f"[Stage 5] Scene clip {target_name} not found. Generating temporary test card...")
                create_synthetic_test_clip(clip_path, scene_durations[i] + 1.0, sc)
            else:
                raise FileNotFoundError(f"Missing required clip: {clip_path}")
        
        # Prepare normalized 1080x1920 scaled clip with correct trimmed duration
        trimmed_clip = clips_dir / f"trimmed_scene_{sc['scene_number']:02d}.mp4"
        dur = scene_durations[i]
        
        # Video filter: scale to cover 1080x1920, crop to center, set frame rate 30fps
        vf_scale = f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"
        
        cmd_trim = [
            config.FFMPEG_EXE, "-y",
            "-stream_loop", "-1",
            "-i", str(clip_path),
            "-t", f"{dur:.3f}",
            "-vf", vf_scale,
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-an",
            str(trimmed_clip)
        ]
        subprocess.run(cmd_trim, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        processed_clip_paths.append(trimmed_clip)

    # Concat all video clips
    concat_list_file = clips_dir / "concat_list.txt"
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for p in processed_clip_paths:
            # Escape path for FFmpeg concat demuxer
            safe_p = str(p).replace('\\', '/')
            f.write(f"file '{safe_p}'\n")

    concatenated_video = clips_dir / "concatenated_raw.mp4"
    cmd_concat = [
        config.FFMPEG_EXE, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_file),
        "-c", "copy",
        str(concatenated_video)
    ]
    subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Handle Background Music
    if not music_track_path or not music_track_path.exists():
        music_track_path = clips_dir / "background_music.aac"
        print("[Stage 5] Generating ambient tension background track...")
        generate_ambient_music_track(music_track_path, total_narration_dur + 2.0)

    # Prepare SFX Impact
    sfx_impact_path = clips_dir / "sfx_impact.aac"
    if not sfx_impact_path.exists():
        generate_sfx_impact(sfx_impact_path)

    # Build Audio Filter Complex (Voice + Music with Ducking)
    # [1:a] = Narration, [2:a] = Music
    audio_filter = (
        f"[1:a]volume={config.VOICE_VOLUME_DB}dB,asplit=2[v0_mix][v0_side];"
        f"[2:a]volume={config.MUSIC_VOLUME_DB}dB[m0];"
        f"[m0][v0_side]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[m_ducked];"
        f"[v0_mix][m_ducked]amix=inputs=2:duration=first:dropout_transition=2[a_out]"
    )

    # Subtitle Filter
    video_filters = []
    if captions_ass_path and captions_ass_path.exists():
        # Escape path for FFmpeg subtitles filter
        ass_path_str = str(captions_ass_path).replace('\\', '/').replace(':', '\\:')
        video_filters.append(f"subtitles='{ass_path_str}'")

    vf_arg = ",".join(video_filters) if video_filters else "null"

    # Final Render
    output_video_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[Stage 5] Rendering final 9:16 short to {output_video_path}...")
    
    cmd_final = [
        config.FFMPEG_EXE, "-y",
        "-i", str(concatenated_video),
        "-i", str(narration_audio_path),
        "-i", str(music_track_path),
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
        str(output_video_path)
    ]

    res = subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed:\n{res.stderr}")

    print(f"[Stage 5] Final Short successfully rendered at {output_video_path}!")
    return output_video_path

if __name__ == "__main__":
    proj_dir = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating"
    sb = proj_dir / "storyboard.json"
    narr = proj_dir / "narration.mp3"
    ass = proj_dir / "captions.ass"
    clips = proj_dir / "clips"
    out_mp4 = proj_dir / "output" / "final_short.mp4"
    if sb.exists() and narr.exists():
        compose_video(sb, narr, ass, clips, out_mp4)
