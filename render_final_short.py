import subprocess, sys
from pathlib import Path
import config

PROJECT_DIR = Path("projects/08_naruto_vs_sasuke").resolve()
RENDERS_DIR = PROJECT_DIR / "renders"
ANIME_VIDEO = PROJECT_DIR / "anime_source" / "naruto_vs_sasuke_anime_cut.mp4"
MASTER_AUDIO = PROJECT_DIR / "audio" / "naruto_vs_sasuke_anime_cut.wav"
FINAL_OUTPUT = PROJECT_DIR / "NARUTO_VS_SASUKE_REALISTIC_COMPARISON_SHORT.mp4"
my_version_vid = RENDERS_DIR / "my_version_animated.mp4"

# Stack "My version" (top) and "Original Anime" (bottom)
# We crop the top 50px of the anime stream to eliminate any logo/watermark cleanly!
cmd_final = [
    str(config.FFMPEG_EXE), "-y",
    "-i", str(my_version_vid),
    "-i", str(ANIME_VIDEO),
    "-i", str(MASTER_AUDIO),
    "-filter_complex", (
        "[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,"
        "drawtext=text='My version':font='Arial':fontsize=52:fontcolor=white:borderw=3:bordercolor=black:"
        "box=1:boxcolor=black@0.65:boxborderw=14:x=(w-text_w)/2:y=35[top];"
        "[1:v]scale=1280:960,crop=1080:960:100:45,"
        "drawtext=text='Original Anime':font='Arial':fontsize=52:fontcolor=white:borderw=3:bordercolor=black:"
        "box=1:boxcolor=black@0.65:boxborderw=14:x=(w-text_w)/2:y=35[bottom];"
        "[top][bottom]vstack=inputs=2[v_stacked];"
        "[v_stacked]drawbox=x=0:y=956:w=1080:h=8:color=0x38bdf8@0.95:t=fill[v_final]"
    ),
    "-map", "[v_final]",
    "-map", "2:a",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
    "-c:a", "aac", "-b:a", "192k",
    "-t", "15.0",
    str(FINAL_OUTPUT)
]

print("Rendering clean comparison short...")
subprocess.run(cmd_final, check=True)
print(f"SUCCESS: Video rendered to {FINAL_OUTPUT.name} ({FINAL_OUTPUT.stat().st_size} bytes)")
