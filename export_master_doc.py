import os, json
from pathlib import Path
import config

base = config.PROJECTS_DIR
master_doc = []
master_doc.append("# 🌍 6-PART MASTER SERIES: WHAT IF EARTH STOPPED SPINNING?\n")
master_doc.append("> **Format:** 6 Connected 50-Second Shorts (36 Scenes Total) $\rightarrow$ Stitched into 1 Master 5-Minute Full-Length YouTube Documentary.\n\n")

parts = [
    "part1_the_first_second",
    "part2_the_great_ocean_surge",
    "part3_atmospheric_superstorms",
    "part4_the_vanishing_shield",
    "part5_fire_and_ice",
    "part6_the_twilight_zone"
]

for p in parts:
    p_dir = base / p
    sb_file = p_dir / "storyboard.json"
    if not sb_file.exists():
        continue
    with open(sb_file, "r", encoding="utf-8") as f:
        sb = json.load(f)
    
    master_doc.append(f"## 🎬 {sb['title']}\n")
    master_doc.append(f"**Project Folder:** `projects/{p}/`  \n")
    master_doc.append(f"**Audio File:** `projects/{p}/narration.mp3`  \n\n")
    master_doc.append("| Scene | Scene Name | Voiceover (ElevenLabs) | Google Flow Visual Prompt (9:16 Veo) |\n")
    master_doc.append("| :---: | :--- | :--- | :--- |\n")
    
    for sc in sb["scenes"]:
        num = sc["scene_number"]
        name = sc["name"]
        narr = sc["narration"].replace("|", "\\|")
        vis = sc["visual_prompt"].replace("|", "\\|")
        master_doc.append(f"| **`scene_{num:02d}.mp4`** | {name} | *\"{narr}\"* | `{vis}` |\n")
    
    master_doc.append("\n---\n\n")

output_path = config.BASE_DIR / "MASTER_PROMPTS_AND_SCRIPTS.md"
with open(output_path, "w", encoding="utf-8") as f:
    f.writelines(master_doc)

print(f"Generated {output_path} ({output_path.stat().st_size} bytes)")
