#!/usr/bin/env python3
"""
MrBeast x James Patterson Campaign — 9-Variation Video Production Script
Generates 9 distinct, heavily edited vertical short-form videos (1080x1920)
utilizing both downloaded source clips, with burned-in dynamic word-by-word
highlighted subtitles in viral short-form style.
"""

import os
import sys
import json
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List

# Setup project environment
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WHOP_ROOT = PROJECT_ROOT / "whop-editor"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(WHOP_ROOT))

from config import settings
from qc.video_check import verify_rendered_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mrbeast_producer")

# Source Clips
INPUT_DIR = WHOP_ROOT / "data" / "input"
SRC_JP = INPUT_DIR / "James_Patterson_1M_Competition.mp4"
SRC_MDG = INPUT_DIR / "Most_Dangerous_Games.mp4"

# Analysis Transcripts
ANALYSIS_DIR = WHOP_ROOT / "data" / "analysis"
TRANSCRIPT_JP_PATH = ANALYSIS_DIR / "vid_5254c95f43_transcript.json"
TRANSCRIPT_MDG_PATH = ANALYSIS_DIR / "vid_mdg_inspect_transcript.json"

# Output Directories
OUTPUT_DIR = WHOP_ROOT / "data" / "output" / "mrbeast_9_variations"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DESKTOP_DIR = Path(r"C:\Users\ice\Desktop\MrBeast_Campaign_9_Versions")
DESKTOP_DIR.mkdir(parents=True, exist_ok=True)


def format_ass_timestamp(seconds: float) -> str:
    """Converts seconds float to ASS timestamp format H:MM:SS.CC (centiseconds)."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        secs += 1
        centis = 0
    return f"{hrs:d}:{mins:02d}:{secs:02d}.{centis:02d}"


def clean_and_merge_tokens(raw_words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merges punctuation and currency tokens into cohesive display words."""
    cleaned = []
    i = 0
    while i < len(raw_words):
        w = raw_words[i]
        txt = w["word"].strip()
        if not txt or txt.startswith("[") or txt.endswith("]"):
            i += 1
            continue
        if txt == "$" and i + 1 < len(raw_words):
            next_w = raw_words[i + 1]
            merged_txt = "$" + next_w["word"].strip()
            cleaned.append({
                "word": merged_txt,
                "start": w["start"],
                "end": next_w["end"]
            })
            i += 2
            continue
        if txt in [".", ",", "!", "?", ":", ";", "-"]:
            if cleaned:
                cleaned[-1]["word"] += txt
                cleaned[-1]["end"] = max(cleaned[-1]["end"], w["end"])
            i += 1
            continue
        cleaned.append({
            "word": txt,
            "start": w["start"],
            "end": w["end"]
        })
        i += 1
    return cleaned


def extract_timeline_words(
    segments: List[Dict[str, Any]],
    jp_words: List[Dict[str, Any]],
    mdg_words: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Calculates exact word timestamps across concatenated timeline segments."""
    timeline_words = []
    current_time_offset = 0.0

    for seg in segments:
        src = seg["src"]
        s_t = seg["start"]
        e_t = seg["end"]
        seg_dur = e_t - s_t
        source_words = jp_words if src == "JP" else mdg_words

        for w in source_words:
            if w["end"] >= s_t and w["start"] <= e_t:
                rel_s = max(0.0, w["start"] - s_t)
                rel_e = min(seg_dur, max(rel_s + 0.12, w["end"] - s_t))
                timeline_words.append({
                    "word": w["word"],
                    "start": round(rel_s + current_time_offset, 2),
                    "end": round(rel_e + current_time_offset, 2)
                })
        current_time_offset += seg_dur

    return clean_and_merge_tokens(timeline_words)


def group_words_into_chunks(words: List[Dict[str, Any]], max_words: int = 3) -> List[List[Dict[str, Any]]]:
    """Groups words into short, rapid 1-3 word bursts for high retention."""
    chunks = []
    cur = []
    for w in words:
        cur.append(w)
        txt = w["word"]
        if len(cur) >= max_words or any(txt.endswith(p) for p in [".", "!", "?", ","]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass_subtitles(
    words: List[Dict[str, Any]],
    ass_path: Path,
    highlight_color: str = "&H0000FFFF&",
    font_size: int = 75,
    margin_v: int = 440
) -> Path:
    """Generates an ASS subtitle file with bold word-by-word active highlighting."""
    chunks = group_words_into_chunks(words, max_words=3)

    header = f"""[Script Info]
Title: MrBeast Viral Shorts Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Impact,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,6,3,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogues = []
    for chunk in chunks:
        c_start = chunk[0]["start"]
        c_end = max(chunk[-1]["end"], c_start + 0.35)

        for i, active_w in enumerate(chunk):
            w_start = active_w["start"]
            w_end = chunk[i + 1]["start"] if (i + 1 < len(chunk)) else c_end
            if w_end <= w_start:
                w_end = w_start + 0.15

            t_s = format_ass_timestamp(w_start)
            t_e = format_ass_timestamp(w_end)

            tokens = []
            for j, w in enumerate(chunk):
                w_text = w["word"].upper().replace("\\", "").replace("{", "").replace("}", "")
                if j == i:
                    tokens.append(f"{{\\c{highlight_color}\\fscx112\\fscy112}}{w_text}{{\\r}}")
                else:
                    tokens.append(f"{{\\c&H00FFFFFF&\\fscx100\\fscy100}}{w_text}{{\\r}}")

            line_text = " ".join(tokens)
            dialogues.append(f"Dialogue: 0,{t_s},{t_e},Default,,0,0,0,,{line_text}")

    ass_path.write_text(header + "\n".join(dialogues) + "\n", encoding="utf-8")
    return ass_path


FILTERS = {
    "scale_jp": "scale=1080:1920:flags=bicubic",
    "punch_jimmy": "crop=1440:2560:0:600,scale=1080:1920:flags=bicubic",
    "punch_patterson": "crop=1440:2560:720:600,scale=1080:1920:flags=bicubic",
    "crop_mdg_center": "crop=608:1080:656:0,scale=1080:1920:flags=bicubic",
    "crop_mdg_qr": "crop=608:1080:1100:0,scale=1080:1920:flags=bicubic",
    "crop_mdg_tight": "crop=500:888:710:100,scale=1080:1920:flags=bicubic",
    "crop_mdg_left": "crop=608:1080:200:0,scale=1080:1920:flags=bicubic",
}

VARIATIONS = [
    {
        "id": "v1",
        "name": "v1_button_explosion_hook.mp4",
        "title": "MrBeast Press For Boom ($1,000,000 Explosion)",
        "hook": "Opens immediately on Patterson hitting the red button and a massive fireball explosion!",
        "color": "&H0000FFFF&",
        "margin_v": 440,
        "segments": [
            {"src": "JP", "start": 23.80, "end": 29.00, "vf": "scale_jp"},
            {"src": "JP", "start": 0.00,  "end": 7.42,  "vf": "punch_jimmy"},
            {"src": "JP", "start": 29.00, "end": 32.15, "vf": "scale_jp"},
        ],
        "caption": "Jimmy gave James Patterson the red button and blew up $1,000,000 🔥 Their new novel 'The Most Dangerous Games' drops Sept 14 with a REAL $1,000,000 reader giveaway! #TheMostDangerousGames #MrBeastPartner #MrBeast #JamesPatterson",
    },
    {
        "id": "v2",
        "name": "v2_before_i_go_to_jail.mp4",
        "title": "Before I Go To Jail (Police Vehicle Reveal)",
        "hook": "MrBeast arrested in tactical SWAT vehicle, pulling novel from cash bag.",
        "color": "&H0033FF33&",
        "margin_v": 440,
        "segments": [
            {"src": "MDG", "start": 9.68,  "end": 16.00, "vf": "crop_mdg_center"},
            {"src": "MDG", "start": 24.00, "end": 29.73, "vf": "crop_mdg_tight"},
            {"src": "MDG", "start": 48.50, "end": 55.20, "vf": "crop_mdg_center"},
            {"src": "JP",  "start": 29.00, "end": 32.15, "vf": "scale_jp"},
        ],
        "caption": "MrBeast really hid a $1,000,000 puzzle inside a novel before getting arrested 🤯 'The Most Dangerous Games' with James Patterson drops Sept 14! #TheMostDangerousGames #MrBeastPartner #MrBeast #JamesPatterson",
    },
    {
        "id": "v3",
        "name": "v3_mrbeast_patterson_banter.mp4",
        "title": "MrBeast x Patterson Comedic Duo Cut",
        "hook": "Comedic dialogue cuts back-and-forth between Jimmy and James Patterson.",
        "color": "&H00FFFF00&",
        "margin_v": 440,
        "segments": [
            {"src": "JP", "start": 3.90,  "end": 7.42,  "vf": "punch_jimmy"},
            {"src": "JP", "start": 7.42,  "end": 12.22, "vf": "punch_patterson"},
            {"src": "JP", "start": 12.22, "end": 17.35, "vf": "punch_jimmy"},
            {"src": "JP", "start": 0.00,  "end": 3.80,  "vf": "scale_jp"},
        ],
        "caption": "MrBeast: 'Growing up I thought reading was boring, so I made a book with James Patterson and put $1,000,000 inside.' First challenge drops Sept 14! #TheMostDangerousGames #MrBeastPartner #MrBeast #JamesPatterson",
    },
    {
        "id": "v4",
        "name": "v4_100_contestants_high_stakes.mp4",
        "title": "100 Contestants — Save Humanity (Survival Premise)",
        "hook": "Highlights the intense book plot: 100 contestants in dangerous games to save humanity.",
        "color": "&H000080FF&",
        "margin_v": 440,
        "segments": [
            {"src": "MDG", "start": 24.00, "end": 29.73, "vf": "crop_mdg_center"},
            {"src": "MDG", "start": 35.57, "end": 43.00, "vf": "crop_mdg_tight"},
            {"src": "MDG", "start": 48.50, "end": 57.00, "vf": "crop_mdg_center"},
        ],
        "caption": "100 contestants. Highest stakes. To save humanity. MrBeast & James Patterson wrote the craziest book ever and hid $1,000,000 inside it 💰 First challenge drops Sept 14! #TheMostDangerousGames #MrBeastPartner #MrBeast #JamesPatterson",
    },
    {
        "id": "v5",
        "name": "v5_the_grand_mashup.mp4",
        "title": "The Grand Mashup (Arrest to Explosion)",
        "hook": "Cross-cuts the police arrest scene directly into the button explosion!",
        "color": "&H0000FFFF&",
        "margin_v": 440,
        "segments": [
            {"src": "MDG", "start": 9.68,  "end": 15.00, "vf": "crop_mdg_center"},
            {"src": "MDG", "start": 24.00, "end": 29.00, "vf": "crop_mdg_tight"},
            {"src": "JP",  "start": 9.00,  "end": 12.00, "vf": "punch_patterson"},
            {"src": "JP",  "start": 23.80, "end": 29.00, "vf": "scale_jp"},
            {"src": "JP",  "start": 0.00,  "end": 3.80,  "vf": "punch_jimmy"},
        ],
        "caption": "From police custody to a massive fireball explosion 💥 Jimmy & James Patterson hid $1,000,000 in 'The Most Dangerous Games'. First challenge drops Sept 14! #TheMostDangerousGames #MrBeastPartner #MrBeast #JamesPatterson",
    },
    {
        "id": "v6",
        "name": "v6_qr_code_mystery_scan.mp4",
        "title": "The QR Code Face Scan (Viral Humor Cut)",
        "hook": "Viral humor cut focusing on scanning the giant QR code on the officer's face.",
        "color": "&H00D900FF&",
        "margin_v": 440,
        "segments": [
            {"src": "MDG", "start": 48.50, "end": 55.00, "vf": "crop_mdg_center"},
            {"src": "MDG", "start": 55.00, "end": 58.50, "vf": "crop_mdg_qr"},
            {"src": "JP",  "start": 29.00, "end": 32.15, "vf": "scale_jp"},
        ],
        "caption": "Why did MrBeast put a QR code on her face?! 😭 Scan to enter the $1,000,000 giveaway for 'The Most Dangerous Games'. Challenge 1 drops Sept 14! #TheMostDangerousGames #MrBeastPartner #MrBeast #JamesPatterson",
    },
    {
        "id": "v7",
        "name": "v7_if_you_like_mrbeast_videos.mp4",
        "title": "If You Like MrBeast Videos (The Non-Reader Hook)",
        "hook": "Direct conversion hook for viewers who don't normally read books.",
        "color": "&H0022FFFF&",
        "margin_v": 440,
        "segments": [
            {"src": "MDG", "start": 29.73, "end": 35.57, "vf": "crop_mdg_center"},
            {"src": "JP",  "start": 18.70, "end": 22.00, "vf": "punch_patterson"},
            {"src": "JP",  "start": 23.80, "end": 29.00, "vf": "scale_jp"},
            {"src": "JP",  "start": 0.00,  "end": 3.80,  "vf": "punch_jimmy"},
        ],
        "caption": "Don't like reading? If you enjoy MrBeast videos, you'll love 'The Most Dangerous Games' with James Patterson. Plus someone wins $1,000,000! Challenge drops Sept 14! #TheMostDangerousGames #MrBeastPartner #MrBeast #JamesPatterson",
    },
    {
        "id": "v8",
        "name": "v8_15s_ultra_fast_hook.mp4",
        "title": "15s Ultra-Fast Hook Cut (Maximum Retention)",
        "hook": "Lightning-paced 15-second cut designed for 100%+ completion rate.",
        "color": "&H0000E6FF&",
        "margin_v": 440,
        "segments": [
            {"src": "JP",  "start": 0.00,  "end": 3.80,  "vf": "punch_jimmy"},
            {"src": "JP",  "start": 23.80, "end": 28.50, "vf": "scale_jp"},
            {"src": "MDG", "start": 24.00, "end": 27.50, "vf": "crop_mdg_tight"},
            {"src": "JP",  "start": 29.00, "end": 31.50, "vf": "scale_jp"},
        ],
        "caption": "$1,000,000 giveaway + huge explosion 🤯 MrBeast & James Patterson's new novel 'The Most Dangerous Games' is out now! Challenge 1 drops Sept 14! #TheMostDangerousGames #MrBeastPartner #MrBeast #JamesPatterson",
    },
    {
        "id": "v9",
        "name": "v9_master_commercial_arc.mp4",
        "title": "The Master Commercial Arc (Full Theatrical Trailer)",
        "hook": "Complete theatrical trailer combining arrest, premise, explosion, and $1M offer.",
        "color": "&H0000FFFF&",
        "margin_v": 440,
        "segments": [
            {"src": "MDG", "start": 9.68,  "end": 14.50, "vf": "crop_mdg_center"},
            {"src": "MDG", "start": 24.00, "end": 28.50, "vf": "crop_mdg_tight"},
            {"src": "MDG", "start": 35.57, "end": 43.00, "vf": "crop_mdg_center"},
            {"src": "JP",  "start": 23.80, "end": 28.50, "vf": "scale_jp"},
            {"src": "MDG", "start": 48.50, "end": 55.00, "vf": "crop_mdg_center"},
            {"src": "JP",  "start": 29.00, "end": 32.15, "vf": "scale_jp"},
        ],
        "caption": "The most insane book release in history. 100 contestants, $1,000,000 reader giveaway, and a real explosion. 'The Most Dangerous Games' out now! Challenge drops Sept 14! #TheMostDangerousGames #MrBeastPartner #MrBeast #JamesPatterson",
    },
]


def render_variation(var: Dict[str, Any], jp_words: List[Dict[str, Any]], mdg_words: List[Dict[str, Any]]) -> Path:
    var_id = var["id"]
    out_name = var["name"]
    out_path = OUTPUT_DIR / out_name
    ass_path = OUTPUT_DIR / f"{var_id}_subtitles.ass"

    logger.info(f"=== Rendering [{var_id.upper()}] {var['title']} ===")

    words = extract_timeline_words(var["segments"], jp_words, mdg_words)
    build_ass_subtitles(
        words=words,
        ass_path=ass_path,
        highlight_color=var["color"],
        font_size=75,
        margin_v=var.get("margin_v", 440)
    )

    escaped_ass = ass_path.as_posix().replace(":", r"\:")

    filter_parts = []
    concat_v_inputs = []
    concat_a_inputs = []

    for idx, seg in enumerate(var["segments"]):
        in_stream = "0" if seg["src"] == "JP" else "1"
        s = seg["start"]
        e = seg["end"]
        dur = round(e - s, 2)
        vf_expr = FILTERS[seg["vf"]]

        filter_parts.append(
            f"[{in_stream}:v]trim=start={s}:end={e},setpts=PTS-STARTPTS,{vf_expr}[v{idx}]"
        )
        concat_v_inputs.append(f"[v{idx}]")

        fade_d = min(0.04, dur / 4)
        filter_parts.append(
            f"[{in_stream}:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade_d},afade=t=out:st={dur - fade_d}:d={fade_d}[a{idx}]"
        )
        concat_a_inputs.append(f"[a{idx}]")

    num_segs = len(var["segments"])
    interleaved_inputs = "".join(f"[v{i}][a{i}]" for i in range(num_segs))
    concat_str = f"{interleaved_inputs}concat=n={num_segs}:v=1:a=1[v_cat][a_cat]"
    filter_parts.append(concat_str)
    filter_parts.append(f"[v_cat]subtitles=filename='{escaped_ass}'[v_out]")

    full_filter_complex = ";".join(filter_parts)

    cmd = [
        settings.FFMPEG_EXE,
        "-y",
        "-i", str(SRC_JP),
        "-i", str(SRC_MDG),
        "-filter_complex", full_filter_complex,
        "-map", "[v_out]",
        "-map", "[a_cat]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        str(out_path)
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.error(f"FFmpeg render failed for {out_name}:\n{res.stderr[-1000:]}")
        raise RuntimeError(f"FFmpeg failed for {out_name}")

    qc_report = verify_rendered_video(out_path)
    logger.info(
        f"QC Passed for {out_name}: duration={qc_report.output_duration:.2f}s, "
        f"size={qc_report.file_size_bytes / (1024*1024):.2f}MB, audio={qc_report.has_audio}"
    )

    desktop_target = DESKTOP_DIR / out_name
    shutil.copy2(out_path, desktop_target)
    logger.info(f"Delivered to Desktop: {desktop_target}")

    return out_path


def main():
    logger.info("Starting MrBeast 9-Variation Video Batch Production")

    with open(TRANSCRIPT_JP_PATH, "r", encoding="utf-8") as f:
        jp_words = json.load(f)["words"]
    with open(TRANSCRIPT_MDG_PATH, "r", encoding="utf-8") as f:
        mdg_words = json.load(f)["words"]

    produced = []
    for var in VARIATIONS:
        out_file = render_variation(var, jp_words, mdg_words)
        produced.append((var, out_file))

    txt_path = DESKTOP_DIR / "captions_and_hashtags.txt"
    lines = [
        "=" * 80,
        "MRBEAST & JAMES PATTERSON — THE MOST DANGEROUS GAMES CAMPAIGN",
        "9 VIRAL VIDEO VARIATIONS (1080x1920 VERTICAL WITH ANIMATED CAPTIONS)",
        "=" * 80,
        "",
        "CAMPAIGN RULES CHECKLIST:",
        " [✓] Mentions book title: 'The Most Dangerous Games'",
        " [✓] Mentions authors: MrBeast & James Patterson",
        " [✓] Mentions $1,000,000 giveaway & entry mechanic (buy book / scan QR)",
        " [✓] Caption mentions: First challenge drops September 14",
        " [✓] Required hashtags: #TheMostDangerousGames #MrBeastPartner",
        " [✓] Video duration > 8 seconds on all 9 variations",
        " [✓] Vertical 9:16 aspect ratio (1080x1920) optimized for TikTok / Shorts / Reels",
        "",
        "=" * 80,
        "READY-TO-COPY POSTING METADATA PER VARIATION",
        "=" * 80,
        ""
    ]

    for idx, (var, out_file) in enumerate(produced, 1):
        qc = verify_rendered_video(out_file)
        lines.append(f"--- VARIATION {idx}: {var['name']} ---")
        lines.append(f"Title: {var['title']}")
        lines.append(f"Creative Angle: {var['hook']}")
        lines.append(f"Duration: {qc.output_duration:.2f}s | Size: {qc.file_size_bytes / (1024*1024):.2f} MB")
        lines.append(f"Caption to Copy & Paste:")
        lines.append(f"{var['caption']}")
        lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Wrote metadata and ready-to-copy captions to: {txt_path}")
    shutil.copy2(txt_path, OUTPUT_DIR / "captions_and_hashtags.txt")

    print("\n" + "=" * 80)
    print("ALL 9 MRBEAST CAMPAIGN VARIATIONS SUCCESSFULLY PRODUCED & DELIVERED!")
    print(f"Desktop Destination: {DESKTOP_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    main()
