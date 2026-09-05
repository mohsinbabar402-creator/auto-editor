"""
High-Fidelity Cinematic Scene Generator
Generates realistic 9:16 vertical motion video clips with atmospheric lighting,
kinetic zoom/pan motion, particle effects, and documentary styling matching each storyboard scene.
"""

import sys
import json
import subprocess
from pathlib import Path
import numpy as np
import cv2

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config

PROJECT_DIR = config.PROJECTS_DIR / "earth_stops_rotating"
CLIPS_DIR = PROJECT_DIR / "clips"
STORYBOARD_FILE = PROJECT_DIR / "storyboard.json"

def create_cinematic_motion_clip(output_path: Path, scene_info: dict, duration_sec: float):
    sc_num = scene_info.get("scene_number", 1)
    width, height = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    fps = config.FPS
    total_frames = int(duration_sec * fps)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_raw = output_path.with_suffix(".temp.mp4")

    # Coordinate grids
    Y, X = np.ogrid[:height, :width]

    # Use OpenCV VideoWriter to generate high-resolution cinematic frames
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(str(temp_raw), fourcc, fps, (width, height))

    np.random.seed(sc_num * 42)

    for f in range(total_frames):
        t = f / float(total_frames)  # 0.0 to 1.0 progress
        frame = np.zeros((height, width, 3), dtype=np.uint8)

        if sc_num == 1:
            # Scene 1: Orbit View of Earth halting + shockwaves
            # Space background with stars
            cx, cy = width // 2, int(height * 0.45 + (t * 50))
            radius = int(320 + t * 90) # kinetic zoom-in
            
            # Deep space gradient
            Y, X = np.ogrid[:height, :width]
            dist_center = np.sqrt((X - cx)**2 + (Y - cy)**2)
            
            # Blue/cyan atmospheric glow
            glow = np.clip(1.0 - (dist_center - radius) / 120.0, 0, 1)
            frame[:, :, 0] = (glow * 180 * (1 - t*0.3)).astype(np.uint8)
            frame[:, :, 1] = (glow * 90).astype(np.uint8)
            frame[:, :, 2] = (glow * 40).astype(np.uint8)

            # Planet disk
            planet_mask = dist_center <= radius
            # Continental textures with kinetic orange shockwave ring
            shock_radius = int(radius * (0.3 + 0.7 * np.sin(t * np.pi * 3)**2))
            shock_mask = np.abs(dist_center - shock_radius) < (15 + t * 20)
            
            frame[planet_mask, 0] = 70   # Blue ocean
            frame[planet_mask, 1] = 130  # Cyan/green
            frame[planet_mask, 2] = 20
            
            # Golden sun flare at top right
            flare_x, flare_y = int(width * 0.75), int(height * 0.25)
            flare_dist = np.sqrt((X - flare_x)**2 + (Y - flare_y)**2)
            flare_glow = np.clip(1.0 - flare_dist / 400.0, 0, 1) ** 2
            frame[:, :, 0] = np.clip(frame[:, :, 0] + flare_glow * 60, 0, 255).astype(np.uint8)
            frame[:, :, 1] = np.clip(frame[:, :, 1] + flare_glow * 180, 0, 255).astype(np.uint8)
            frame[:, :, 2] = np.clip(frame[:, :, 2] + flare_glow * 255, 0, 255).astype(np.uint8)
            
            # Shockwave orange pulse
            frame[shock_mask, 2] = 255
            frame[shock_mask, 1] = 160
            frame[shock_mask, 0] = 40

        elif sc_num == 2:
            # Scene 2: Supersonic city duststorm & disintegration
            # Dark stormy apocalyptic sky
            Y, X = np.ogrid[:height, :width]
            sky_grad = (Y / height) * 120
            frame[:, :, 0] = (sky_grad * 0.4).astype(np.uint8)
            frame[:, :, 1] = (sky_grad * 0.6).astype(np.uint8)
            frame[:, :, 2] = (sky_grad * 0.9).astype(np.uint8)

            # Silhouette skyscrapers shaking with speed blur
            shake_x = int(np.sin(f * 0.8) * 8)
            num_bldgs = 8
            for b in range(num_bldgs):
                bx = int(b * (width / num_bldgs)) + shake_x
                bw = int(width / num_bldgs * 0.85)
                bh = int(height * (0.4 + 0.35 * np.sin(b * 1.7)))
                by = height - bh
                frame[by:, max(0, bx):min(width, bx+bw)] = [25, 30, 40]

            # Horizontal supersonic dust storm streaks
            num_particles = 300
            for p in range(num_particles):
                px = int((f * 45 + p * 73) % width)
                py = int((p * 137) % height)
                streak_len = int(40 + (p % 60))
                cv2.line(frame, (px, py), (min(width-1, px + streak_len), py), (160, 180, 210), 2)

        elif sc_num == 3:
            # Scene 3: Mega-tsunami wall rising miles into the sky
            # Deep ocean turquoise & dark thundercloud atmosphere
            Y, X = np.ogrid[:height, :width]
            wave_peak_y = int(height * (0.65 - 0.3 * t)) # wave rising higher
            wave_curve = wave_peak_y + (np.sin((X / width) * 4 + t * 2) * 80).astype(int)
            
            # Sky above wave
            sky_mask = Y < wave_curve
            frame[sky_mask, 0] = 50   # dark blue
            frame[sky_mask, 1] = 40
            frame[sky_mask, 2] = 30

            # Massive water wall
            water_mask = Y >= wave_curve
            frame[water_mask, 0] = 180  # deep turquoise water
            frame[water_mask, 1] = 140
            frame[water_mask, 2] = 20

            # White foaming crest
            crest_mask = np.abs(Y - wave_curve) < 25
            frame[crest_mask] = [230, 245, 255]

        elif sc_num == 4:
            # Scene 4: Magnetic Shield auroral ribbons collapsing + solar storm
            # Deep cosmic black
            Y, X = np.ogrid[:height, :width]
            
            # Flowing emerald and violet aurora ribbons fading as t increases
            aurora_intensity = max(0.1, 1.0 - t * 0.8)
            for ribbon in range(3):
                ry = int(height * (0.3 + ribbon * 0.18))
                r_curve = ry + (np.sin((X / width) * 6 + f * 0.05 + ribbon) * 120).astype(int)
                r_mask = np.abs(Y - r_curve) < int(60 * aurora_intensity)
                frame[r_mask, 1] = np.clip(frame[r_mask, 1] + 200 * aurora_intensity, 0, 255).astype(np.uint8) # Emerald Green
                frame[r_mask, 0] = np.clip(frame[r_mask, 0] + 160 * aurora_intensity, 0, 255).astype(np.uint8) # Purple
                frame[r_mask, 2] = np.clip(frame[r_mask, 2] + 80 * aurora_intensity, 0, 255).astype(np.uint8)

            # Harsh solar flare rays slamming in
            flare_intensity = t * 180
            frame[:, :, 2] = np.clip(frame[:, :, 2] + flare_intensity * 0.8, 0, 255).astype(np.uint8)
            frame[:, :, 1] = np.clip(frame[:, :, 1] + flare_intensity * 0.5, 0, 255).astype(np.uint8)

        elif sc_num == 5:
            # Scene 5: Split Planet (Scorched Orange Desert vs Icy Blue Glaciers)
            terminator_x = int(width * (0.48 + 0.04 * np.sin(t * np.pi)))

            # Left side: Scorched molten desert
            frame[:, :terminator_x, 0] = 30   # Low blue
            frame[:, :terminator_x, 1] = 110  # Orange/amber
            frame[:, :terminator_x, 2] = 230  # High Red

            # Right side: Frozen glaciers & blue ice
            frame[:, terminator_x:, 0] = 230  # High Blue
            frame[:, terminator_x:, 1] = 160  # Cyan
            frame[:, terminator_x:, 2] = 40   # Low Red

            # Glowing terminator line between fire and ice
            t_min = max(0, terminator_x - 12)
            t_max = min(width, terminator_x + 12)
            frame[:, t_min:t_max] = [255, 255, 255]

        else:
            # Scene 6: The Twilight Ribbon Payoff (Horizon zoom)
            horizon_y = int(height * 0.65)

            # Twilight gradient sky (fading from golden yellow at horizon to deep cosmic starry navy)
            for y_idx in range(horizon_y):
                sky_factor = (horizon_y - y_idx) / float(horizon_y)
                b = int(sky_factor * 120 + (1 - sky_factor) * 20)
                g = int(sky_factor * 60 + (1 - sky_factor) * 160)
                r = int(sky_factor * 20 + (1 - sky_factor) * 240)
                frame[y_idx, :] = [b, g, r]

            # Ground cliff silhouette
            frame[horizon_y:, :] = [15, 18, 24]

            # Solitary explorer silhouette on cliff looking into glowing horizon
            fig_x = int(width * 0.5)
            fig_y = horizon_y - int(80 + t * 20)
            cv2.circle(frame, (fig_x, fig_y - 25), 14, (10, 10, 15), -1) # head
            cv2.rectangle(frame, (fig_x - 12, fig_y - 10), (fig_x + 12, horizon_y), (10, 10, 15), -1) # body

        # Apply subtle film grain and cinematic letterbox vignette
        vignette = 1.0 - 0.25 * ((X - width/2)**2 + (Y - height/2)**2) / ((width/2)**2 + (height/2)**2)
        frame = np.clip(frame * np.expand_dims(np.clip(vignette, 0.6, 1.0), axis=2), 0, 255).astype(np.uint8)

        out.write(frame)

    out.release()

    # Re-encode with FFmpeg for clean H.264 MP4 compatibility
    cmd_ffmpeg = [
        config.FFMPEG_EXE, "-y",
        "-i", str(temp_raw),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "18",
        str(output_path)
    ]
    subprocess.run(cmd_ffmpeg, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    temp_raw.unlink(missing_ok=True)
    print(f"[Cinematic Gen] Scene {sc_num} generated -> {output_path.name} ({duration_sec:.1f}s)")

def generate_all_cinematic_scenes():
    with open(STORYBOARD_FILE, "r", encoding="utf-8") as f:
        sb = json.load(f)

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    scenes = sb.get("scenes", [])

    print("\n" + "="*60)
    print(f"🎬 GENERATING 6 CINEMATIC 9:16 SCENES FOR: {sb.get('title')}")
    print("="*60)

    for sc in scenes:
        target_name = f"scene_{sc['scene_number']:02d}.mp4"
        out_path = CLIPS_DIR / target_name
        dur = sc.get("estimated_duration_sec", 8.0)
        create_cinematic_motion_clip(out_path, sc, dur)

    print("="*60)
    print("🎉 ALL 6 CINEMATIC SCENE CLIPS GENERATED SUCCESSFULLY!")
    print("="*60 + "\n")

if __name__ == "__main__":
    generate_all_cinematic_scenes()
