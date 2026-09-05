import os, sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

downloads = Path(os.path.expanduser("~/Downloads"))
p3_dir = config.PROJECTS_DIR / "part3_atmospheric_superstorms" / "clips"
p3_dir.mkdir(parents=True, exist_ok=True)

mapping_p3 = [
    (1, "hurricane"),
    (2, "Mountain_peaks_glowing"),
    (3, "Violet_lightning"),
    (4, "Orange_sky_over_barren"),
    (5, "Bedrock_canyon"),
    (6, "Earth_core_slowing")
]

dl_files = list(downloads.glob("*.mp4"))

print("=== MAPPING PART 3 CLIPS ===")
for num, pattern in mapping_p3:
    matched = [f for f in dl_files if pattern.lower() in f.name.lower()]
    if matched:
        matched.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        src = matched[0]
        dst = p3_dir / f"scene_{num:02d}.mp4"
        shutil.copy2(src, dst)
        print(f"Mapped Scene {num}: {src.name} -> {dst.name}")
    else:
        print(f"Scene {num} ('{pattern}') not found in Downloads yet.")

print("\nClips currently in Part 3:")
for c in sorted(p3_dir.glob("*.mp4")):
    print(f"   {c.name} ({c.stat().st_size//1024} KB)")
