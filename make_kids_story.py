"""
make_kids_story.py — Dedicated Kids Story Time Factory for YouTube Shorts.

Usage:
    python make_kids_story.py "The Little Star Who Lost Her Twinkle" --voice george
    python make_kids_story.py "Barnaby Bear and the Runaway Pancake" --voice jessica
    python make_kids_story.py --topics 10
    python make_kids_story.py "Pip and the Giant Blueberry" --script-only
"""
import sys
import os
import json
import time
import argparse
import hashlib
import subprocess
import shutil
import re
import requests
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

# Channel Root
KIDS_CHANNEL_DIR = config.PROJECTS_DIR / "03_kids_stories"

# Curated Voice Map for Kids Stories
KIDS_VOICE_MAP = {
    "jessica": {
        "id": "cgSgspJ2msm6clMCkdW9",
        "name": "Jessica",
        "style": "Playful, Bright, Warm, American Cute",
        "best_for": "Upbeat, energetic animal adventures & cheerful stories"
    },
    "george": {
        "id": "JBFqnCBsd6RMkjVDRZzb",
        "name": "George",
        "style": "Warm, Captivating Storyteller, British Mature",
        "best_for": "Bedtime stories, classic gentle fables, soothing tales"
    },
    "alice": {
        "id": "Xb7hH8MSUJpSbSDYk0k2",
        "name": "Alice",
        "style": "Clear, Engaging Educator, British Professional",
        "best_for": "Nature mysteries, curious science, learning adventures"
    },
    "bella": {
        "id": "hpp4J3VqNfWAUOO0d1Us",
        "name": "Bella",
        "style": "Professional, Bright, Warm",
        "best_for": "Heartwarming character stories"
    }
}

DEFAULT_KIDS_VOICE = "jessica"

def _call_gemini(prompt: str) -> str:
    """Helper to query Gemini 3.6 Flash via direct REST endpoint."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={config.GOOGLE_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7}
    }
    resp = requests.post(url, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API Error {resp.status_code}: {resp.text}")
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


# ─────────────────────────────────────────────
#  STAGE 0: VIRAL TOPIC GENERATOR
# ─────────────────────────────────────────────
def generate_kids_topics(count: int = 10, category: str = "all") -> list:
    """Use Gemini to generate viral, cute, captivating Kids Story Shorts concepts."""
    prompt = f"""You are a master creative director for top-tier viral YouTube Kids Shorts.
Generate {count} unique, heartwarming, and visual story ideas for 50-second animated shorts (Ages 3-8).

Categories to include:
1. Cute Animal Adventures with Big Hearts (e.g. timid bears, curious bunnies, brave mice)
2. Cozy Bedtime & Slumberland Tales (e.g. sleepy clouds, moon's cozy blanket, stars playing hide-and-seek)
3. Magical Fables with Sweet Lessons (e.g. sharing, kindness, finding courage)
4. Whimsical Wonders of Nature (e.g. why fireflies glow, how rainbows get their stripes)

Requirements:
- Each title should be catchy, charming, and spark instant curiosity.
- Return ONLY a valid JSON array of objects with keys: "title", "category", "hero_character", "one_sentence_hook", "recommended_voice" ('jessica' or 'george').
"""
    raw_text = _call_gemini(prompt).strip()
    if "```" in raw_text:
        raw_text = raw_text.split("```json")[-1].split("```")[0] if "```json" in raw_text else raw_text.split("```")[1].split("```")[0]
    return json.loads(raw_text.strip())


# ─────────────────────────────────────────────
#  STAGE 1: GEMINI KIDS STORYBOARD & SCRIPTWRITING
# ─────────────────────────────────────────────
def generate_kids_storyboard(topic: str, num_scenes: int = 5, voice_name: str = "jessica") -> dict:
    """Use Gemini to write a 50-second, 5-scene animated storyboard in 3D Pixar/Disney aesthetic."""
    voice_info = KIDS_VOICE_MAP.get(voice_name.lower(), KIDS_VOICE_MAP[DEFAULT_KIDS_VOICE])

    prompt = f"""You are a master writer and animator for top-performing YouTube Kids Shorts (Ages 3-8).
Create a {num_scenes}-scene storyboard for a delightful, animated 50-second vertical video about: "{topic}"

The narration will be voiced by {voice_info['name']} ({voice_info['style']}).

Return ONLY valid JSON with this exact schema:
{{
    "title": "{topic}",
    "theme": "Core moral or emotional takeaway",
    "voice": "{voice_name.lower()}",
    "voice_id": "{voice_info['id']}",
    "target_duration_sec": 50,
    "scenes": [
        {{
            "scene_number": 1,
            "name": "The Magical Hook",
            "narration": "Exact 15-22 word engaging narration for kids, enthusiastic and warm.",
            "visual_prompt": "3D Pixar Disney style animation, 9:16 vertical, vibrant saturated colors, [detailed description of cute character with expressive big sparkling eyes, whimsical environment, soft magical lighting, camera action], 8k render, masterpiece",
            "estimated_duration_sec": 10
        }}
    ]
}}

STRICT STORY RULES:
1. Scene 1: Instant adorable hook that grabs toddlers & kids in the first 2 seconds.
2. Scene 2: The playful dilemma or funny obstacle.
3. Scene 3: A surprising magical discovery or helpful friend.
4. Scene 4: The heartwarming triumph where kindness, bravery, or teamwork wins.
5. Scene 5: Sweet moral payoff or gentle bedtime send-off + friendly question (e.g., 'Have you ever hugged a cloud? Sweet dreams, little dreamer!').
6. Visual Prompts MUST explicitly start with: '3D Pixar Disney style animation, 9:16 vertical, vibrant saturated colors'
7. Absolutely ZERO scary elements, uncanny designs, dark shadows, or loud violence. Pure charm, whimsy, and delight.
8. Each narration line must be 15 to 22 words (natural spoken pace for young kids).
"""
    raw_text = _call_gemini(prompt).strip()
    if "```" in raw_text:
        raw_text = raw_text.split("```json")[-1].split("```")[0] if "```json" in raw_text else raw_text.split("```")[1].split("```")[0]
    return json.loads(raw_text.strip())


# ─────────────────────────────────────────────
#  STAGE 2: CAPTIONS FOR KIDS (PLAYFUL & WARM)
# ─────────────────────────────────────────────
def generate_kids_ass_captions(words_data_path: Path, output_ass_path: Path) -> Path:
    """Generates bouncy, child-friendly ASS captions with vibrant warm highlights."""
    with open(words_data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words", [])
    if not words:
        return output_ass_path

    from pipeline.stage4_subtitles import format_ass_timestamp, group_words_into_chunks

    chunks = group_words_into_chunks(words, max_words_per_chunk=3)

    # Use Comic Sans MS or Segoe UI for cheerful, legible kids' aesthetic
    font_name = "Comic Sans MS"
    # Vivid golden yellow highlight in ASS BBGGRR: &H0000E5FF (Yellow-Gold)
    primary_white = "&H00FFFFFF"
    highlight_color = "&H0000FFFF" # Vivid Yellow
    outline_black = "&H00000000"

    ass_header = f"""[Script Info]
Title: Kids Story Time Animated Captions
ScriptType: v4.00+
PlayResX: {config.VIDEO_WIDTH}
PlayResY: {config.VIDEO_HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: KidsDefault,{font_name},76,{primary_white},&H000000FF,{outline_black},&H60000000,-1,0,0,0,100,100,2,0,1,6,3,2,60,60,{config.CAPTION_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogue_lines = []
    for chunk in chunks:
        chunk_start = chunk[0]["start"]
        chunk_end = max(chunk[-1]["end"], chunk_start + 0.3)

        for i, target_word in enumerate(chunk):
            w_start = target_word["start"]
            w_end = chunk[i + 1]["start"] if i + 1 < len(chunk) else chunk_end

            w_start_str = format_ass_timestamp(w_start)
            w_end_str = format_ass_timestamp(w_end)

            text_parts = []
            for j, w in enumerate(chunk):
                word_clean = w["word"]
                if j == i:
                    text_parts.append(f"{{\\c{highlight_color}\\t(0,100,\\fscx115\\fscy115)}}{word_clean}{{\\r}}")
                else:
                    text_parts.append(f"{{\\c{primary_white}}}{word_clean}{{\\r}}")

            line_text = " ".join(text_parts)
            dialogue_lines.append(f"Dialogue: 0,{w_start_str},{w_end_str},KidsDefault,,0,0,0,,{line_text}")

    output_ass_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogue_lines) + "\n")
    return output_ass_path


# ─────────────────────────────────────────────
#  STAGE 3: FULL PRODUCTION RUNNER
# ─────────────────────────────────────────────
def produce_kids_story(
    topic: str,
    voice_name: str = "jessica",
    script_only: bool = False,
    use_dry_run: bool = False,
    run_browser: bool = False
):
    """Orchestrates creation of a complete Kids Story Short."""
    slug = re.sub(r'[^a-z0-9]+', '_', topic.lower().strip())[:50].strip('_')
    proj_dir = KIDS_CHANNEL_DIR / slug
    proj_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "="*65)
    print(f"🧸 KIDS STORY TIME FACTORY: \"{topic}\"")
    print(f"Narrator: {voice_name.upper()} ({KIDS_VOICE_MAP.get(voice_name, {}).get('name', 'Default')})")
    print(f"Output Directory: {proj_dir}")
    print("="*65 + "\n")

    # Step 1: Storyboard & Script
    print("[1/5] ✍️ Generating 3D Pixar Storyboard with Gemini AI...", flush=True)
    storyboard = generate_kids_storyboard(topic, num_scenes=5, voice_name=voice_name)
    
    sb_file = proj_dir / "storyboard.json"
    with open(sb_file, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, indent=2)

    # Human-readable prompt doc
    prompts_md = proj_dir / "google_flow_prompts.md"
    with open(prompts_md, "w", encoding="utf-8") as f:
        f.write(f"# 🧸 Kids Story: {storyboard['title']}\n\n")
        f.write(f"**Theme:** {storyboard.get('theme', 'N/A')}\n")
        f.write(f"**Voice:** {voice_name.capitalize()} (ElevenLabs ID: `{storyboard['voice_id']}`)\n\n")
        f.write("| Scene | Name | Narration | 9:16 Veo / Flow Prompt |\n")
        f.write("| :---: | :--- | :--- | :--- |\n")
        for sc in storyboard["scenes"]:
            f.write(f"| **Scene {sc['scene_number']}** | {sc['name']} | *\"{sc['narration']}\"* | `{sc['visual_prompt']}` |\n")

    print(f"   ✓ Storyboard & Prompts saved to {prompts_md.name}")
    for sc in storyboard["scenes"]:
        print(f"   Scene {sc['scene_number']}: {sc['name']}")
        print(f"     Narrator: \"{sc['narration']}\"")

    if script_only:
        print("\n✨ Script-only mode finished! Check generated prompts in:")
        print(f"   {prompts_md}")
        return

    # Step 2: Voiceover Generation
    narr_audio = proj_dir / "narration.mp3"
    words_json = proj_dir / "words.json"
    print(f"\n[2/5] 🎙️ Generating ElevenLabs Voiceover with {voice_name.capitalize()}...", flush=True)
    
    from pipeline.stage3_voiceover import build_full_script, generate_voiceover_elevenlabs
    full_script = build_full_script(storyboard)
    voice_id = storyboard.get("voice_id", KIDS_VOICE_MAP[DEFAULT_KIDS_VOICE]["id"])
    
    if not use_dry_run:
        generate_voiceover_elevenlabs(full_script, narr_audio, words_json, voice_id=voice_id)
        print(f"   ✓ Voiceover generated: {narr_audio.name}")
    else:
        print("   [Dry Run] Simulated voiceover step.")

    # Step 3: Captions
    print("\n[3/5] 🎨 Creating Dynamic Kids Captions (Comic Sans / Sunny Gold)...", flush=True)
    captions_file = proj_dir / "captions.ass"
    if words_json.exists():
        generate_kids_ass_captions(words_json, captions_file)
        print(f"   ✓ Captions saved: {captions_file.name}")

    # Summary
    print("\n" + "="*65)
    print(f"🎉 Episode \"{storyboard['title']}\" is fully staged!")
    print(f"Storyboard: {sb_file}")
    print(f"Flow Prompts: {prompts_md}")
    if narr_audio.exists():
        print(f"Narration: {narr_audio}")
    print("="*65 + "\n")


# ─────────────────────────────────────────────
#  CLI INTERFACE
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kids Story Time AI Video Factory")
    parser.add_argument("topic", nargs="?", help="Story topic or character title")
    parser.add_argument("--voice", choices=["jessica", "george", "alice", "bella"], default="jessica",
                        help="ElevenLabs voice (jessica=playful, george=bedtime, alice=curious)")
    parser.add_argument("--topics", type=int, help="Auto-generate N viral Kids Story topics")
    parser.add_argument("--script-only", action="store_true", help="Generate storyboard and prompts only")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without ElevenLabs or browser")
    args = parser.parse_args()

    if args.topics:
        print(f"Generating {args.topics} viral Kids Story concepts with Gemini 2.0 Flash...\n")
        topics_list = generate_kids_topics(args.topics)
        print(json.dumps(topics_list, indent=2))
        
        # Save to channel catalog
        catalog_path = KIDS_CHANNEL_DIR / "viral_topics_catalog.json"
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump(topics_list, f, indent=2)
        print(f"\nSaved topics catalog to: {catalog_path}")

    elif args.topic:
        produce_kids_story(
            topic=args.topic,
            voice_name=args.voice,
            script_only=args.script_only,
            use_dry_run=args.dry_run
        )
    else:
        parser.print_help()
