"""
Creative Intelligence Engine — Clip Discovery (Phase 2)

PURPOSE:
    Autonomously scan the entire episode transcript and discover candidate
    clip moments WITHOUT any user-supplied timestamps.

    The engine slides a variable-width window across the dialogue,
    evaluates each window for clip potential, and produces a ranked
    list of candidates with full context.

INPUTS:
    - SourceAnalysis (from source_analyzer)

OUTPUTS:
    - List[ClipCandidate] — ranked by final_score, with context and reasoning

STRATEGY:
    1. Slide variable windows (30s to 90s) across dialogue segments.
    2. For each window, extract the full transcript text.
    3. Evaluate the text against multiple virality/quality dimensions.
    4. Score each candidate using the multi-vector scoring model.
    5. Deduplicate overlapping candidates (keep the strongest).
    6. Return ranked candidates.

    The scoring uses keyword/pattern heuristics as a fast first pass.
    The brain can later run LLM semantic analysis on the top candidates.
"""

from __future__ import annotations
import re
from typing import List, Tuple
from brain.models import (
    SourceAnalysis, DialogueSegment, ClipCandidate, VirialityScores,
    NegativeFactors, ContentType, ContextSafety, CandidateStatus
)


# ─── Signal Detection Patterns ──────────────────────────────────────────────

# Words/phrases that indicate high-value content
SIGNAL_PATTERNS = {
    'strong_claim': [
        r'\b(never|always|nobody|everyone|impossible|guaranteed|secret|truth)\b',
        r'\b(the (?:real|actual|honest|brutal) truth)\b',
        r'\b(most people (?:don.t|dont|never|won.t))\b',
        r'\b(here.s (?:the thing|what (?:happened|nobody)))\b',
    ],
    'money_business': [
        r'\$\d+',
        r'\b(\d+[kK]|\d+ (?:thousand|million|billion))\b',
        r'\b(revenue|profit|funding|raised|valuation|ARR|MRR)\b',
        r'\b(making money|income|salary|pay|earning)\b',
    ],
    'story_narrative': [
        r'\b(I (?:remember|was|had|did|went|started|quit|dropped|left|built))\b',
        r'\b(when I was|back (?:when|in)|growing up|one day|that moment)\b',
        r'\b(and then|suddenly|turns out|that.s when|everything changed)\b',
    ],
    'controversy_conflict': [
        r'\b(wrong|stupid|terrible|awful|trash|fake|lying|scam)\b',
        r'\b(people (?:think|say|believe|assume))\b',
        r'\b(controversial|disagree|unpopular opinion|hot take)\b',
        r'\b(fight|argue|debate|clash|versus|vs)\b',
    ],
    'emotion_intensity': [
        r'\b(crazy|insane|unbelievable|incredible|amazing|shocking)\b',
        r'\b(scared|terrified|angry|furious|heartbroken|devastated)\b',
        r'\b(love|hate|passionate|obsessed|blown away)\b',
    ],
    'practical_advice': [
        r'\b(you (?:should|need to|have to|must|can)|tip|trick|hack|strategy)\b',
        r'\b(the (?:key|secret|best way|fastest way|only way))\b',
        r'\b(step (?:one|two|three|1|2|3)|first|second|third)\b',
        r'\b(how (?:to|I|we|you)|here.s how)\b',
    ],
    'revelation': [
        r'\b(found out|discovered|realized|learned|figured out)\b',
        r'\b(turns out|actually|in reality|the truth is)\b',
        r'\b(what (?:most|nobody|people don.t) (?:know|realize|understand))\b',
        r'\b(changed (?:my|everything|the game))\b',
    ],
    'ai_tech': [
        r'\b(AI|artificial intelligence|machine learning|GPT|LLM)\b',
        r'\b(automat(?:e|ed|ion|ing)|agent|bot|algorithm)\b',
        r'\b(tech|startup|app|platform|software|SaaS)\b',
    ],
}

# Patterns indicating low-value content
NEGATIVE_PATTERNS = {
    'filler': [
        r'\b(um|uh|like|you know|I mean|sort of|kind of)\b',
    ],
    'small_talk': [
        r'\b(how are you|nice to meet|welcome to|thanks for (?:coming|having))\b',
        r'\b(before we (?:start|begin|dive)|let.s (?:get into|talk about))\b',
    ],
    'laughter_noise': [
        r'\[laughter\]',
        r'\[music\]',
        r'\[applause\]',
    ],
    'repetition': [
        r'(\b\w+\b)(?:\s+\1){2,}',  # Same word repeated 3+ times
    ],
}


# ─── Scoring Functions ──────────────────────────────────────────────────────

def _count_pattern_matches(text: str, patterns: List[str]) -> int:
    """Count total regex matches across a list of patterns."""
    count = 0
    for pat in patterns:
        count += len(re.findall(pat, text, re.IGNORECASE))
    return count


def _score_dimension(text: str, patterns: List[str], max_score: float = 10.0, saturation: int = 5) -> float:
    """
    Score a text dimension based on pattern matches.
    Saturates at 'saturation' matches = max_score.
    """
    matches = _count_pattern_matches(text, patterns)
    return min(max_score, (matches / saturation) * max_score)


def _detect_content_type(text: str) -> ContentType:
    """Determine the primary content type from dialogue text."""
    scores = {}
    scores[ContentType.STORY] = _count_pattern_matches(text, SIGNAL_PATTERNS['story_narrative'])
    scores[ContentType.STRONG_OPINION] = _count_pattern_matches(text, SIGNAL_PATTERNS['strong_claim'])
    scores[ContentType.CONFLICT] = _count_pattern_matches(text, SIGNAL_PATTERNS['controversy_conflict'])
    scores[ContentType.ADVICE] = _count_pattern_matches(text, SIGNAL_PATTERNS['practical_advice'])
    scores[ContentType.REVELATION] = _count_pattern_matches(text, SIGNAL_PATTERNS['revelation'])
    scores[ContentType.EMOTIONAL] = _count_pattern_matches(text, SIGNAL_PATTERNS['emotion_intensity'])
    scores[ContentType.TECHNICAL] = _count_pattern_matches(text, SIGNAL_PATTERNS['ai_tech'])

    if not any(scores.values()):
        return ContentType.STRONG_OPINION

    return max(scores, key=scores.get)


def _compute_filler_ratio(text: str) -> float:
    """Compute the ratio of filler words to total words."""
    words = text.lower().split()
    if not words:
        return 0.0
    filler_count = _count_pattern_matches(text, NEGATIVE_PATTERNS['filler'])
    return min(1.0, filler_count / len(words))


def _has_payoff(text: str) -> bool:
    """Check if the text contains a clear conclusion, result, or payoff."""
    payoff_patterns = [
        r'\b(so (?:that.s|now|we|the)|the result|it worked|turned out)\b',
        r'\b(and (?:that.s|now|it)|which means|because of that)\b',
        r'\b(the (?:answer|solution|key|point|lesson) (?:is|was))\b',
        r'\b(made|earned|generated|grew|built|created|launched|shipped)\b',
    ]
    return _count_pattern_matches(text, payoff_patterns) > 0


def _compute_information_density(text: str) -> float:
    """
    Estimate how information-dense the text is.
    Higher unique word ratio + signal words = higher density.
    """
    words = text.lower().split()
    if len(words) < 10:
        return 0.0
    unique_ratio = len(set(words)) / len(words)

    # Count total signal matches
    total_signals = 0
    for category_patterns in SIGNAL_PATTERNS.values():
        total_signals += _count_pattern_matches(text, category_patterns)

    signal_density = min(1.0, total_signals / (len(words) / 10))
    return round((unique_ratio * 0.4 + signal_density * 0.6) * 10, 2)


def score_candidate_text(text: str, duration_sec: float) -> Tuple[VirialityScores, NegativeFactors]:
    """
    Score a candidate clip's transcript text on all virality dimensions
    and negative factors.
    """
    scores = VirialityScores(
        hook_potential=_score_dimension(text,
            SIGNAL_PATTERNS['strong_claim'] + SIGNAL_PATTERNS['revelation'],
            saturation=4),
        curiosity=_score_dimension(text,
            SIGNAL_PATTERNS['strong_claim'] + SIGNAL_PATTERNS['controversy_conflict'],
            saturation=4),
        novelty=_score_dimension(text,
            SIGNAL_PATTERNS['revelation'] + SIGNAL_PATTERNS['ai_tech'],
            saturation=4),
        emotional_intensity=_score_dimension(text,
            SIGNAL_PATTERNS['emotion_intensity'],
            saturation=3),
        story_quality=_score_dimension(text,
            SIGNAL_PATTERNS['story_narrative'],
            saturation=4),
        payoff_strength=7.0 if _has_payoff(text) else 3.0,
        shareability=_score_dimension(text,
            SIGNAL_PATTERNS['money_business'] + SIGNAL_PATTERNS['ai_tech'],
            saturation=4),
        comment_potential=_score_dimension(text,
            SIGNAL_PATTERNS['controversy_conflict'] + SIGNAL_PATTERNS['strong_claim'],
            saturation=4),
        audience_relevance=_score_dimension(text,
            SIGNAL_PATTERNS['money_business'] + SIGNAL_PATTERNS['practical_advice'] + SIGNAL_PATTERNS['ai_tech'],
            saturation=5),
        practical_value=_score_dimension(text,
            SIGNAL_PATTERNS['practical_advice'],
            saturation=3),
        visual_potential=5.0,  # Baseline — podcast always has speaker on camera
        platform_fit=_clamp_duration_score(duration_sec),
        context_completeness=6.0,  # Default — context engine will refine this
        speaker_credibility=6.0,   # Default — needs external knowledge
    )

    filler_ratio = _compute_filler_ratio(text)
    word_count = len(text.split())

    negatives = NegativeFactors(
        boring=max(0, 5.0 - _compute_information_density(text)),
        repetitive=_score_dimension(text, NEGATIVE_PATTERNS['repetition'], saturation=2),
        context_dependent=0.0,  # Context engine sets this
        misleading_risk=0.0,    # Context engine sets this
        weak_payoff=0.0 if _has_payoff(text) else 4.0,
        excessive_length=max(0, (duration_sec - 75) / 10) if duration_sec > 75 else 0.0,
        poor_audio=0.0,  # Determined post-render
        filler_heavy=min(10.0, filler_ratio * 30),
    )

    # Penalize small talk / intro segments
    small_talk_count = _count_pattern_matches(text, NEGATIVE_PATTERNS['small_talk'])
    if small_talk_count >= 2:
        negatives.boring = min(10.0, negatives.boring + 3.0)

    return scores, negatives


def _clamp_duration_score(duration_sec: float) -> float:
    """
    Score platform fit based on duration.
    Sweet spots: 30-45s (good), 45-70s (optimal for RPM), 70-90s (acceptable).
    """
    if 45 <= duration_sec <= 70:
        return 9.0
    elif 30 <= duration_sec <= 90:
        return 7.0
    elif 20 <= duration_sec <= 30:
        return 5.0
    elif duration_sec > 90:
        return 3.0
    else:
        return 2.0


# ─── Window Scanning Engine ─────────────────────────────────────────────────

def discover_candidates(
    analysis: SourceAnalysis,
    min_window_sec: float = 25.0,
    max_window_sec: float = 80.0,
    step_sec: float = 10.0,
    min_score_threshold: float = 3.5
) -> List[ClipCandidate]:
    """
    Slide variable-width windows across the episode dialogue and
    evaluate each for clip potential.

    Strategy:
    1. For each starting position, try multiple window sizes.
    2. Score each window.
    3. Keep candidates above the minimum score threshold.
    4. Deduplicate overlapping candidates (keep strongest).
    5. Return sorted by final_score descending.
    """
    segments = analysis.dialogue_segments
    if not segments:
        return []

    print(f"[Clip Discovery] Scanning {len(segments)} dialogue segments...")
    print(f"[Clip Discovery] Window range: {min_window_sec}s - {max_window_sec}s, step: {step_sec}s")

    raw_candidates = []
    total_duration = analysis.total_duration_sec

    # Generate start positions
    start_positions = []
    t = segments[0].start_sec
    while t < total_duration - min_window_sec:
        start_positions.append(t)
        t += step_sec

    window_sizes = [30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
    evaluated = 0

    for start_t in start_positions:
        for window_dur in window_sizes:
            if window_dur < min_window_sec or window_dur > max_window_sec:
                continue

            end_t = start_t + window_dur
            if end_t > total_duration:
                continue

            # Collect dialogue segments within this window
            window_segments = [
                s for s in segments
                if s.start_sec >= start_t - 2.0 and s.end_sec <= end_t + 2.0
            ]

            if len(window_segments) < 2:
                continue

            # Build transcript
            transcript = ' '.join(s.text for s in window_segments)

            # Skip very short transcripts (not enough content)
            if len(transcript.split()) < 20:
                continue

            # Score this window
            actual_start = window_segments[0].start_sec
            actual_end = window_segments[-1].end_sec
            actual_dur = actual_end - actual_start

            scores, negatives = score_candidate_text(transcript, actual_dur)
            evaluated += 1

            # Build context strings
            context_before = _get_context_text(segments, actual_start, lookback_sec=15.0)
            context_after = _get_context_text_after(segments, actual_end, lookahead_sec=15.0)

            candidate = ClipCandidate(
                source_id=analysis.source_id,
                start_sec=actual_start,
                end_sec=actual_end,
                transcript=transcript,
                speakers=list(set(s.speaker for s in window_segments)),
                topic=_extract_brief_topic(transcript),
                content_type=_detect_content_type(transcript),
                context_before=context_before,
                context_after=context_after,
                scores=scores,
                negatives=negatives,
                recommended_duration_sec=actual_dur,
                confidence=min(1.0, scores.weighted_total / 8.0),
                status=CandidateStatus.CANDIDATE,
            )

            if candidate.final_score >= min_score_threshold:
                raw_candidates.append(candidate)

    print(f"[Clip Discovery] Evaluated {evaluated} windows, found {len(raw_candidates)} above threshold")

    # Deduplicate overlapping candidates
    deduplicated = _deduplicate_candidates(raw_candidates)
    print(f"[Clip Discovery] After deduplication: {len(deduplicated)} unique candidates")

    # Sort by final score
    deduplicated.sort(key=lambda c: c.final_score, reverse=True)

    return deduplicated


def _get_context_text(segments: List[DialogueSegment], before_time: float, lookback_sec: float) -> str:
    """Get transcript text from segments before the given time."""
    context_segs = [
        s for s in segments
        if s.end_sec <= before_time and s.start_sec >= before_time - lookback_sec
    ]
    return ' '.join(s.text for s in context_segs[-3:])  # Last 3 segments


def _get_context_text_after(segments: List[DialogueSegment], after_time: float, lookahead_sec: float) -> str:
    """Get transcript text from segments after the given time."""
    context_segs = [
        s for s in segments
        if s.start_sec >= after_time and s.end_sec <= after_time + lookahead_sec
    ]
    return ' '.join(s.text for s in context_segs[:3])  # First 3 segments


def _extract_brief_topic(text: str, max_words: int = 8) -> str:
    """Extract a brief topic summary from transcript text."""
    cleaned = re.sub(r'\[.*?\]', '', text)  # Remove [laughter] etc
    cleaned = re.sub(r'\b(um|uh|like|you know)\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    first_clause = re.split(r'[.!?,;]', cleaned)[0].strip()
    words = first_clause.split()[:max_words]
    return ' '.join(words) if words else "General"


def _deduplicate_candidates(candidates: List[ClipCandidate], overlap_threshold: float = 0.5) -> List[ClipCandidate]:
    """
    Remove overlapping candidates, keeping the highest-scoring one in each cluster.

    Two candidates overlap if their time ranges share more than overlap_threshold
    of the shorter candidate's duration.
    """
    if not candidates:
        return []

    # Sort by score descending
    sorted_cands = sorted(candidates, key=lambda c: c.final_score, reverse=True)
    kept = []

    for candidate in sorted_cands:
        overlaps_existing = False
        for existing in kept:
            # Calculate overlap
            overlap_start = max(candidate.start_sec, existing.start_sec)
            overlap_end = min(candidate.end_sec, existing.end_sec)
            overlap_dur = max(0, overlap_end - overlap_start)

            shorter_dur = min(candidate.duration_sec, existing.duration_sec)
            if shorter_dur > 0 and overlap_dur / shorter_dur > overlap_threshold:
                overlaps_existing = True
                break

        if not overlaps_existing:
            kept.append(candidate)

    return kept


# ─── CLI Testing ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
    from brain.source_analyzer import analyze_source
    from pathlib import Path

    test_srt = Path(__file__).resolve().parent.parent / "projects" / "07_viral_podcasts" / "raw_subtitles.en.srt"

    print("=" * 70)
    print("PHASE 2: CLIP DISCOVERY ENGINE TEST")
    print("=" * 70)

    # Phase 1: Analyze source
    analysis = analyze_source(
        test_srt,
        title="The Cap Table - Episode 25 (Clouted)",
        url="https://youtube.com/watch?v=example",
        source_id="cap_table_ep25"
    )

    # Phase 2: Discover candidates
    candidates = discover_candidates(analysis)

    print("\n" + "=" * 70)
    print(f"TOP {min(15, len(candidates))} CANDIDATE CLIPS (Ranked by Score)")
    print("=" * 70)

    for i, c in enumerate(candidates[:15], 1):
        print(f"\n  [{i}] SCORE: {c.final_score:.2f} | CONFIDENCE: {c.confidence:.2f}")
        print(f"      Time: {c.start_sec:.1f}s - {c.end_sec:.1f}s ({c.duration_sec:.0f}s)")
        print(f"      Type: {c.content_type.value}")
        print(f"      Topic: {c.topic}")
        print(f"      Speakers: {c.speakers}")
        print(f"      Transcript (first 150 chars): {c.transcript[:150]}...")
        print(f"      Virality: hook={c.scores.hook_potential:.1f} curiosity={c.scores.curiosity:.1f} "
              f"payoff={c.scores.payoff_strength:.1f} emotion={c.scores.emotional_intensity:.1f}")
        print(f"      Negatives: boring={c.negatives.boring:.1f} filler={c.negatives.filler_heavy:.1f} "
              f"weak_payoff={c.negatives.weak_payoff:.1f}")
