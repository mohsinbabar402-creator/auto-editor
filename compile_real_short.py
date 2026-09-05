import subprocess, shutil
from pathlib import Path
import config

PROJ_DIR = Path("projects/08_naruto_vs_sasuke").resolve()
REAL_VIDEOS = PROJ_DIR / "real_videos"
ANIME_VIDEO = PROJ_DIR / "anime_source" / "naruto_vs_sasuke_anime_cut.mp4"
MASTER_AUDIO = PROJ_DIR / "audio" / "naruto_vs_sasuke_anime_cut.wav"
FINAL_PROJECT_SHORT = PROJ_DIR / "NARUTO_VS_SASUKE_REAL_MOTION_COMPARISON.mp4"
DESKTOP_SHORT = Path(r"C:\Users\ice\Desktop\NARUTO_VS_SASUKE_REALISTIC_SHORT.mp4")

sasuke_vid = REAL_VIDEOS / "sasuke_real_motion_video.mp4"
naruto_vid = REAL_VIDEOS / "naruto_real_motion_video.mp4"
clash_vid = REAL_VIDEOS / "clash_real_motion_video.mp4"

# 1. First concatenate the 3 real motion videos together into one 15s top video
concat_list = PROJ_DIR / "real_concat_list.txt"
with open(concat_list, "w") as f:
    f.write(f"file '{sasuke_vid.as_posix()}'\n")
    f.write(f"file '{naruto_vid.as_posix()}'\n")
    f.write(f"file '{clash_vid.as_posix()}'\n")

top_15s = PROJ_DIR / "real_top_15s.mp4"
print("Concatenating 3 real AI motion clips...")
cmd_concat = [
    str(config.FFMPEG_EXE), "-y",
    "-f", "concat", "-safe", "0",
    "-i", str(concat_list),
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
    "-t", "15.0",
    str(top_15s)
]
subprocess.run(cmd_concat, check=True)

# 2. Build final split-screen Short
print("Assembling split-screen Short with mastered audio...")
cmd_final = [
    str(config.FFMPEG_EXE), "-y",
    "-i", str(top_15s),
    "-i", str(ANIME_VIDEO),
    "-i", str(MASTER_AUDIO),
    "-filter_complex", (
        "[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,"
        "drawtext=text='My version':font='Arial':fontsize=52:fontcolor=white:borderw=3:bordercolor=black:"
        "box=1:boxcolor=black@0.65:boxborderw=14:x=(w-text_w)/2:y=35[top];"
        "[1:v]scale=1320:1080,crop=1080:960:120:120,"
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
    str(FINAL_PROJECT_SHORT)
]
subprocess.run(cmd_final, check=True)

shutil.copy2(FINAL_PROJECT_SHORT, DESKTOP_SHORT)
print(f"\n=======================================================")
print(f"MASTER SHORT COMPLETED AND COPIED TO DESKTOP!")
print(f"Path: {DESKTOP_SHORT} ({DESKTOP_SHORT.stat().st_size} bytes)")
print(f"=======================================================")
