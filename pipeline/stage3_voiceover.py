import os
import sys
import json
import base64
import requests
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config

def build_full_script(storyboard: Dict[str, Any]) -> str:
    """Combines all scene narrations into a coherent master narration script with natural pacing."""
    paragraphs = []
    for sc in storyboard.get("scenes", []):
        text = sc.get("narration", "").strip()
        if text:
            paragraphs.append(text)
    return " ".join(paragraphs)

def load_elevenlabs_pool() -> List[Dict[str, Any]]:
    """Loads active keys from elevenlabs_pool.json."""
    pool_file = Path(__file__).resolve().parent.parent / "elevenlabs_pool.json"
    if pool_file.exists():
        try:
            with open(pool_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [k for k in data.get("keys", []) if k.get("status") == "active" and k.get("key")]
        except Exception as e:
            print(f"[Stage 3] Warning: Could not read elevenlabs_pool.json: {e}")
    return []

def generate_voiceover_elevenlabs(
    script_text: str,
    output_audio_path: Path,
    output_words_path: Path,
    api_key: Optional[str] = None,
    voice_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calls ElevenLabs text-to-speech with timestamps API.
    Rotates through elevenlabs_pool.json automatically if a key hits quota limits.
    """
    candidate_keys = []
    if api_key:
        candidate_keys.append({"label": "direct_arg", "key": api_key})
    
    pool = load_elevenlabs_pool()
    candidate_keys.extend(pool)
    
    fallback_config_key = config.ELEVENLABS_API_KEY or os.environ.get("ELEVENLABS_API_KEY", "")
    if fallback_config_key and not any(k["key"] == fallback_config_key for k in candidate_keys):
        candidate_keys.append({"label": "config_default", "key": fallback_config_key})
        
    if not candidate_keys:
        raise ValueError("No ElevenLabs API keys found in elevenlabs_pool.json, config.py, or arguments.")

    vid = voice_id or config.DEFAULT_VOICE_ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/with-timestamps"

    payload = {
        "text": script_text,
        "model_id": config.DEFAULT_MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
            "style": 0.2,
            "use_speaker_boost": True
        }
    }

    last_error = None
    response = None

    for candidate in candidate_keys:
        k_label = candidate.get("label", "unknown")
        k_val = candidate.get("key", "")
        masked_key = f"{k_val[:8]}...{k_val[-4:]}" if len(k_val) > 12 else "***"
        
        print(f"[Stage 3] Trying ElevenLabs TTS with [{k_label}] ({masked_key}) for ~{len(script_text)} chars...")
        headers = {
            "xi-api-key": k_val,
            "Content-Type": "application/json"
        }
        
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code == 200:
                print(f"[Stage 3] TTS success with [{k_label}]!")
                response = resp
                break
            else:
                err_msg = f"Status {resp.status_code}: {resp.text}"
                print(f"[Stage 3] Key [{k_label}] failed ({err_msg}). Trying next key in pool...")
                last_error = err_msg
        except Exception as ex:
            print(f"[Stage 3] Network exception with [{k_label}]: {ex}. Trying next...")
            last_error = str(ex)

    if not response or response.status_code != 200:
        raise RuntimeError(f"All candidate ElevenLabs keys exhausted or failed. Last error: {last_error}")

    data = response.json()
    audio_base64 = data.get("audio_base64")
    alignment = data.get("alignment", {})

    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_audio_path, "wb") as f:
        f.write(base64.b64decode(audio_base64))

    # Convert character-level alignment to word-level alignment
    words = []
    characters = alignment.get("characters", [])
    char_starts = alignment.get("character_start_times_seconds", [])
    char_ends = alignment.get("character_end_times_seconds", [])

    current_word = ""
    start_time = None
    end_time = None

    for char, c_start, c_end in zip(characters, char_starts, char_ends):
        if char in [" ", "\n", "\t"]:
            if current_word:
                words.append({
                    "word": current_word,
                    "start": round(start_time, 3),
                    "end": round(end_time, 3)
                })
                current_word = ""
                start_time = None
                end_time = None
        else:
            if start_time is None:
                start_time = c_start
            end_time = c_end
            current_word += char

    if current_word and start_time is not None:
        words.append({
            "word": current_word,
            "start": round(start_time, 3),
            "end": round(end_time, 3)
        })

    with open(output_words_path, "w", encoding="utf-8") as f:
        json.dump({"words": words, "text": script_text}, f, indent=2)

    print(f"[Stage 3] Narration audio saved to {output_audio_path}")
    print(f"[Stage 3] Word timestamps saved to {output_words_path}")
    return {"audio_path": str(output_audio_path), "words_path": str(output_words_path), "word_count": len(words)}

async def _edge_tts_fallback(script_text: str, output_audio_path: Path, output_words_path: Path):
    """Free local fallback using edge-tts for dry-run testing without spending any credits."""
    import edge_tts
    communicate = edge_tts.Communicate(script_text, "en-US-ChristopherNeural")
    words = []
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] in ["SentenceBoundary", "WordBoundary"]:
                text = chunk.get("text", "")
                offset_sec = chunk["offset"] / 10_000_000.0
                dur_sec = chunk["duration"] / 10_000_000.0
                chunk_words = text.split()
                if chunk_words:
                    word_dur = dur_sec / len(chunk_words)
                    for i, w in enumerate(chunk_words):
                        w_start = offset_sec + (i * word_dur)
                        w_end = w_start + word_dur
                        words.append({
                            "word": w,
                            "start": round(w_start, 3),
                            "end": round(w_end, 3)
                        })

    with open(output_words_path, "w", encoding="utf-8") as f:
        json.dump({"words": words, "text": script_text}, f, indent=2)
    print(f"[Stage 3 - DRY RUN (Free)] Generated free test voiceover with {len(words)} words at {output_audio_path}")

def generate_voiceover(
    storyboard_path: Path,
    output_audio_path: Path,
    output_words_path: Path,
    use_dry_run: bool = False
) -> Dict[str, Any]:
    with open(storyboard_path, "r", encoding="utf-8") as f:
        sb = json.load(f)

    script_text = build_full_script(sb)
    has_api_key = bool(config.ELEVENLABS_API_KEY or os.environ.get("ELEVENLABS_API_KEY"))

    if use_dry_run or not has_api_key:
        print("[Stage 3] Using free dry-run engine (zero credits used) to test timing...")
        asyncio.run(_edge_tts_fallback(script_text, output_audio_path, output_words_path))
        return {"audio_path": str(output_audio_path), "words_path": str(output_words_path), "dry_run": True}
    else:
        return generate_voiceover_elevenlabs(script_text, output_audio_path, output_words_path)

if __name__ == "__main__":
    sb_file = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating" / "storyboard.json"
    out_audio = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating" / "narration.mp3"
    out_words = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating" / "narration_words.json"
    generate_voiceover(sb_file, out_audio, out_words, use_dry_run=True)
