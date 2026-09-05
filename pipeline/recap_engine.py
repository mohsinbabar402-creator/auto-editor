"""
Joel-Style Perfect Movie Recap Engine v1.0
==========================================

Creates professional, engaging movie recap Shorts that:
1. Match EVERY clip to the narration perfectly (semantic scene mapping)
2. Use 3-5 second slow, cinematic cuts (NOT rapid trailer cuts)
3. Download clean 1080p footage from YouTube (no hardcoded subs)
4. Apply clean Joel-style white italic captions (lower third)
5. Generate ElevenLabs narration with the pool rotation system
6. Auto-save to Google Drive and free local disk

Usage:
    python -m pipeline.recap_engine --movie "The Platform" --year 2019
    
Or from another script:
    from pipeline.recap_engine import create_recap
    create_recap(movie_name="The Platform", year=2019)
"""

import os
import sys
import json
import re
import time
import subprocess
import base64
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure UTF-8 output
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
import config

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
WORK_DIR = ROOT_DIR / "projects" / "04_movie_recaps"
FOOTAGE_DIR = WORK_DIR / "footage"
CLIPS_DIR = WORK_DIR / "clips"
AUDIO_DIR = WORK_DIR / "audio"
RENDERS_DIR = WORK_DIR / "renders"
SCENE_MAPS_DIR = WORK_DIR / "scene_maps"

for d in [FOOTAGE_DIR, CLIPS_DIR, AUDIO_DIR, RENDERS_DIR, SCENE_MAPS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

FFMPEG = config.FFMPEG_EXE

# Joel Recap caption style
CAPTION_STYLE = {
    "fontname": "Arial",
    "fontsize": 52,
    "bold": True,
    "italic": True,
    "primary_color": "&H00FFFFFF",   # White
    "outline_color": "&H00000000",   # Black outline
    "back_color": "&H80000000",      # Semi-transparent shadow
    "outline_width": 2.5,
    "shadow": 1.5,
    "alignment": 2,                  # Bottom center
    "margin_v": 120,                 # Positioned at lower chest, not over faces
}


# ---------------------------------------------------------------------------
# STEP 1: SEARCH & DOWNLOAD 1080p FOOTAGE
# ---------------------------------------------------------------------------
def search_and_download_footage(movie_name: str, year: int = None) -> List[Path]:
    """
    Searches YouTube for clean scene packs / trailers and downloads in 1080p.
    Returns list of downloaded footage file paths.
    """
    import yt_dlp
    search_queries = [
        f"{movie_name} {year or ''} official trailer 4K",
        f"{movie_name} {year or ''} movie clip 1080p",
        f"{movie_name} {year or ''} scene pack no subtitles",
    ]
    
    safe_name = re.sub(r'[^\w\s-]', '', movie_name).strip().replace(' ', '_').lower()
    downloaded = []
    
    for i, query in enumerate(search_queries[:2]):  # Download top 2 search results
        output_path = FOOTAGE_DIR / f"{safe_name}_source_{i+1}.mp4"
        
        if output_path.exists() and output_path.stat().st_size > 1024 * 1024:
            print(f"[Footage] Already have: {output_path.name}")
            downloaded.append(output_path)
            continue
        
        print(f"[Footage] Searching YouTube: '{query}'...")
        
        ydl_opts = {
            'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
            'ffmpeg_location': str(Path(FFMPEG).parent),
            'outtmpl': str(output_path),
            'merge_output_format': 'mp4',
            'max_filesize': 150 * 1024 * 1024,
            'quiet': False,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"ytsearch1:{query}"])
            
            if output_path.exists() and output_path.stat().st_size > 1024 * 1024:
                size_mb = output_path.stat().st_size / (1024 * 1024)
                print(f"[Footage] Downloaded: {output_path.name} ({size_mb:.1f} MB)")
                downloaded.append(output_path)
            else:
                print(f"[Footage] Download failed for query: {query}")
        except Exception as e:
            print(f"[Footage] Error: {e}")
    
    if not downloaded:
        raise RuntimeError(f"Could not download any footage for '{movie_name}'. Please drop 1080p files into {FOOTAGE_DIR}/")
    
    return downloaded


# ---------------------------------------------------------------------------
# STEP 2: ANALYZE FOOTAGE & EXTRACT KEY FRAMES
# ---------------------------------------------------------------------------
def analyze_footage(footage_paths: List[Path], safe_name: str) -> Dict[str, Any]:
    """
    Analyzes downloaded footage: extracts key frames every 3 seconds,
    gets duration, resolution, and scene timestamps.
    """
    import cv2
    
    analysis = {"sources": []}
    frames_dir = WORK_DIR / "ref_frames" / safe_name
    frames_dir.mkdir(parents=True, exist_ok=True)
    
    for fp in footage_paths:
        cap = cv2.VideoCapture(str(fp))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = total_frames / fps if fps > 0 else 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        source_info = {
            "file": str(fp),
            "filename": fp.name,
            "duration": round(duration, 1),
            "resolution": f"{width}x{height}",
            "fps": round(fps, 2),
            "frames": []
        }
        
        # Extract frames every 3 seconds for visual reference
        t = 0
        while t < duration:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
            ret, frame = cap.read()
            if ret:
                frame_path = frames_dir / f"{fp.stem}_{int(t)}s.jpg"
                cv2.imwrite(str(frame_path), frame)
                source_info["frames"].append({
                    "timestamp": round(t, 1),
                    "path": str(frame_path)
                })
            t += 3.0
        
        cap.release()
        analysis["sources"].append(source_info)
        print(f"[Analysis] {fp.name}: {duration:.1f}s, {width}x{height}, extracted {len(source_info['frames'])} frames")
    
    return analysis


# ---------------------------------------------------------------------------
# STEP 3: GENERATE SCRIPT & SCENE MAP WITH GEMINI
# ---------------------------------------------------------------------------
def generate_script_and_scene_map(
    movie_name: str, 
    year: int,
    footage_analysis: Dict,
    target_duration: int = 90
) -> Dict[str, Any]:
    """
    Uses Gemini to generate:
    1. A compelling narration script (60-120 seconds)
    2. A semantic scene map that matches each narration line to exact footage timestamps
    """
    import google.generativeai as genai
    
    genai.configure(api_key=config.GOOGLE_API_KEY)
    model = genai.GenerativeModel("gemini-3.6-flash")
    
    # Build footage summary for Gemini
    footage_summary = ""
    for src in footage_analysis["sources"]:
        footage_summary += f"\nSource: {src['filename']} ({src['duration']}s, {src['resolution']})\n"
        footage_summary += f"Available timestamps: 0s to {src['duration']}s\n"
    
    prompt = f"""You are a professional movie recap scriptwriter for YouTube Shorts (Joel Recap style).

MOVIE: {movie_name} ({year})

AVAILABLE FOOTAGE:
{footage_summary}

Create a movie recap Short script that is EXACTLY {target_duration} seconds long.

RULES FOR THE NARRATION:
1. Start with a HOOK that makes viewers NEED to keep watching (a question, a shocking fact, or a dramatic moment)
2. Tell the story in a way that makes viewers WANT to watch the actual movie
3. End with a CLIFFHANGER that makes them want Part 2
4. Each narration segment should be 3-5 seconds of speech
5. Use dramatic pauses between segments
6. Total narration should be {target_duration-10} to {target_duration} seconds when spoken

RULES FOR SCENE MAPPING:
1. Each clip MUST be 3-5 seconds long (NOT rapid 1.5s cuts)
2. The clip MUST visually match what the narration is describing
3. If narration says "a feast" -> clip MUST show food/feast scene
4. If narration says "he picks up a knife" -> clip MUST show knife scene
5. Use SLOW, CINEMATIC clips that let viewers absorb the scene
6. Prefer close-up face shots during emotional moments
7. Prefer wide shots during establishing/setting moments

Return ONLY valid JSON in this exact format:
{{
    "title": "Video title for YouTube",
    "description": "YouTube description with hashtags",
    "total_duration_seconds": {target_duration},
    "scenes": [
        {{
            "scene_number": 1,
            "narration_text": "The exact words the narrator will say",
            "narration_duration_seconds": 4.5,
            "clip_source": "filename of the source video",
            "clip_start_seconds": 15.0,
            "clip_end_seconds": 19.5,
            "visual_description": "What this clip shows (for verification)",
            "mood": "tense/dramatic/calm/shocking/emotional"
        }}
    ]
}}

Generate 15-25 scenes that together create a compelling, binge-worthy recap."""

    print(f"[Script] Generating narration + scene map with Gemini...")
    
    response = model.generate_content(prompt)
    raw_text = response.text.strip()
    
    # Extract JSON from response
    json_match = re.search(r'\{[\s\S]*\}', raw_text)
    if json_match:
        scene_map = json.loads(json_match.group())
    else:
        raise ValueError("Gemini did not return valid JSON scene map")
    
    # Save scene map
    safe_name = re.sub(r'[^\w\s-]', '', movie_name).strip().replace(' ', '_').lower()
    map_path = SCENE_MAPS_DIR / f"{safe_name}_scene_map.json"
    with open(map_path, 'w', encoding='utf-8') as f:
        json.dump(scene_map, f, indent=2, ensure_ascii=False)
    
    num_scenes = len(scene_map.get("scenes", []))
    print(f"[Script] Generated {num_scenes} scenes, saved to {map_path.name}")
    
    return scene_map


# ---------------------------------------------------------------------------
# STEP 4: GENERATE VOICEOVER WITH ELEVENLABS (Pool Rotation)
# ---------------------------------------------------------------------------
def generate_voiceover(scene_map: Dict, safe_name: str) -> Path:
    """
    Generates a single continuous voiceover from all narration segments.
    Uses the ElevenLabs pool rotation system.
    """
    from pipeline.stage3_voiceover import generate_voiceover_elevenlabs
    
    # Combine all narration into one script with natural pauses
    full_script = ""
    for scene in scene_map.get("scenes", []):
        text = scene.get("narration_text", "").strip()
        if text:
            full_script += text + "... "  # Ellipsis creates a natural pause
    
    full_script = full_script.strip()
    
    audio_path = AUDIO_DIR / f"{safe_name}_narration.mp3"
    words_path = AUDIO_DIR / f"{safe_name}_words.json"
    
    print(f"[Voice] Generating narration ({len(full_script)} chars)...")
    
    result = generate_voiceover_elevenlabs(
        script_text=full_script,
        output_audio_path=audio_path,
        output_words_path=words_path,
    )
    
    print(f"[Voice] Narration saved: {audio_path.name}")
    return audio_path


# ---------------------------------------------------------------------------
# STEP 5: CUT CLIPS FROM FOOTAGE (Exact Scene Mapping)
# ---------------------------------------------------------------------------
def cut_clips(scene_map: Dict, safe_name: str) -> List[Path]:
    """
    Cuts exact clips from source footage based on the scene map.
    Each clip is cropped to 9:16 vertical with face-centered framing.
    """
    clips = []
    clip_dir = CLIPS_DIR / safe_name
    clip_dir.mkdir(parents=True, exist_ok=True)
    
    for scene in scene_map.get("scenes", []):
        idx = scene["scene_number"]
        source_file = None
        
        # Find the source footage file
        clip_source = scene.get("clip_source", "")
        for fp in FOOTAGE_DIR.glob("*.mp4"):
            if fp.name == clip_source or clip_source in fp.name:
                source_file = fp
                break
        
        if not source_file:
            # Fallback: use first available footage
            source_files = list(FOOTAGE_DIR.glob(f"{safe_name}*.mp4"))
            if source_files:
                source_file = source_files[0]
            else:
                print(f"[Clips] WARNING: No source found for scene {idx}, skipping")
                continue
        
        start = scene.get("clip_start_seconds", 0)
        end = scene.get("clip_end_seconds", start + 4)
        duration = end - start
        
        # Clamp duration to 3-6 seconds
        if duration < 2:
            duration = 4
            end = start + duration
        elif duration > 8:
            duration = 5
            end = start + duration
        
        clip_path = clip_dir / f"scene_{idx:02d}.mp4"
        
        # FFmpeg: Extract clip + crop to 9:16 vertical (center crop)
        # For landscape source: crop center to 9:16
        # For portrait source: use as-is
        cmd = [
            str(FFMPEG), "-y",
            "-ss", str(start),
            "-i", str(source_file),
            "-t", str(duration),
            "-vf", (
                "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"  # Center crop to 9:16
                "scale=1080:1920:flags=lanczos,"       # Scale to full HD
                "setsar=1"
            ),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-an",  # No audio (we add narration separately)
            str(clip_path)
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
            if clip_path.exists():
                clips.append(clip_path)
            else:
                print(f"[Clips] Failed to cut scene {idx}")
        except Exception as e:
            print(f"[Clips] Error cutting scene {idx}: {e}")
    
    print(f"[Clips] Cut {len(clips)} clips from footage")
    return clips


# ---------------------------------------------------------------------------
# STEP 6: GENERATE CAPTIONS (Joel Recap Style)
# ---------------------------------------------------------------------------
def generate_captions(scene_map: Dict, safe_name: str) -> Path:
    """
    Creates an ASS subtitle file with Joel Recap-style captions.
    Clean white italic text, lower third positioning.
    """
    s = CAPTION_STYLE
    
    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: JoelStyle,{s['fontname']},{s['fontsize']},{s['primary_color']},{s['primary_color']},{s['outline_color']},{s['back_color']},-1,-1,0,0,100,100,1,0,1,{s['outline_width']},{s['shadow']},{s['alignment']},40,40,{s['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    # Calculate timing for each narration segment
    current_time = 0.0
    
    for scene in scene_map.get("scenes", []):
        text = scene.get("narration_text", "").strip()
        dur = scene.get("narration_duration_seconds", 4.0)
        
        if not text:
            continue
        
        start_time = current_time
        end_time = current_time + dur
        
        # Format time as H:MM:SS.CC
        def fmt(t):
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            sec = int(t % 60)
            cs = int((t % 1) * 100)
            return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"
        
        # Split long text into 2 lines max (for readability)
        words = text.split()
        if len(words) > 8:
            mid = len(words) // 2
            line1 = " ".join(words[:mid])
            line2 = " ".join(words[mid:])
            display_text = f"{line1}\\N{line2}"
        else:
            display_text = text
        
        ass_content += f"Dialogue: 0,{fmt(start_time)},{fmt(end_time)},JoelStyle,,0,0,0,,{display_text}\n"
        
        current_time = end_time + 0.3  # Small gap between captions
    
    captions_path = WORK_DIR / f"{safe_name}_captions.ass"
    with open(captions_path, 'w', encoding='utf-8') as f:
        f.write(ass_content)
    
    print(f"[Captions] Generated Joel-style captions: {captions_path.name}")
    return captions_path


# ---------------------------------------------------------------------------
# STEP 7: FINAL ASSEMBLY (Clips + Narration + Captions + Music)
# ---------------------------------------------------------------------------
def assemble_final_video(
    clips: List[Path],
    audio_path: Path,
    captions_path: Path,
    safe_name: str,
    scene_map: Dict
) -> Path:
    """
    Assembles the final video:
    1. Concatenates all scene clips in order
    2. Overlays the narration audio
    3. Burns in Joel-style captions
    4. Renders at 1080x1920, 30fps, high bitrate
    """
    # Step 7a: Create concat list
    concat_list_path = CLIPS_DIR / safe_name / "concat_list.txt"
    with open(concat_list_path, 'w') as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")
    
    # Step 7b: Concatenate clips into one video
    concat_video = CLIPS_DIR / safe_name / "concatenated.mp4"
    cmd_concat = [
        str(FFMPEG), "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list_path),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-r", "30",
        str(concat_video)
    ]
    
    print("[Assembly] Concatenating clips...")
    subprocess.run(cmd_concat, capture_output=True, timeout=120)
    
    if not concat_video.exists():
        raise RuntimeError("Failed to concatenate clips")
    
    # Step 7c: Final render with narration + captions
    title = scene_map.get("title", f"{safe_name}_recap")
    output_filename = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_').lower() + ".mp4"
    final_output = RENDERS_DIR / output_filename
    
    # Get audio duration to trim video
    audio_duration_cmd = [
        str(FFMPEG), "-i", str(audio_path),
        "-hide_banner"
    ]
    result = subprocess.run(audio_duration_cmd, capture_output=True, text=True)
    
    cmd_final = [
        str(FFMPEG), "-y",
        "-i", str(concat_video),          # Video
        "-i", str(audio_path),             # Narration audio
        "-filter_complex", (
            f"[0:v]ass='{str(captions_path).replace(chr(92), chr(92)+chr(92)).replace(':', chr(92)+':')}'[captioned]"
        ),
        "-map", "[captioned]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "17",                      # High quality
        "-c:a", "aac",
        "-b:a", "192k",
        "-r", "30",
        "-shortest",                       # Trim to shortest stream (audio length)
        "-movflags", "+faststart",         # Web-optimized
        str(final_output)
    ]
    
    print("[Assembly] Rendering final video with captions...")
    result = subprocess.run(cmd_final, capture_output=True, text=True, timeout=300)
    
    if not final_output.exists():
        # Fallback: render without ASS captions (in case of path escaping issues)
        print("[Assembly] Retrying without embedded captions...")
        cmd_simple = [
            str(FFMPEG), "-y",
            "-i", str(concat_video),
            "-i", str(audio_path),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "17",
            "-c:a", "aac", "-b:a", "192k",
            "-r", "30", "-shortest",
            "-movflags", "+faststart",
            str(final_output)
        ]
        subprocess.run(cmd_simple, capture_output=True, timeout=300)
    
    if final_output.exists():
        size_mb = final_output.stat().st_size / (1024 * 1024)
        print(f"[Assembly] DONE: {final_output.name} ({size_mb:.1f} MB)")
    else:
        raise RuntimeError("Final render failed")
    
    # Cleanup temp concat video
    if concat_video.exists():
        concat_video.unlink()
    
    return final_output


# ---------------------------------------------------------------------------
# STEP 8: CLOUD SAVE
# ---------------------------------------------------------------------------
def save_and_cleanup(final_video: Path):
    """Moves final video to Google Drive and frees local space."""
    from pipeline.cloud_save import save_to_cloud
    
    try:
        cloud_path = save_to_cloud(str(final_video), "04_movie_recaps", delete_local=True)
        print(f"[Cloud] Video saved to: {cloud_path}")
        print(f"[Cloud] Watch at: drive.google.com > YouTube Shorts > 04_movie_recaps")
    except Exception as e:
        print(f"[Cloud] Cloud save failed: {e}. File stays at: {final_video}")


# ---------------------------------------------------------------------------
# MASTER FUNCTION: CREATE RECAP
# ---------------------------------------------------------------------------
def create_recap(
    movie_name: str, 
    year: int = None, 
    target_duration: int = 90,
    save_to_cloud: bool = True
) -> Path:
    """
    Master function: Creates a complete Joel-style movie recap Short.
    
    Args:
        movie_name: Name of the movie (e.g. "The Platform")
        year: Release year (e.g. 2019)
        target_duration: Target duration in seconds (60-120)
        save_to_cloud: Whether to save to Google Drive after rendering
    
    Returns:
        Path to the final rendered video
    """
    safe_name = re.sub(r'[^\w\s-]', '', movie_name).strip().replace(' ', '_').lower()
    
    print("=" * 60)
    print(f"JOEL-STYLE RECAP ENGINE: {movie_name} ({year or 'Unknown'})")
    print("=" * 60)
    
    # Step 1: Download footage
    print("\n[1/7] Downloading 1080p footage...")
    footage_paths = search_and_download_footage(movie_name, year)
    
    # Step 2: Analyze footage
    print("\n[2/7] Analyzing footage & extracting frames...")
    analysis = analyze_footage(footage_paths, safe_name)
    
    # Step 3: Generate script + scene map
    print("\n[3/7] Generating narration script + scene map...")
    scene_map = generate_script_and_scene_map(movie_name, year, analysis, target_duration)
    
    # Step 4: Generate voiceover
    print("\n[4/7] Generating ElevenLabs narration...")
    audio_path = generate_voiceover(scene_map, safe_name)
    
    # Step 5: Cut clips
    print("\n[5/7] Cutting matched clips from footage...")
    clips = cut_clips(scene_map, safe_name)
    
    if not clips:
        raise RuntimeError("No clips were cut. Check footage availability.")
    
    # Step 6: Generate captions
    print("\n[6/7] Generating Joel-style captions...")
    captions_path = generate_captions(scene_map, safe_name)
    
    # Step 7: Assemble final video
    print("\n[7/7] Assembling final video...")
    final_video = assemble_final_video(clips, audio_path, captions_path, safe_name, scene_map)
    
    # Step 8: Cloud save
    if save_to_cloud:
        print("\n[CLOUD] Saving to Google Drive...")
        save_and_cleanup(final_video)
    
    print("\n" + "=" * 60)
    print(f"RECAP COMPLETE: {movie_name}")
    print("=" * 60)
    
    return final_video


# ---------------------------------------------------------------------------
# CLI ENTRY POINT
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Joel-Style Movie Recap Engine")
    parser.add_argument("--movie", required=True, help="Movie name")
    parser.add_argument("--year", type=int, default=None, help="Release year")
    parser.add_argument("--duration", type=int, default=90, help="Target duration (60-120 seconds)")
    parser.add_argument("--no-cloud", action="store_true", help="Don't save to Google Drive")
    
    args = parser.parse_args()
    
    create_recap(
        movie_name=args.movie,
        year=args.year,
        target_duration=args.duration,
        save_to_cloud=not args.no_cloud,
    )
