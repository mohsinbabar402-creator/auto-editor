import sys
import json
from pathlib import Path
from typing import Dict, Any, List

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config

def format_ass_timestamp(seconds: float) -> str:
    """Converts floating seconds (e.g. 12.345) to ASS timestamp format H:MM:SS.CC (centiseconds)."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        secs += 1
        centis = 0
    return f"{hrs:d}:{mins:02d}:{secs:02d}.{centis:02d}"

def group_words_into_chunks(words: List[Dict[str, Any]], max_words_per_chunk: int = 3) -> List[List[Dict[str, Any]]]:
    """Groups words into short readable bursts (1-3 words). Breaks chunks on punctuation."""
    chunks = []
    current_chunk = []
    
    for w in words:
        current_chunk.append(w)
        word_text = w.get("word", "")
        # Break chunk if it hits max limit or ends with strong punctuation
        if len(current_chunk) >= max_words_per_chunk or any(word_text.endswith(p) for p in [".", "!", "?", ","]):
            chunks.append(current_chunk)
            current_chunk = []
            
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

def generate_ass_subtitles(words_data_path: Path, output_ass_path: Path, highlight_color: str = "&H0022FFFF&") -> Path:
    """
    Generates an ASS subtitle file where each word within a 2-3 word chunk is highlighted
    as it is spoken.
    """
    with open(words_data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    words = data.get("words", [])
    if not words:
        print("[Stage 4] Warning: No words found in word timestamp file.")
        return output_ass_path

    chunks = group_words_into_chunks(words, max_words_per_chunk=3)

    ass_header = f"""[Script Info]
Title: AI Auto Shorts Captions
ScriptType: v4.00+
PlayResX: {config.VIDEO_WIDTH}
PlayResY: {config.VIDEO_HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Impact,{config.CAPTION_FONT_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,{config.CAPTION_OUTLINE_WIDTH},3,2,60,60,{config.CAPTION_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines = []

    for chunk in chunks:
        chunk_start = chunk[0]["start"]
        chunk_end = chunk[-1]["end"]
        # Extend slightly for smooth transition
        chunk_end = max(chunk_end, chunk_start + 0.3)

        # For each word in this chunk, create a sub-event highlighting that active word
        for i, target_word in enumerate(chunk):
            w_start = target_word["start"]
            # Active duration lasts until next word starts or chunk ends
            if i + 1 < len(chunk):
                w_end = chunk[i + 1]["start"]
            else:
                w_end = chunk_end

            w_start_str = format_ass_timestamp(w_start)
            w_end_str = format_ass_timestamp(w_end)

            # Build text where current word has highlight color & uppercase impact styling
            text_parts = []
            for j, w in enumerate(chunk):
                word_clean = w["word"].upper()
                if j == i:
                    # Highlight active word with yellow/cyan + slight pop
                    text_parts.append(f"{{\\c{highlight_color}\\fscx110\\fscy110}}{word_clean}{{\\r}}")
                else:
                    text_parts.append(f"{{\\c&H00FFFFFF&\\fscx100\\fscy100}}{word_clean}{{\\r}}")

            formatted_text = " ".join(text_parts)
            dialogue_lines.append(
                f"Dialogue: 0,{w_start_str},{w_end_str},Default,,0,0,0,,{formatted_text}"
            )

    output_ass_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogue_lines) + "\n")

    print(f"[Stage 4] Generated animated ASS captions at {output_ass_path}")
    return output_ass_path

if __name__ == "__main__":
    w_path = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating" / "narration_words.json"
    ass_path = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating" / "captions.ass"
    if w_path.exists():
        generate_ass_subtitles(w_path, ass_path)
