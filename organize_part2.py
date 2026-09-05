import os, sys, shutil, json, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

downloads = Path(os.path.expanduser("~/Downloads"))
p_dir = config.PROJECTS_DIR / "part2_the_great_ocean_surge"
clips_dir = p_dir / "clips"
clips_dir.mkdir(parents=True, exist_ok=True)

# Mapping downloaded files to Part 2 scenes
mapping = [
    (1, "Earth_water_displacement_toward"),
    (2, "Monstrous_ocean_wave_cresting"),
    (3, "Ocean_waves_crashing_into_mountains"),
    (4, "Sunlight_filtering_through_subme"),
    (5, "Globe_map_showing_supercontinent"),
    (6, "Storm_clouds_igniting_with_elect")
]

dl_files = list(downloads.glob("*.mp4"))

print("=== MAPPING & MOVING PART 2 CLIPS ===")
for num, pattern in mapping:
    matched = [f for f in dl_files if pattern.lower() in f.name.lower()]
    if matched:
        # Sort by mtime descending to get latest
        matched.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        src = matched[0]
        dst = clips_dir / f"scene_{num:02d}.mp4"
        shutil.copy2(src, dst)
        print(f"Mapped Scene {num}: {src.name} -> {dst.name} ({dst.stat().st_size // 1024} KB)")
    else:
        print(f"WARNING: No file matching '{pattern}' found in Downloads!")

print("\nClips in Part 2 directory:")
for c in sorted(clips_dir.glob("*.mp4")):
    print(f"   {c.name}: {c.stat().st_size // 1024} KB")
