from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("whop_editor.analysis.transcript")


class TranscriptError(Exception):
    """Base transcript processing error."""
    pass


class EmptyTranscriptError(TranscriptError):
    """Raised when transcript contains no words."""
    pass


class InvalidWordIndexError(TranscriptError):
    """Raised when a requested word index is out of bounds."""
    pass


@dataclass(frozen=True)
class WordToken:
    index: int
    word: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


class NormalizedTranscript:
    """
    Guarantees sanitized, strictly ordered, monotonically non-decreasing word tokens.
    Handles malformed timestamps, re-indexing, and effect window resolution.
    """

    def __init__(self, raw_words: List[Dict[str, Any]], full_text: str = ""):
        self.full_text = full_text.strip()
        self.words: List[WordToken] = self._normalize_words(raw_words)

    def _normalize_words(self, raw_words: List[Dict[str, Any]]) -> List[WordToken]:
        if not raw_words:
            raise EmptyTranscriptError("Transcript contains zero words.")

        valid_tokens: List[Dict[str, Any]] = []

        for item in raw_words:
            word_str = str(item.get("word", "")).strip()
            if not word_str:
                continue

            try:
                start = float(item.get("start", 0.0))
                end = float(item.get("end", 0.0))
            except (ValueError, TypeError):
                continue

            # Fix inverted or invalid timestamps
            if start < 0.0:
                start = 0.0
            if end < start:
                # Minimum fallback duration for zero/inverted interval
                end = round(start + 0.15, 3)

            valid_tokens.append({
                "word": word_str,
                "start": round(start, 3),
                "end": round(end, 3)
            })

        if not valid_tokens:
            raise EmptyTranscriptError("No valid words remained after sanitization.")

        # Sort tokens monotonically by start time, then end time
        valid_tokens.sort(key=lambda t: (t["start"], t["end"]))

        # Build clean sequential tokens with canonical indexes
        normalized: List[WordToken] = []
        for idx, t in enumerate(valid_tokens):
            normalized.append(WordToken(
                index=idx,
                word=t["word"],
                start=t["start"],
                end=t["end"]
            ))

        return normalized

    def __len__(self) -> int:
        return len(self.words)

    def get_word(self, index: int) -> WordToken:
        """Returns word token by canonical 0-based index."""
        if not (0 <= index < len(self.words)):
            raise InvalidWordIndexError(
                f"Word index {index} out of range [0, {len(self.words) - 1}]."
            )
        return self.words[index]

    def to_prompt_context(self) -> str:
        """Formats words into an unambiguous, index-anchored string for AI evaluation."""
        lines = []
        for w in self.words:
            lines.append(f"[{w.index}] '{w.word}' ({w.start:.2f}s - {w.end:.2f}s)")
        return "\n".join(lines)

    def resolve_effect_window(
        self,
        word_index: int,
        duration_ms: int,
        pre_offset_ms: int = 40,
        video_duration: Optional[float] = None,
        phrase_expansion: bool = False
    ) -> tuple[float, float]:
        """
        Calculates exact start and end seconds for punch-in based on word boundary.
        Applies configurable pre-offset (lead-in) and clamps to video duration.
        If phrase_expansion is True, expands effect window to encompass the surrounding
        rhetorical phrase (up to 1 word prior and 1 word following).
        """
        token = self.get_word(word_index)
        
        t_start = token.start
        t_end = token.end

        if phrase_expansion:
            # Expand to include preceding word if close (<0.5s pause)
            if word_index > 0:
                prev_token = self.get_word(word_index - 1)
                if (t_start - prev_token.end) < 0.5:
                    t_start = prev_token.start
            # Expand to include following word if close (<0.5s pause)
            if word_index + 1 < len(self.words):
                next_token = self.get_word(word_index + 1)
                if (next_token.start - t_end) < 0.5:
                    t_end = next_token.end

        # Start time with lead-in pre-offset
        start_sec = max(0.0, round(t_start - (pre_offset_ms / 1000.0), 3))
        
        # Duration converted to seconds
        effect_duration_sec = round(duration_ms / 1000.0, 3)
        end_sec = round(start_sec + effect_duration_sec, 3)

        # Ensure effect covers at least the token/phrase end
        if end_sec < t_end:
            end_sec = round(t_end + 0.05, 3)

        # Clamp to video duration if provided
        if video_duration is not None and end_sec > video_duration:
            end_sec = round(video_duration, 3)

        return (start_sec, end_sec)

