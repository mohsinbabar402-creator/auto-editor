"""
Stage 1: Storyboard & Script Generator
Generates structured storyboards with scene timing, narration, visual descriptions, camera movement, and audio cues.
"""

import json
from pathlib import Path
from typing import Dict, Any, List

def create_earth_stops_storyboard() -> Dict[str, Any]:
    """Generates the initial benchmark storyboard for 'What Would Happen If Earth Suddenly Stopped Rotating?'"""
    return {
        "project_id": "earth_stops_rotating",
        "title": "What Would Happen If Earth Suddenly Stopped Rotating?",
        "aspect_ratio": "9:16",
        "target_duration_sec": 52,
        "style": "Photorealistic 8K cinematic scientific documentary, highly dramatic, intense lighting, atmospheric depth",
        "scenes": [
            {
                "scene_number": 1,
                "name": "The Instant Cataclysm (Hook)",
                "estimated_duration_sec": 7.0,
                "narration": "If Earth stopped spinning for even one second, you wouldn't just fall over. You would be launched east at a thousand miles per hour.",
                "visual_description": "Cinematic 8K space view of Earth spinning rapidly, then abruptly grinding to a dead halt as massive atmospheric shockwaves ripple across continents.",
                "camera_movement": "Rapid zoom-in push from deep space toward the equator, camera trembling with kinetic force.",
                "lighting": "Dramatic golden sun flare breaking over the curvature of the dark horizon.",
                "mood": "Shocking, catastrophic, immense scale.",
                "sfx_cue": "deep_bass_impact_whoosh"
            },
            {
                "scene_number": 2,
                "name": "Supersonic Atmospheric Winds",
                "estimated_duration_sec": 9.0,
                "narration": "Because the atmosphere keeps moving at rotational speed, supersonic winds over 1,000 miles an hour would instantly wipe entire cities off the map.",
                "visual_description": "Ground-level slow-motion view of modern city skyscrapers and steel bridges shattering and disintegrating into a colossal wall of dust and debris from horizontal supersonic winds.",
                "camera_movement": "Low-angle tracking shot panning frantically as buildings tear apart.",
                "lighting": "Hazy, storm-lit daylight with particulate air and glowing sparks.",
                "mood": "Pure chaos, destructive power.",
                "sfx_cue": "supersonic_wind_destruction"
            },
            {
                "scene_number": 3,
                "name": "The Mega-Tsunami Ocean Surge",
                "estimated_duration_sec": 10.0,
                "narration": "The oceans would slosh violently toward the poles, creating colossal global tsunamis towering miles high, swallowing continents in minutes.",
                "visual_description": "Wide aerial drone shot of an incomprehensibly vast mega-tsunami wall rising miles into the stratosphere, crashing over coastal mountain ranges and valleys.",
                "camera_movement": "High-altitude sweeping crane shot pulling back to reveal the apocalyptic scale of the water wall.",
                "lighting": "Dark storm clouds with piercing shafts of divine sunlight reflecting off churning turquoise water.",
                "mood": "Awe-inspiring, terrifying natural force.",
                "sfx_cue": "colossal_ocean_roar"
            },
            {
                "scene_number": 4,
                "name": "Magnetic Shield Collapse",
                "estimated_duration_sec": 10.0,
                "narration": "Without rotation, Earth's liquid metal core stops churning, destroying our magnetic shield and exposing the surface to deadly cosmic radiation.",
                "visual_description": "Macro cinematic shot of Earth's magnetic aurora lines flickering, shattering like glass, and fading away as intense solar radiation flares blast through the upper atmosphere.",
                "camera_movement": "Slow orbital spiral looking down at glowing ionized auroral ribbons vanishing into darkness.",
                "lighting": "Vibrant emerald green and purple aurora fading into harsh blinding white solar flares.",
                "mood": "Silent cosmic vulnerability.",
                "sfx_cue": "cosmic_energy_static"
            },
            {
                "scene_number": 5,
                "name": "Half Frozen, Half Scorched",
                "estimated_duration_sec": 9.0,
                "narration": "One side of the planet would endure six months of scorching daylight, while the other freezes in eternal darkness.",
                "visual_description": "Split planetary orbital perspective: the left half is a cracked, glowing orange desert wasteland with drying seas, while the right half is engulfed in blue ice sheets, glaciers, and eternal blizzard storms.",
                "camera_movement": "Slow cinematic roll centered right along the sharp planetary terminator line.",
                "lighting": "Blinding scorching sunlight on the day side contrasted with icy dark starlight on the night side.",
                "mood": "Alien, desolate, extreme survival.",
                "sfx_cue": "sub_bass_ambient_drone"
            },
            {
                "scene_number": 6,
                "name": "The Twilight Payoff",
                "estimated_duration_sec": 7.0,
                "narration": "The only place you could survive? A narrow, twilight strip between fire and ice. Would you make it?",
                "visual_description": "A cinematic push-in toward a thin glowing atmospheric ribbon between the frozen dark wasteland and scorching desert, a solitary silhouetted figure standing on a cliff edge looking out.",
                "camera_movement": "Smooth slow forward push-in behind the silhouette toward the horizon.",
                "lighting": "Golden hour twilight gradient fading into starry darkness.",
                "mood": "Mysterious, haunting, reflective ending.",
                "sfx_cue": "dramatic_ending_swell"
            }
        ]
    }

def save_storyboard(storyboard_data: Dict[str, Any], output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(storyboard_data, f, indent=2)
    print(f"[Stage 1] Storyboard saved to {output_path}")

    # Also save a human-readable markdown version
    md_path = output_path.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Storyboard: {storyboard_data.get('title')}\n\n")
        f.write(f"- **Aspect Ratio**: {storyboard_data.get('aspect_ratio')}\n")
        f.write(f"- **Target Duration**: ~{storyboard_data.get('target_duration_sec')} seconds\n")
        f.write(f"- **Visual Style**: {storyboard_data.get('style')}\n\n")
        f.write("## Scenes\n\n")
        for sc in storyboard_data.get("scenes", []):
            f.write(f"### Scene {sc['scene_number']}: {sc['name']} (~{sc['estimated_duration_sec']}s)\n")
            f.write(f"- **Narration**: \"{sc['narration']}\"\n")
            f.write(f"- **Visual**: {sc['visual_description']}\n")
            f.write(f"- **Camera**: {sc['camera_movement']}\n")
            f.write(f"- **Lighting & Mood**: {sc['lighting']} | *{sc['mood']}*\n")
            f.write(f"- **Audio SFX Cue**: `{sc['sfx_cue']}`\n\n")
    print(f"[Stage 1] Storyboard markdown saved to {md_path}")

if __name__ == "__main__":
    sb = create_earth_stops_storyboard()
    save_path = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating" / "storyboard.json"
    save_storyboard(sb, save_path)
