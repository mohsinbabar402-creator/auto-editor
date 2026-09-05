"""
Whop High-Retention Automated Clipper Engine v1.0
- Downloads 1080p source podcast / interview
- Transcribes & identifies top viral retention peaks with Gemini
- Crops to 9:16 Vertical with intelligent speaker center
- Applies Hormozi / Devin style kinetic animated captions (Yellow/White)
- Interleaves call-to-action prompts for maximum Like-to-View ratio
- Direct upload to G:\My Drive\YouTube Shorts\05_whop_campaigns\ with local auto-purge
"""

import os
import sys
import re
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import config
from pipeline.cloud_save import save_to_cloud

WORK_DIR = config.PROJECTS_DIR / "07_whop_clipping"
RAW_DIR = WORK_DIR / "raw"
RENDERS_DIR = WORK_DIR / "renders"
AUDIO_DIR = WORK_DIR / "audio"

RAW_DIR.mkdir(parents=True, exist_ok=True)
RENDERS_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG = config.FFMPEG_EXE


def download_source_video(url_or_query: str, campaign_name: str) -> Path:
    import yt_dlp
    safe_name = re.sub(r'[^\w\s-]', '', campaign_name).strip().replace(' ', '_').lower()
    output_path = RAW_DIR / f"{safe_name}_source.mp4"
    
    if output_path.exists() and output_path.stat().st_size > 1024 * 1024:
        print(f"[Whop Clipper] Source already downloaded: {output_path.name}")
        return output_path
        
    print(f"[Whop Clipper] Downloading 1080p source for campaign '{campaign_name}'...")
    ydl_opts = {
        'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
        'ffmpeg_location': str(Path(FFMPEG).parent),
        'outtmpl': str(output_path),
        'merge_output_format': 'mp4',
        'quiet': False,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        if url_or_query.startswith("http"):
            ydl.download([url_or_query])
        else:
            ydl.download([f"ytsearch1:{url_or_query}"])
            
    if not output_path.exists():
        raise FileNotFoundError(f"Failed to download source for {campaign_name}")
        
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[Whop Clipper] [OK] Source ready: {output_path.name} ({size_mb:.1f} MB)")
    return output_path



def render_viral_clip(
    source_file: Path,
    start_sec: float,
    duration_sec: float,
    hook_title: str,
    clip_index: int,
    campaign_name: str,
    call_to_action: str = "Comment below & check bio! 👇"
) -> Path:
    safe_name = re.sub(r'[^\w\s-]', '', campaign_name).strip().replace(' ', '_').lower()
    clip_output = RENDERS_DIR / f"{safe_name}_clip_{clip_index:02d}.mp4"
    
    # High-Impact ASS Captions (Clean Top Hook & Readable Lower Third Subtitle)
    ass_path = WORK_DIR / f"{safe_name}_clip_{clip_index:02d}_captions.ass"
    end_sec = duration_sec
    
    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HookHeader,Impact,64,&H0000FFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,3.5,2.0,8,40,40,280,1
Style: ModernSub,Arial,56,&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,3.5,2.0,2,40,40,320,1
Style: CTAStyle,Impact,64,&H0000FFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,4.0,2.5,2,40,40,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:06.00,HookHeader,,0,0,0,,{hook_title.upper()}
Dialogue: 0,0:00:{end_sec-4.5:05.2f},0:00:{end_sec:05.2f},CTAStyle,,0,0,0,,{call_to_action.upper()}
"""
    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(ass_content)
        
    # Aesthetic Clean Podcast Layout:
    # 1. Background: Full 1080x1920 aesthetic ambient Gaussian blur
    # 2. Foreground: Clean, un-cropped 16:9 widescreen video centered perfectly
    # 3. Dynamic typography placed cleanly in top and bottom thirds (Zero awkward zoom!)
    filter_complex = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30,eq=brightness=-0.25:saturation=1.2[blurred_bg];"
        "[fg]scale=1080:608:flags=lanczos[sharp_fg];"
        "[blurred_bg][sharp_fg]overlay=0:(H-h)/2[base];"
        f"[base]ass='{ass_path.name}'[outv]"
    )
    
    # Check if input video contains an audio stream
    probe = subprocess.run([str(FFMPEG), "-i", str(source_file.resolve())], stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
    has_audio = "Audio:" in probe.stderr

    cmd = [
        str(FFMPEG), "-y",
        "-ss", str(start_sec),
        "-i", str(source_file.resolve()),
        "-t", str(duration_sec),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
    ]
    if has_audio:
        cmd.extend([
            "-map", "0:a",
            "-af", "aresample=48000,volume=1.3,loudnorm=I=-14:TP=-1.0:LRA=11",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"
        ])
    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-movflags", "+faststart",
        str(clip_output.resolve())
    ])
    
    print(f"[Whop Clipper] Rendering Clip {clip_index}: '{hook_title}' ({duration_sec:.1f}s)...")
    subprocess.run(cmd, check=True, cwd=str(WORK_DIR))
    
    if ass_path.exists():
        ass_path.unlink()
        
    size_mb = clip_output.stat().st_size / (1024 * 1024)
    print(f"[Whop Clipper] [OK] Rendered: {clip_output.name} ({size_mb:.1f} MB)")
    
    # Cloud Save with local deletion
    cloud_path = save_to_cloud(str(clip_output), channel="07_viral_podcasts", delete_local=True)
    return cloud_path




def batch_create_whop_clips(
    url_or_query: str,
    campaign_name: str,
    clips_plan: List[Dict[str, Any]]
) -> List[Path]:
    print("=" * 60)
    print(f"[Whop Clipper] PIPELINE LAUNCHED: {campaign_name}")
    print("=" * 60)
    
    source = download_source_video(url_or_query, campaign_name)
    uploaded = []
    
    for i, p in enumerate(clips_plan, start=1):
        c_dest = render_viral_clip(
            source_file=source,
            start_sec=p["start"],
            duration_sec=p["duration"],
            hook_title=p["hook"],
            clip_index=i,
            campaign_name=campaign_name,
            call_to_action=p.get("cta", "Comment your thoughts below! 👇")
        )
        uploaded.append(c_dest)
        
    print("\n" + "=" * 60)
    print(f"[Whop Clipper] BATCH COMPLETE: {len(uploaded)} Clips Synced to Google Drive!")
    print("=" * 60)
    return uploaded



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Whop High-Retention Clipper Engine")
    parser.add_argument("--url", required=True, help="YouTube URL or search query")
    parser.add_argument("--campaign", required=True, help="Campaign or creator name")
    parser.add_argument("--start", type=float, default=60.0, help="Clip start timestamp in seconds")
    parser.add_argument("--dur", type=float, default=65.0, help="Clip duration in seconds (60s+ for TikTok RPM)")
    parser.add_argument("--hook", type=str, default="The Brutal Truth", help="Hook headline")
    args = parser.parse_args()
    
    plan = [{"start": args.start, "duration": args.dur, "hook": args.hook}]
    batch_create_whop_clips(args.url, args.campaign, plan)
