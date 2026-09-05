"""
Stage 2: Cinematic Prompt Generator for Google Flow / Veo
Transforms storyboard scenes into production-ready, highly detailed cinematic video prompts.
"""

import json
from pathlib import Path
from typing import Dict, Any, List

def format_veo_prompt(scene: Dict[str, Any], global_style: str) -> Dict[str, Any]:
    """
    Creates a tailored prompt structure for Google Flow / Veo.
    Includes visual description, camera movement, lighting, lens/aesthetic, and negative styling.
    """
    prompt_text = (
        f"Vertical 9:16 cinematic video. {scene['visual_description']} "
        f"Camera: {scene['camera_movement']}. "
        f"Lighting: {scene['lighting']}. "
        f"Atmosphere: {scene['mood']}. "
        f"Style: {global_style}, shot on 35mm master prime anamorphic lens, hyperrealistic textures, volumetric dust and atmospheric light rays, 8K ultra high fidelity, National Geographic documentary look, zero cartoonish elements."
    )
    
    return {
        "scene_number": scene["scene_number"],
        "scene_name": scene["name"],
        "target_filename": f"scene_{scene['scene_number']:02d}.mp4",
        "recommended_duration_sec": scene["estimated_duration_sec"],
        "aspect_ratio": "9:16",
        "veo_prompt": prompt_text,
        "negative_prompt": "blurry, low quality, CGI cartoon, anime, low resolution, 2D illustration, deformed geometry, text, watermarks, subtitles, borders, flickering, oversaturated plastic textures",
        "camera_motion_guidance": scene["camera_movement"]
    }

def generate_prompts_file(storyboard_path: Path, output_md_path: Path) -> List[Dict[str, Any]]:
    with open(storyboard_path, "r", encoding="utf-8") as f:
        sb = json.load(f)
        
    global_style = sb.get("style", "Photorealistic 8K cinematic scientific documentary")
    prompts_list = []
    
    for sc in sb.get("scenes", []):
        prompts_list.append(format_veo_prompt(sc, global_style))
        
    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(f"# Google Flow / Veo Prompts for: {sb.get('title')}\n\n")
        f.write("> **Instructions**: Generate each scene individually in Google Flow / Veo using **9:16 vertical** aspect ratio. Download the rendered MP4s into the project's `clips/` directory with the exact filenames listed below.\n\n")
        f.write("---\n\n")
        for p in prompts_list:
            f.write(f"## 🎬 Scene {p['scene_number']}: {p['scene_name']}\n")
            f.write(f"- **Target File**: `clips/{p['target_filename']}`\n")
            f.write(f"- **Target Duration**: ~{p['recommended_duration_sec']}s\n")
            f.write(f"- **Aspect Ratio**: `9:16 (Vertical)`\n\n")
            f.write("### 📋 Copy & Paste Prompt for Google Flow / Veo:\n")
            f.write("```text\n")
            f.write(f"{p['veo_prompt']}\n")
            f.write("```\n\n")
            f.write("### 🚫 Negative Prompt (if supported):\n")
            f.write("```text\n")
            f.write(f"{p['negative_prompt']}\n")
            f.write("```\n\n")
            f.write("---\n\n")
            
    # Also save as json for programmatic ingestion
    json_path = output_md_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(prompts_list, f, indent=2)
        
    print(f"[Stage 2] Generated {len(prompts_list)} prompts to {output_md_path} and {json_path}")
    return prompts_list

if __name__ == "__main__":
    sb_file = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating" / "storyboard.json"
    out_file = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating" / "google_flow_prompts.md"
    generate_prompts_file(sb_file, out_file)
