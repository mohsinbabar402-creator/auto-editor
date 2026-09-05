"""
Creative Intelligence Engine — Editorial Decision Engine (Phase 7)

PURPOSE:
    Transforms a candidate moment into a surgical, content-specific EDIT DECISION PLAN (EditPlan).
    Acts as the master short-form editor:
    - Analyzes the attention curve & narrative structure
    - Refines rough window timestamps into exact, natural sentence/thought boundaries
    - Classifies pauses (keep dramatic pauses, remove dead space)
    - Identifies filler phrases
    - Determines punch-in / zoom moments for emotional/claim emphasis
    - Decides if B-roll is required/optional/none and generates exact visual briefs
    - Selects keyword emphasis for captions
    - Designs audio/music/SFX pacing and ending strategy
    - Adapts parameters for target platform (YouTube Shorts, TikTok, Instagram Reels)

INPUTS:
    - ClipCandidate
    - HookSelection
    - SourceAnalysis (with dialogue segments & raw SRT entries)
    - Platform target

OUTPUT:
    - EditPlan (comprehensive, structured specification consumable by renderer)
"""

from __future__ import annotations
import re
from typing import List, Dict, Any, Optional, Tuple
from brain.models import (
    ClipCandidate, HookSelection, SourceAnalysis, DialogueSegment,
    SRTEntry, EditPlan, ContentType, HookCandidate
)


# ─── 1. Semantic Boundary Refinement ──────────────────────────────────────────

def refine_clip_boundaries(
    candidate: ClipCandidate,
    analysis: SourceAnalysis,
    max_boundary_drift_sec: float = 12.0
) -> Tuple[float, float, str, str]:
    """
    Refines rough sliding-window timestamps into exact, clean sentence boundaries.
    
    Checks dialogue segments and raw SRT entries:
    - Snaps start to the beginning of a coherent sentence or thought.
    - Snaps end to a complete conclusion/punchline (never cutting mid-sentence).
    - Ensures setup and payoff are intact while trimming dead rambling.
    
    Returns:
        (exact_start_sec, exact_end_sec, refined_transcript, reasoning)
    """
    raw_start = candidate.start_sec
    raw_end = candidate.end_sec
    
    # Get all dialogue segments that intersect with [raw_start - drift, raw_end + drift]
    relevant_segs = [
        s for s in analysis.dialogue_segments
        if s.end_sec >= raw_start - max_boundary_drift_sec and s.start_sec <= raw_end + max_boundary_drift_sec
    ]
    
    if not relevant_segs:
        return raw_start, raw_end, candidate.transcript, "Preserved raw timestamps (no matching segments)"

    # --- Refine Start Boundary ---
    # Find the segment closest to raw_start that begins cleanly
    best_start = raw_start
    best_start_seg = relevant_segs[0]
    
    for s in relevant_segs:
        # If segment starts within drift window of raw_start
        if abs(s.start_sec - raw_start) <= max_boundary_drift_sec:
            # Check if text starts with capital letter or clear opener
            txt = s.text.strip()
            if txt and (txt[0].isupper() or not re.match(r'^(and|but|or|so|because|like)\b', txt, re.IGNORECASE)):
                best_start = s.start_sec
                best_start_seg = s
                break
            elif s.start_sec >= raw_start:
                best_start = s.start_sec
                best_start_seg = s
                break

    # --- Refine End Boundary ---
    # Find the segment closest to raw_end that concludes a thought (. ! ? or strong clause)
    best_end = raw_end
    for s in reversed(relevant_segs):
        if s.end_sec <= raw_end + max_boundary_drift_sec and s.start_sec >= best_start:
            txt = s.text.strip()
            # If it ends with punctuation or strong terminal word
            if txt and (txt.endswith(('.', '!', '?')) or not re.search(r'\b(and|but|or|so|because|with|to|that)\s*$', txt, re.IGNORECASE)):
                best_end = s.end_sec
                break
                
    # Safeguard duration
    if best_end - best_start < 20.0:
        best_end = min(analysis.total_duration_sec, best_start + candidate.duration_sec)

    # Rebuild refined transcript
    included_segs = [s for s in relevant_segs if s.start_sec >= best_start - 0.5 and s.end_sec <= best_end + 0.5]
    refined_transcript = " ".join(s.text for s in included_segs) if included_segs else candidate.transcript
    
    reasoning = (
        f"Snapped start from {raw_start:.1f}s -> {best_start:.1f}s (clean opener) "
        f"and end from {raw_end:.1f}s -> {best_end:.1f}s (sentence conclusion). "
        f"Duration: {best_end - best_start:.1f}s."
    )
    
    return round(best_start, 2), round(best_end, 2), refined_transcript, reasoning


# ─── 2. Pause & Silence Classification ────────────────────────────────────────

def analyze_pauses_and_silences(
    start_sec: float,
    end_sec: float,
    analysis: SourceAnalysis
) -> List[Dict[str, Any]]:
    """
    Inspects gaps between consecutive SRT entries / dialogue segments.
    Classifies pauses as:
    - UNNECESSARY (dead air > 1.2s without emotional buildup -> cut/tighten)
    - DRAMATIC (pause right after a shocking statement -> KEEP)
    - NATURAL (conversational breathing room 0.3s - 0.8s -> KEEP)
    """
    segs = [s for s in analysis.raw_entries if s.start_sec >= start_sec and s.end_sec <= end_sec]
    decisions = []
    
    for i in range(len(segs) - 1):
        gap = segs[i+1].start_sec - segs[i].end_sec
        gap_start = segs[i].end_sec
        gap_end = segs[i+1].start_sec
        prev_text = segs[i].text.lower()
        
        if gap > 1.2:
            # Check if previous statement was high-tension
            if any(w in prev_text for w in ['never', 'impossible', 'crazy', 'insane', 'million', 'billion', 'truth', 'secret']):
                decisions.append({
                    "start": round(gap_start, 2),
                    "end": round(gap_end, 2),
                    "duration": round(gap, 2),
                    "classification": "DRAMATIC",
                    "action": "KEEP",
                    "reason": "Dramatic pause emphasizing high-impact statement"
                })
            else:
                decisions.append({
                    "start": round(gap_start, 2),
                    "end": round(gap_end, 2),
                    "duration": round(gap, 2),
                    "classification": "UNNECESSARY",
                    "action": "TIGHTEN",
                    "reason": f"Dead air ({gap:.1f}s) without dramatic value -> tighten to 0.4s"
                })
        elif gap > 0.4:
            decisions.append({
                "start": round(gap_start, 2),
                "end": round(gap_end, 2),
                "duration": round(gap, 2),
                "classification": "NATURAL",
                "action": "KEEP",
                "reason": "Natural conversational breathing space"
            })
            
    return decisions


# ─── 3. Filler Phrase Analysis ───────────────────────────────────────────────

def analyze_filler_removals(transcript: str) -> List[Dict[str, Any]]:
    """
    Identifies obvious filler words / stuttering that can be cleanly tightened.
    """
    removals = []
    filler_patterns = [
        (r'\b(um|uh)\b', "filler_vocalization"),
        (r'\b(like\s+like|you\s+know\s+you\s+know)\b', "stutter_repetition"),
        (r'\b(I\s+mean\s+like)\b', "rambling_lead_in")
    ]
    for pat, ftype in filler_patterns:
        for m in re.finditer(pat, transcript, re.IGNORECASE):
            removals.append({
                "phrase": m.group(0),
                "type": ftype,
                "position": m.start(),
                "recommendation": "TIGHTEN_IF_ISOLATED"
            })
    return removals


# ─── 4. Punch-In / Dynamic Zoom Intelligence ─────────────────────────────────

def plan_punch_ins(
    start_sec: float,
    end_sec: float,
    transcript: str,
    content_type: ContentType
) -> List[Dict[str, Any]]:
    """
    Determines intentional punch-in / camera zoom moments based on content importance:
    - Hook punch-in (0.0s - 3.0s, subtle 1.08x scale)
    - Key claim punch-in (1.15x scale)
    - Revelation punch-in (1.20x scale)
    - Reset to 1.0x master frame during narrative setups
    """
    punch_ins = []
    
    # 1. Opening hook punch-in
    punch_ins.append({
        "timestamp_offset_sec": 0.0,
        "duration_sec": 3.5,
        "scale": 1.08,
        "reason": "Hook visual pattern interrupt"
    })
    
    # 2. Search for revelation or high-value numerical statements
    revelation_matches = list(re.finditer(
        r'\b(\$\d+[kKmMbB]?|\d+%\b|never|always|secret|truth|insane|crazy|realized|discovered)\b',
        transcript,
        re.IGNORECASE
    ))
    
    total_dur = end_sec - start_sec
    for m in revelation_matches[:3]: # Max 3 punch-ins per clip to avoid chaotic twitching
        char_ratio = m.start() / max(1, len(transcript))
        est_time_offset = round(char_ratio * total_dur, 1)
        if est_time_offset > 4.0 and est_time_offset < total_dur - 4.0:
            punch_ins.append({
                "timestamp_offset_sec": est_time_offset,
                "duration_sec": 2.8,
                "scale": 1.15,
                "reason": f"Emphasis on critical revelation keyword '{m.group(0)}'"
            })
            
    return punch_ins


# ─── 5. B-Roll Decision Engine ───────────────────────────────────────────────

def plan_broll(
    transcript: str,
    content_type: ContentType,
    duration_sec: float
) -> List[Dict[str, Any]]:
    """
    Decides whether B-roll visual overlays are required, optional, or prohibited.
    
    Rules:
    - B-roll is NEVER inserted merely to fill space.
    - If a concrete entity, technology, platform, or monetary metric is discussed,
      create an explicit B-roll specification.
    - Otherwise, preserve clean speaker focus with Ambient Blur layout.
    """
    broll_requests = []
    
    # Search for concrete visual opportunities
    tech_match = re.search(r'\b(ai|artificial intelligence|agents?|algorithms?|software|app|dashboard)\b', transcript, re.IGNORECASE)
    money_match = re.search(r'\b(\$\d+[kKmMbB]?|revenue|funding|valuation|cash)\b', transcript, re.IGNORECASE)
    gaming_match = re.search(r'\b(overwatch|gaming|esports|pro gamer|league)\b', transcript, re.IGNORECASE)
    
    if tech_match:
        broll_requests.append({
            "status": "OPTIONAL",
            "visual_concept": "Futuristic UI overlay depicting autonomous AI agent workflows",
            "source_type": "GENERATED_OR_STOCK",
            "duration_sec": 3.0,
            "purpose": "Illustrates abstract AI concept to increase viewer comprehension",
            "transition": "crossfade_0.3s"
        })
    elif money_match:
        broll_requests.append({
            "status": "OPTIONAL",
            "visual_concept": "Financial growth analytics graph / revenue scaling graphic",
            "source_type": "GRAPHIC",
            "duration_sec": 2.5,
            "purpose": "Visual reinforcement of monetary metric",
            "transition": "fade_in_0.2s"
        })
    elif gaming_match:
        broll_requests.append({
            "status": "OPTIONAL",
            "visual_concept": "Competitive esports arena / gameplay HUD aesthetic",
            "source_type": "STOCK",
            "duration_sec": 3.0,
            "purpose": "Contextual visual anchor for competitive gaming discussion",
            "transition": "quick_cut"
        })
        
    return broll_requests


# ─── 6. Caption Emphasis Engine ──────────────────────────────────────────────

def plan_caption_emphasis(transcript: str) -> List[str]:
    """
    Extracts high-impact semantic words to highlight in vivid yellow (&H0000FFFF)
    rather than highlighting words arbitrarily.
    """
    candidates = []
    
    # Monetary / Numbers
    for m in re.finditer(r'\b(\$\d+[kKmMbB]?|\d+%\b|\d+\s*(?:thousand|million|billion|dollars?))\b', transcript, re.IGNORECASE):
        candidates.append(m.group(0).upper())
        
    # High-intensity action / outcome keywords
    for m in re.finditer(r'\b(ai agents?|never|always|secret|insane|crazy|realized|clipping|vc|pro gamer|revenue)\b', transcript, re.IGNORECASE):
        candidates.append(m.group(0).upper())
        
    # Deduplicate while preserving order
    seen = set()
    emphasis_words = []
    for w in candidates:
        if w not in seen and len(w) > 2:
            seen.add(w)
            emphasis_words.append(w)
            
    return emphasis_words[:8] # Top 8 most impactful keywords


# brain/edit_planner.py — Production Editorial Decision Engine (v2.0 Adversarial Standard)
from brain.edit_planner_v2 import (
    refine_clip_boundaries_semantic,
    calculate_editing_necessity,
    plan_punch_ins_srt_accurate,
    plan_broll_conservative,
    plan_sound_and_ending,
    create_edit_plan_v2 as create_edit_plan
)

def create_edit_plans_batch(
    candidates: List[ClipCandidate],
    hook_selections: List[HookSelection],
    analysis: SourceAnalysis,
    target_platform: str = "youtube_shorts"
) -> List[EditPlan]:
    """Generates edit plans for a batch of verified candidates using v2 standards."""
    plans = []
    hook_dict = {h.candidate_id: h for h in hook_selections}
    
    for cand in candidates:
        h_sel = hook_dict.get(cand.candidate_id, HookSelection(candidate_id=cand.candidate_id))
        plan = create_edit_plan(cand, h_sel, analysis, target_platform)
        plans.append(plan)
        print(f"[Edit Planner] Generated EditPlan for {cand.candidate_id}: {plan.body_start_sec:.1f}s -> {plan.body_end_sec:.1f}s ({plan.target_duration_sec:.1f}s total)")
        
    return plans
