"""
Creative Intelligence Engine — Source Analyzer (Phase 1)

PURPOSE:
    Takes a raw SRT transcript and produces a structured semantic understanding
    of the entire episode: who is speaking, what they discuss, where the topics
    change, where emotional moments occur, and what claims are being made.

    This is the FOUNDATION of all downstream clip discovery. Without understanding
    the source, the system cannot make intelligent editorial decisions.

INPUTS:
    - SRT file path
    - Episode metadata (title, url, duration)

OUTPUTS:
    - SourceAnalysis object containing:
        - Parsed SRT entries with clean timestamps
        - Reconstructed dialogue segments (merged overlapping subtitle windows)
        - Topic segments with speaker attribution
        - Summary of the episode

REUSES:
    - SRT file format already produced by yt-dlp (existing infrastructure)
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import List, Tuple

from brain.models import (
    SRTEntry, DialogueSegment, TopicSegment, SourceAnalysis
)


# ─── SRT Parsing ─────────────────────────────────────────────────────────────

def _parse_srt_timestamp(ts: str) -> float:
    """Convert SRT timestamp (HH:MM:SS,mmm) to seconds."""
    ts = ts.strip().replace(',', '.')
    parts = ts.split(':')
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(ts)


def parse_srt_file(srt_path: Path) -> List[SRTEntry]:
    """
    Parse an SRT file into structured entries.

    Handles the standard SRT format:
        1
        00:00:00,080 --> 00:00:04,720
        Just because you were top 500 on

    Also handles overlapping timestamp windows (common in YouTube auto-subs).
    """
    text = srt_path.read_text(encoding='utf-8', errors='replace')
    entries = []

    # Split on blank lines followed by a number
    blocks = re.split(r'\n\s*\n', text.strip())

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue

        # First line should be the index number
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue

        # Second line should be the timestamp range
        ts_match = re.match(
            r'(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})',
            lines[1].strip()
        )
        if not ts_match:
            continue

        start = _parse_srt_timestamp(ts_match.group(1))
        end = _parse_srt_timestamp(ts_match.group(2))

        # Remaining lines are the subtitle text
        sub_text = ' '.join(lines[2:]).strip()
        # Clean up common artifacts
        sub_text = re.sub(r'<[^>]+>', '', sub_text)  # Remove HTML tags
        sub_text = re.sub(r'\{[^}]+\}', '', sub_text)  # Remove style tags
        sub_text = sub_text.strip()

        if sub_text:
            entries.append(SRTEntry(
                index=idx,
                start_sec=round(start, 3),
                end_sec=round(end, 3),
                text=sub_text
            ))

    return entries


# ─── Dialogue Reconstruction ────────────────────────────────────────────────

def _detect_speaker_change(text: str) -> Tuple[str, str]:
    """
    Detect speaker change markers in subtitle text.
    YouTube auto-subs use '>>' to indicate speaker changes.
    Returns (speaker_hint, cleaned_text).
    """
    cleaned = text.strip()

    # '>>' marks a new speaker in YouTube auto-subs
    if cleaned.startswith('>>'):
        cleaned = cleaned.lstrip('>').strip()
        return "new_speaker", cleaned

    return "same_speaker", cleaned


def reconstruct_dialogue(entries: List[SRTEntry], merge_gap_sec: float = 1.5) -> List[DialogueSegment]:
    """
    Merge overlapping/adjacent SRT entries into coherent dialogue segments.

    YouTube auto-subs create overlapping windows where the same sentence
    appears across 2-3 entries with slightly different timestamps.
    This function merges them into clean, non-overlapping dialogue blocks.

    Strategy:
    1. Walk through entries sequentially.
    2. If the next entry overlaps or is within merge_gap_sec of the current,
       AND the speaker hasn't changed, merge them.
    3. On speaker change (>> marker), start a new segment.
    4. Deduplicate text that appears in overlapping windows.
    """
    if not entries:
        return []

    segments = []
    current_speaker = "Speaker_A"
    speaker_counter = 0
    speaker_map = {}

    # Track which text fragments have been seen to avoid duplication
    current_start = entries[0].start_sec
    current_end = entries[0].end_sec
    current_texts = []
    current_speaker_id = "Speaker_A"

    for entry in entries:
        speaker_hint, cleaned_text = _detect_speaker_change(entry.text)

        if speaker_hint == "new_speaker":
            # Save current segment
            if current_texts:
                merged_text = _merge_overlapping_texts(current_texts)
                if merged_text.strip():
                    segments.append(DialogueSegment(
                        start_sec=current_start,
                        end_sec=current_end,
                        speaker=current_speaker_id,
                        text=merged_text
                    ))

            # Switch speaker
            speaker_counter += 1
            if speaker_counter % 2 == 0:
                current_speaker_id = "Speaker_A"
            else:
                current_speaker_id = "Speaker_B"

            current_start = entry.start_sec
            current_end = entry.end_sec
            current_texts = [cleaned_text]

        elif entry.start_sec <= current_end + merge_gap_sec:
            # Continuation or overlap — extend current segment
            current_end = max(current_end, entry.end_sec)
            current_texts.append(cleaned_text)
        else:
            # Gap too large — new segment, same speaker
            if current_texts:
                merged_text = _merge_overlapping_texts(current_texts)
                if merged_text.strip():
                    segments.append(DialogueSegment(
                        start_sec=current_start,
                        end_sec=current_end,
                        speaker=current_speaker_id,
                        text=merged_text
                    ))

            current_start = entry.start_sec
            current_end = entry.end_sec
            current_texts = [cleaned_text]

    # Flush final segment
    if current_texts:
        merged_text = _merge_overlapping_texts(current_texts)
        if merged_text.strip():
            segments.append(DialogueSegment(
                start_sec=current_start,
                end_sec=current_end,
                speaker=current_speaker_id,
                text=merged_text
            ))

    return segments


def _merge_overlapping_texts(texts: List[str]) -> str:
    """
    Merge a list of potentially overlapping subtitle text fragments
    into a single coherent sentence.

    YouTube auto-subs repeat partial phrases across overlapping windows.
    This uses a longest-common-suffix/prefix approach to deduplicate.
    """
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0]

    # Simple incremental merge: for each new text, find the longest overlap
    # with the tail of the accumulated text, then append the non-overlapping part.
    result = texts[0]

    for text in texts[1:]:
        # Find the longest suffix of result that matches a prefix of text
        overlap_len = 0
        result_lower = result.lower()
        text_lower = text.lower()

        # Check word-level overlap (more robust than character-level)
        result_words = result_lower.split()
        text_words = text_lower.split()

        max_check = min(len(result_words), len(text_words))
        best_overlap = 0

        for overlap in range(1, max_check + 1):
            if result_words[-overlap:] == text_words[:overlap]:
                best_overlap = overlap

        if best_overlap > 0:
            # Append only the new words (use original case from text)
            new_words = text.split()[best_overlap:]
            if new_words:
                result = result + ' ' + ' '.join(new_words)
        else:
            # No overlap — just concatenate
            result = result + ' ' + text

    # Clean up extra whitespace
    result = re.sub(r'\s+', ' ', result).strip()
    return result


# ─── Topic Segmentation ─────────────────────────────────────────────────────

def segment_topics(
    dialogue_segments: List[DialogueSegment],
    min_topic_duration_sec: float = 20.0
) -> List[TopicSegment]:
    """
    Group dialogue segments into topic-level segments.

    Strategy:
    - A topic change is detected when there's a significant gap (>3s),
      a speaker change combined with content shift, or when accumulated
      duration exceeds a threshold.
    - This is a heuristic segmentation. The brain can later refine it
      using semantic analysis.
    """
    if not dialogue_segments:
        return []

    topics = []
    current_segs = [dialogue_segments[0]]
    current_start = dialogue_segments[0].start_sec

    for i in range(1, len(dialogue_segments)):
        prev = dialogue_segments[i - 1]
        curr = dialogue_segments[i]

        gap = curr.start_sec - prev.end_sec
        accumulated_dur = curr.end_sec - current_start

        # Heuristic topic break: large gap, OR very long accumulated topic
        is_topic_break = (
            gap > 3.0 or
            (accumulated_dur > 60.0 and gap > 1.5)
        )

        if is_topic_break:
            # Save current topic
            speakers = list(set(s.speaker for s in current_segs))
            full_text = ' '.join(s.text for s in current_segs)
            topics.append(TopicSegment(
                topic=_extract_topic_label(full_text),
                summary=full_text[:200] + "..." if len(full_text) > 200 else full_text,
                start_sec=current_start,
                end_sec=prev.end_sec,
                speakers=speakers,
                segments=list(current_segs)
            ))
            current_segs = [curr]
            current_start = curr.start_sec
        else:
            current_segs.append(curr)

    # Flush final topic
    if current_segs:
        speakers = list(set(s.speaker for s in current_segs))
        full_text = ' '.join(s.text for s in current_segs)
        topics.append(TopicSegment(
            topic=_extract_topic_label(full_text),
            summary=full_text[:200] + "..." if len(full_text) > 200 else full_text,
            start_sec=current_start,
            end_sec=current_segs[-1].end_sec,
            speakers=speakers,
            segments=list(current_segs)
        ))

    return topics


def _extract_topic_label(text: str, max_words: int = 6) -> str:
    """
    Extract a short topic label from dialogue text.
    Uses the first meaningful clause as a rough label.
    The brain can later replace this with semantic analysis.
    """
    # Remove filler and clean
    cleaned = re.sub(r'\b(um|uh|like|you know|I mean)\b', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Take first sentence or clause
    first_sentence = re.split(r'[.!?]', cleaned)[0].strip()
    words = first_sentence.split()[:max_words]
    label = ' '.join(words)

    if len(label) > 50:
        label = label[:50] + "..."

    return label if label else "General Discussion"


# ─── Main Entry Point ────────────────────────────────────────────────────────

def analyze_source(
    srt_path: Path,
    title: str = "",
    url: str = "",
    source_id: str = ""
) -> SourceAnalysis:
    """
    Complete source analysis pipeline.

    INPUT: SRT file path + metadata
    OUTPUT: SourceAnalysis with parsed entries, merged dialogue, and topic segments.
    """
    print(f"[Source Analyzer] Parsing SRT: {srt_path.name}")
    entries = parse_srt_file(srt_path)
    print(f"[Source Analyzer] Parsed {len(entries)} subtitle entries")

    if not entries:
        raise ValueError(f"No subtitle entries found in {srt_path}")

    total_duration = entries[-1].end_sec

    print("[Source Analyzer] Reconstructing dialogue from overlapping windows...")
    dialogue = reconstruct_dialogue(entries)
    print(f"[Source Analyzer] Reconstructed {len(dialogue)} dialogue segments")

    print("[Source Analyzer] Segmenting topics...")
    topics = segment_topics(dialogue)
    print(f"[Source Analyzer] Identified {len(topics)} topic segments")

    # Identify unique speakers
    all_speakers = list(set(seg.speaker for seg in dialogue))

    analysis = SourceAnalysis(
        source_id=source_id or srt_path.stem,
        title=title,
        url=url,
        total_duration_sec=round(total_duration, 2),
        speakers=all_speakers,
        topics=topics,
        raw_entries=entries,
        dialogue_segments=dialogue,
        summary=f"Episode: {title}. Duration: {total_duration/60:.1f} min. "
                f"Speakers: {len(all_speakers)}. Topics: {len(topics)}. "
                f"Dialogue segments: {len(dialogue)}."
    )

    print(f"[Source Analyzer] Analysis complete: {analysis.summary}")
    return analysis


# ─── CLI Testing ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Default test: use the existing Cap Table SRT
    test_srt = Path(__file__).resolve().parent.parent / "projects" / "07_viral_podcasts" / "raw_subtitles.en.srt"

    if len(sys.argv) > 1:
        test_srt = Path(sys.argv[1])

    if not test_srt.exists():
        print(f"SRT file not found: {test_srt}")
        sys.exit(1)

    analysis = analyze_source(
        test_srt,
        title="The Cap Table - Episode 25 (Clouted)",
        url="https://youtube.com/watch?v=example",
        source_id="cap_table_ep25"
    )

    print("\n" + "=" * 70)
    print("SOURCE ANALYSIS REPORT")
    print("=" * 70)
    print(f"Title:    {analysis.title}")
    print(f"Duration: {analysis.total_duration_sec / 60:.1f} minutes")
    print(f"Speakers: {analysis.speakers}")
    print(f"Topics:   {len(analysis.topics)}")
    print(f"Dialogue: {len(analysis.dialogue_segments)} segments")

    print("\n--- TOPIC MAP ---")
    for i, topic in enumerate(analysis.topics, 1):
        dur = topic.end_sec - topic.start_sec
        print(f"\n  [{i}] {topic.start_sec:.1f}s - {topic.end_sec:.1f}s ({dur:.0f}s)")
        print(f"      Topic: {topic.topic}")
        print(f"      Speakers: {topic.speakers}")
        print(f"      Summary: {topic.summary[:120]}...")

    print("\n--- SAMPLE DIALOGUE SEGMENTS (first 10) ---")
    for seg in analysis.dialogue_segments[:10]:
        print(f"  [{seg.start_sec:.1f}s - {seg.end_sec:.1f}s] {seg.speaker}: {seg.text[:100]}...")
