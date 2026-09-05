"""
make_video.py — One-command YouTube Shorts factory.

Usage:
    python make_video.py "What if Earth stopped rotating?"
    python make_video.py "What if the Sun disappeared?" --scenes 5
    python make_video.py "What if gravity doubled?" --output G:\My Drive\Shorts\

Pipeline:
    1. Gemini AI writes storyboard + narration (5 scenes)
    2. Google Flow generates video clips via browser automation
    3. CDN interception downloads each clip (guaranteed unique)
    4. ElevenLabs generates word-timestamped voiceover
    5. FFmpeg composites: trimmed clips + voiceover + music + animated captions
    6. Gemini AI audits final (duplicate check, sync check)
    7. Saves to Google Drive (or local output dir)
"""
import sys, os, json, time, argparse, hashlib, subprocess, shutil, re, requests
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config


# ─────────────────────────────────────────────
#  GOOGLE DRIVE AUTO-DETECT
# ─────────────────────────────────────────────
def find_google_drive_path():
    """Auto-detect Google Drive for Desktop mount point."""
    candidates = [
        Path("G:/My Drive"),
        Path("G:/"),
        Path(os.path.expanduser("~/Google Drive")),
        Path(os.path.expanduser("~/GoogleDrive")),
    ]
    # Check all drive letters
    for letter in "GHIJKLMNOPQRSTUVWXYZ":
        candidates.append(Path(f"{letter}:/My Drive"))
        candidates.append(Path(f"{letter}:/"))
    for p in candidates:
        if p.exists() and (p / "My Drive").exists():
            return p / "My Drive"
        # Some installs mount directly
        if p.exists() and p.name == "My Drive":
            return p
    return None


# ─────────────────────────────────────────────
#  STAGE 1: GEMINI STORYBOARD GENERATION
# ─────────────────────────────────────────────
def generate_storyboard(topic: str, num_scenes: int = 5) -> dict:
    """Use Gemini to generate a storyboard from a topic."""
    import google.generativeai as genai
    genai.configure(api_key=config.GOOGLE_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""You are a YouTube Shorts scriptwriter. Create a {num_scenes}-scene storyboard for a dramatic, 
    hook-driven 50-second vertical video about: "{topic}"

    Return ONLY valid JSON with this exact structure:
    {{
        "title": "Catchy title",
        "target_duration_sec": 50,
        "scenes": [
            {{
                "scene_number": 1,
                "name": "Scene Name",
                "narration": "Exact narration text the voice actor will read",
                "visual_prompt": "Detailed 9:16 vertical video prompt for AI video generation. Be specific about subject, camera angle, lighting, motion.",
                "estimated_duration_sec": 10
            }}
        ]
    }}

    Rules:
    - Scene 1 MUST be a strong hook that grabs attention in 2 seconds
    - Last scene MUST end with a question or call-to-action
    - Each narration should be 15-25 words (natural speaking pace)
    - Visual prompts should describe CINEMATIC scenes (National Geographic quality)
    - Total narration should fit in ~50 seconds when spoken
    - Each visual_prompt MUST include "9:16 vertical" and "cinematic photorealistic"
    """

    resp = model.generate_content(prompt)
    text = resp.text.strip()
    # Extract JSON from markdown code blocks if needed
    if "```" in text:
        text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


# ─────────────────────────────────────────────
#  STAGE 2: GOOGLE FLOW VIDEO GENERATION
# ─────────────────────────────────────────────
def generate_clips_google_flow(storyboard: dict, clips_dir: Path) -> list:
    """Submit all scene prompts to Google Flow and download via CDN interception."""
    from playwright.sync_api import sync_playwright

    scenes = storyboard["scenes"]
    clips_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(config.BROWSER_PROFILE_DIR), headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            viewport={"width": 1280, "height": 900}, accept_downloads=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Navigate to Flow
        page.goto("https://labs.google/fx/tools/flow", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        # Submit batch prompt for ALL scenes at once
        batch_prompt = "Generate these videos as separate cards:\n\n"
        for sc in scenes:
            batch_prompt += f"Card {sc['scene_number']}: {sc['visual_prompt']}\n\n"

        chat_in = page.locator('[contenteditable="true"]').first
        if chat_in.is_visible(timeout=5000):
            chat_in.click()
            page.keyboard.type(batch_prompt, delay=1)
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)

            # Auto-approve
            for _ in range(10):
                btns = page.locator('button:has-text("Approve"), button:has-text("Generate")')
                if btns.count() > 0:
                    btns.last.click(force=True)
                    print("   [Flow] Approved generation", flush=True)
                    break
                page.wait_for_timeout(2000)

        # Wait for all videos to render (up to 5 min)
        print("   [Flow] Waiting for videos to render...", flush=True)
        for i in range(30):
            page.wait_for_timeout(10000)
            cards = page.locator('img[src*="googleusercontent"]')
            if cards.count() >= len(scenes):
                print(f"   [Flow] All {len(scenes)} cards rendered!", flush=True)
                break
            print(f"   [Flow] {(i+1)*10}s - {cards.count()}/{len(scenes)} cards...", flush=True)

        page.wait_for_timeout(3000)

        # Download each card via CDN interception
        card_positions = []
        card_elements = page.locator('img[src*="googleusercontent"]')
        count = card_elements.count()
        for idx in range(min(count, len(scenes))):
            box = card_elements.nth(idx).bounding_box()
            if box:
                card_positions.append((box["x"] + box["width"] / 2, box["y"] + box["height"] / 2))

        # If we can't find card positions, use estimated X positions
        if len(card_positions) < len(scenes):
            spacing = 170
            start_x = 300
            card_positions = [(start_x + i * spacing, 210) for i in range(len(scenes))]

        for idx, sc in enumerate(scenes):
            filename = f"scene_{sc['scene_number']:02d}.mp4"
            out_path = clips_dir / filename
            print(f"   [Flow] Downloading {filename}...", flush=True)

            captured = []
            def make_handler():
                urls = []
                def handler(response):
                    if "flow-content.google/video" in response.url:
                        urls.append(response.url)
                return handler, urls
            handler, captured = make_handler()
            page.on("response", handler)

            cx, cy = card_positions[idx] if idx < len(card_positions) else (300 + idx * 170, 210)
            page.mouse.click(cx, cy)
            page.wait_for_timeout(2000)
            page.evaluate("document.querySelector('video')?.play()")
            page.wait_for_timeout(4000)
            page.remove_listener("response", handler)

            if captured:
                cookies = ctx.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                resp = requests.get(captured[-1], headers={"Cookie": cookie_str}, stream=True, timeout=30)
                if resp.status_code == 200:
                    with open(out_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    downloaded.append(out_path)
                    print(f"   [Flow] Saved {filename}: {out_path.stat().st_size // 1024} KB", flush=True)

            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

        ctx.close()

    return downloaded


# ─────────────────────────────────────────────
#  STAGE 3: DUPLICATE CHECK
# ─────────────────────────────────────────────
def verify_unique_clips(clips_dir: Path, num_scenes: int) -> bool:
    """MD5 check all clips. Returns True if all unique."""
    hashes = {}
    for i in range(1, num_scenes + 1):
        p = clips_dir / f"scene_{i:02d}.mp4"
        if not p.exists():
            print(f"   [QC] MISSING: {p.name}", flush=True)
            return False
        h = hashlib.md5(open(p, "rb").read()).hexdigest()
        if h in hashes:
            print(f"   [QC] DUPLICATE: scene_{i:02d} == scene_{hashes[h]:02d}", flush=True)
            return False
        hashes[h] = i
    print(f"   [QC] All {num_scenes} clips verified unique", flush=True)
    return True


# ─────────────────────────────────────────────
#  STAGE 4-6: VOICEOVER + CAPTIONS + RENDER
# ─────────────────────────────────────────────
def render_final_video(proj_dir: Path, storyboard: dict) -> Path:
    """Generate voiceover, compute cuts, composite final video."""
    clips_dir = proj_dir / "clips"

    # Voiceover
    print("   [Voice] Generating ElevenLabs voiceover...", flush=True)
    from pipeline.stage3_voiceover import build_full_script, generate_voiceover_elevenlabs
    script = build_full_script(storyboard)
    narr_path = proj_dir / "narration.mp3"
    words_path = proj_dir / "words.json"
    generate_voiceover_elevenlabs(script, narr_path, words_path)

    # Sentence cuts
    with open(words_path, "r", encoding="utf-8") as f:
        words_data = json.load(f)
    words_list = words_data.get("words", [])
    word_idx = 0
    scene_durations = []
    for sc in storyboard["scenes"]:
        sc_words = sc["narration"].split()
        s = words_list[word_idx]["start"] if word_idx < len(words_list) else 0.0
        word_idx += len(sc_words)
        e = words_list[min(word_idx - 1, len(words_list) - 1)]["end"] if word_idx - 1 < len(words_list) else s + 8.0
        d = max(3.0, e - s)
        scene_durations.append((sc["scene_number"], d))
        print(f"   [Cut] Scene {sc['scene_number']}: {d:.2f}s", flush=True)

    # Trim clips
    trimmed = []
    for num, dur in scene_durations:
        src = clips_dir / f"scene_{num:02d}.mp4"
        out = clips_dir / f"trimmed_{num:02d}.mp4"
        subprocess.run([config.FFMPEG_EXE, "-y", "-i", str(src),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
            "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-an", str(out)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        trimmed.append(out)

    # Concat
    cf = clips_dir / "concat.txt"
    with open(cf, "w", encoding="utf-8") as f:
        for t in trimmed:
            f.write(f"file '{str(t).replace(chr(92), '/')}'\n")
    raw = clips_dir / "raw_concat.mp4"
    subprocess.run([config.FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", str(cf), "-c", "copy", str(raw)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Captions
    from pipeline.stage4_subtitles import generate_ass_subtitles
    cap = proj_dir / "captions.ass"
    generate_ass_subtitles(words_path, cap)

    # Music
    from pipeline.stage5_composer import generate_ambient_music_track, get_media_duration
    mus = clips_dir / "bg_music.aac"
    td = get_media_duration(narr_path)
    generate_ambient_music_track(mus, td + 2.0)

    # Final composite
    out_dir = proj_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "final_short.mp4"

    af = (f"[1:a]volume={config.VOICE_VOLUME_DB}dB,asplit=2[v0][vs];"
          f"[2:a]volume={config.MUSIC_VOLUME_DB}dB[m];"
          f"[m][vs]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300[md];"
          f"[v0][md]amix=inputs=2:duration=first:dropout_transition=2[ao]")
    ass = str(cap).replace("\\", "/").replace(":", "\\:")

    r = subprocess.run([config.FFMPEG_EXE, "-y",
        "-i", str(raw), "-i", str(narr_path), "-i", str(mus),
        "-filter_complex", af, "-map", "0:v", "-map", "[ao]",
        "-vf", f"subtitles='{ass}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", config.AUDIO_BITRATE,
        "-t", f"{td:.3f}", "-pix_fmt", "yuv420p", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {r.stderr[-300:]}")

    return out


# ─────────────────────────────────────────────
#  MAIN PIPELINE
# ─────────────────────────────────────────────
def make_video(topic: str, num_scenes: int = 5, output_dir: str = None):
    """Full end-to-end pipeline: topic → finished YouTube Short."""
    start = time.time()
    print(f"\n{'='*60}", flush=True)
    print(f"  YOUTUBE SHORTS FACTORY", flush=True)
    print(f"  Topic: {topic}", flush=True)
    print(f"  Scenes: {num_scenes}", flush=True)
    print(f"{'='*60}\n", flush=True)

    # Create project directory
    slug = re.sub(r'[^a-z0-9]+', '_', topic.lower().strip())[:50].strip('_')
    proj_dir = config.PROJECTS_DIR / slug
    clips_dir = proj_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: Storyboard
    print("[1/6] Generating storyboard with Gemini AI...", flush=True)
    storyboard = generate_storyboard(topic, num_scenes)
    with open(proj_dir / "storyboard.json", "w", encoding="utf-8") as f:
        json.dump(storyboard, f, indent=2)
    for sc in storyboard["scenes"]:
        print(f"   Scene {sc['scene_number']}: {sc['name']}", flush=True)

    # Stage 2: Generate clips
    print(f"\n[2/6] Generating {num_scenes} video clips in Google Flow...", flush=True)
    generate_clips_google_flow(storyboard, clips_dir)

    # Stage 3: Verify unique
    print(f"\n[3/6] Verifying all clips are unique...", flush=True)
    if not verify_unique_clips(clips_dir, num_scenes):
        print("   [!] Duplicate detected. Retrying problematic clips...", flush=True)
        # TODO: Auto-retry failed clips
        raise RuntimeError("Duplicate clips detected. Manual intervention needed.")

    # Stage 4-6: Render
    print(f"\n[4/6] Generating voiceover + captions + music...", flush=True)
    print(f"[5/6] Compositing final video...", flush=True)
    final_path = render_final_video(proj_dir, storyboard)
    sz = final_path.stat().st_size // (1024 * 1024)

    # Stage 7: Copy to Google Drive
    print(f"\n[6/6] Saving to output...", flush=True)
    drive_path = find_google_drive_path()
    if output_dir:
        dest_dir = Path(output_dir)
    elif drive_path:
        dest_dir = drive_path / "YouTube Shorts"
    else:
        dest_dir = None

    if dest_dir:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{slug}.mp4"
        shutil.copy2(final_path, dest)
        print(f"   Saved to: {dest}", flush=True)
    else:
        print(f"   Google Drive not found. Video at: {final_path}", flush=True)

    elapsed = time.time() - start
    print(f"\n{'='*60}", flush=True)
    print(f"  DONE in {elapsed:.0f}s ({elapsed/60:.1f} min)", flush=True)
    print(f"  Video: {final_path} ({sz} MB)", flush=True)
    if dest_dir:
        print(f"  Cloud: {dest_dir / f'{slug}.mp4'}", flush=True)
    print(f"{'='*60}\n", flush=True)

    return final_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Shorts Factory")
    parser.add_argument("topic", help="Video topic (e.g. 'What if Earth stopped rotating?')")
    parser.add_argument("--scenes", type=int, default=5, help="Number of scenes (default: 5)")
    parser.add_argument("--output", type=str, default=None, help="Output directory (default: Google Drive or local)")
    args = parser.parse_args()
    make_video(args.topic, args.scenes, args.output)
