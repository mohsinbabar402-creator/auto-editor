import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger("whop_editor.analysis.whisper")


class WhisperAnalysisError(Exception):
    """Raised when audio extraction or Whisper transcription fails."""
    pass


def extract_audio_for_whisper(video_path: Path, output_wav: Path) -> Path:
    """Extracts 16kHz mono 16-bit PCM WAV for optimal Whisper ingestion."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_EXE,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_wav)
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise WhisperAnalysisError(f"FFmpeg audio extraction failed: {proc.stderr}")
    except Exception as e:
        raise WhisperAnalysisError(f"Could not extract audio from {video_path}: {e}") from e

    if not output_wav.exists() or output_wav.stat().st_size == 0:
        raise WhisperAnalysisError(f"Extracted audio file is missing or empty: {output_wav}")

    return output_wav


def _transcribe_with_whisper_cli(wav_path: Path, video_id: str) -> Optional[Dict[str, Any]]:
    """Runs local standalone whisper-cli.exe if present."""
    tools_dir = Path(__file__).resolve().parent.parent / "tools" / "whisper"
    cli_exe = tools_dir / "Release" / "whisper-cli.exe"
    model_bin = tools_dir / "ggml-tiny.en.bin"

    if not (cli_exe.exists() and model_bin.exists()):
        return None

    json_base = settings.ANALYSIS_DIR / f"{video_id}_wcli"
    cmd = [
        str(cli_exe),
        "-m", str(model_bin),
        "-f", str(wav_path),
        "-ojf",
        "-ml", "1",
        "-of", str(json_base)
    ]
    try:
        logger.info(f"Running standalone whisper-cli with {model_bin.name}...")
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out_json = Path(f"{json_base}.json")
        if not out_json.exists():
            return None

        data = json.loads(out_json.read_text(encoding="utf-8"))
        words = []
        full_text_list = []
        w_idx = 0

        for seg in data.get("transcription", []):
            txt = seg.get("text", "").strip()
            if txt:
                full_text_list.append(txt)
            tokens = seg.get("tokens", [])
            if tokens:
                for tok in tokens:
                    w = tok.get("text", "").strip()
                    if w and not w.startswith("[_"):
                        t_start = tok.get("timestamps", {}).get("from", "00:00:00,000")
                        t_end = tok.get("timestamps", {}).get("to", "00:00:00,000")
                        # Parse HH:MM:SS,mmm to seconds
                        def parse_ts(ts_str):
                            try:
                                h, m, rest = ts_str.split(":")
                                s, ms = rest.split(",")
                                return float(h)*3600 + float(m)*60 + float(s) + float(ms)/1000.0
                            except: return 0.0
                        
                        s_sec = parse_ts(t_start)
                        e_sec = parse_ts(t_end)
                        if e_sec <= s_sec:
                            e_sec = s_sec + 0.15
                        words.append({
                            "index": w_idx,
                            "word": w,
                            "start": round(s_sec, 3),
                            "end": round(e_sec, 3),
                            "probability": round(tok.get("p", 1.0), 3)
                        })
                        w_idx += 1
            else:
                # If segment-level words
                clean = txt.strip()
                if clean:
                    # Segment level timestamp
                    def parse_str_ts(ts_str):
                        try:
                            h, m, rest = ts_str.split(":")
                            s, ms = rest.split(",")
                            return float(h)*3600 + float(m)*60 + float(s) + float(ms)/1000.0
                        except: return 0.0
                    s_sec = parse_str_ts(seg.get("timestamps", {}).get("from", "00:00:00,000"))
                    e_sec = parse_str_ts(seg.get("timestamps", {}).get("to", "00:00:00,000"))
                    for word_part in clean.split():
                        words.append({
                            "index": w_idx,
                            "word": word_part,
                            "start": round(s_sec, 3),
                            "end": round(e_sec, 3),
                            "probability": 0.95
                        })
                        w_idx += 1

        # Clean up temporary cli json
        try:
            out_json.unlink()
        except: pass

        return {
            "text": " ".join(full_text_list),
            "words": words,
            "language": data.get("result", {}).get("language", "en")
        }
    except Exception as e:
        logger.warning(f"whisper-cli execution error: {e}")
        return None


def transcribe_video_words(
    video_path: str | Path,
    video_id: str,
    model_size: str = "tiny"
) -> Dict[str, Any]:
    """
    Transcribes video and returns word-level timestamps.
    Saves analysis JSON artifact in settings.ANALYSIS_DIR.
    """
    v_path = Path(video_path).resolve()
    if not v_path.exists():
        raise WhisperAnalysisError(f"Video file not found: {v_path}")

    wav_path = settings.ANALYSIS_DIR / f"{video_id}_temp_audio.wav"
    artifact_json_path = settings.ANALYSIS_DIR / f"{video_id}_transcript.json"

    # Extract audio
    extract_audio_for_whisper(v_path, wav_path)

    words: List[Dict[str, Any]] = []
    full_text = ""
    detected_lang = "en"
    transcribed = False

    # 1. First priority: Fast, standalone native whisper-cli
    cli_result = _transcribe_with_whisper_cli(wav_path, video_id)
    if cli_result and cli_result["words"]:
        words = cli_result["words"]
        full_text = cli_result["text"]
        detected_lang = cli_result["language"]
        transcribed = True

    # 2. Try faster-whisper if cli was not used
    if not transcribed:
        try:
            from faster_whisper import WhisperModel
            logger.info(f"Loading faster-whisper model '{model_size}' on CPU...")
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            segments, info = model.transcribe(str(wav_path), word_timestamps=True)
            detected_lang = info.language

            w_idx = 0
            full_parts = []
            for seg in segments:
                full_parts.append(seg.text)
                if seg.words:
                    for w in seg.words:
                        clean_w = w.word.strip()
                        if clean_w:
                            words.append({
                                "index": w_idx,
                                "word": clean_w,
                                "start": round(w.start, 3),
                                "end": round(w.end, 3),
                                "probability": round(getattr(w, "probability", 1.0), 3)
                            })
                            w_idx += 1
            full_text = " ".join(full_parts)
            transcribed = True
        except Exception as e:
            logger.warning(f"faster-whisper fallback failed: {e}")

    # Clean up temporary WAV
    if wav_path.exists():
        try:
            wav_path.unlink()
        except Exception:
            pass

    if not transcribed or not words:
        raise WhisperAnalysisError(
            "Whisper transcription produced zero words or failed to execute."
        )

    artifact_data = {
        "video_id": video_id,
        "video_path": str(v_path),
        "language": detected_lang,
        "text": full_text,
        "words": words,
        "word_count": len(words)
    }

    # Save artifact locally
    artifact_json_path.write_text(json.dumps(artifact_data, indent=2), encoding="utf-8")
    logger.info(f"Whisper transcript saved: {artifact_json_path.name} ({len(words)} words)")
    return artifact_data
