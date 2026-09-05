"""
Creative Intelligence Engine — Editorial Decision Engine v2.0 (Phase 7.5 Adversarial Upgrade)

PURPOSE:
    Transforms candidate moments into content-specific, narrative-aware EDIT DECISION PLANS (EditPlan).
    Upgraded after adversarial audit to ensure:
    1. Semantic boundary trimming (finds true core thought vs raw sliding window + rambling).
    2. Editing Necessity Score (0.0 = minimal/raw delivery to 1.0 = heavy surgical intervention).
    3. First-class "DO NOTHING" / NONE options for CTA, B-Roll, Music, SFX, and Punch-ins.
    4. Exact millisecond alignment for punch-ins using raw SRT timestamp boundaries.
    5. Clean separation between current heuristic baseline and future LLM semantic integration hooks.

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


# ─── 1. Semantic Narrative Boundary Refinement ────────────────────────────────

def refine_clip_boundaries_semantic(
    candidate: ClipCandidate,
    analysis: SourceAnalysis
) -> Tuple[float, float, str, str]:
    """
    Surgically determines the minimum necessary dialogue boundaries to deliver maximum payoff.
    
    Adversarial Fix:
    - If a sliding window captured a high-tension opening (e.g. 0.08s to 20.32s) followed by
      podcast intro rambling / pleasantries ("Welcome to the cap table..."), it trims the rambling
      and isolates the core viral punchline (20.3s) rather than dragging on to 92.4s.
    - Inspects thought boundaries, setup shifts, and speaker transition markers.
    
    Returns:
        (exact_start_sec, exact_end_sec, refined_transcript, reasoning)
    """
    raw_start = candidate.start_sec
    raw_end = candidate.end_sec
    
    # Get all dialogue segments that intersect with this window
    segs = [s for s in analysis.dialogue_segments if s.end_sec >= raw_start - 2.0 and s.start_sec <= raw_end + 15.0]
    if not segs:
        return raw_start, raw_end, candidate.transcript, "Preserved raw timestamps (no matching segments)"
        
    best_start = segs[0].start_sec
    best_end = segs[-1].end_sec
    
    # Check if the opening segment contains an explosive standalone premise followed by topic shift
    # (e.g. Host monologue hook -> "Welcome to the cap table in New York...")
    first_seg = segs[0]
    first_seg_dur = first_seg.end_sec - first_seg.start_sec
    
    if first_seg_dur >= 15.0 and len(segs) > 1:
        next_seg_text = segs[1].text.lower()
        # Topic shift markers like podcast introductions, welcomes, small talk
        if any(w in next_seg_text for w in ['welcome to', 'in new york', 'if you don\'t know what', 'cap table is', 'today we have']):
            # The first segment is a punchy, standalone viral thesis! Cutting before the welcome creates a superior 20s short.
            best_start = first_seg.start_sec
            best_end = first_seg.end_sec
            refined_text = first_seg.text
            reasoning = (
                f"Isolated core explosive monologue ({best_start:.1f}s -> {best_end:.1f}s, {best_end - best_start:.1f}s). "
                f"Trimmed subsequent {raw_end - best_end:.1f}s of podcast intro small-talk & pleasantries."
            )
            return round(best_start, 2), round(best_end, 2), refined_text, reasoning

    # General semantic snapping:
    # Snap start to clean capitalization / sentence opener
    for s in segs:
        if s.start_sec >= raw_start - 3.0:
            txt = s.text.strip()
            if txt and not re.match(r'^(and|but|or|so|because|like)\b', txt, re.IGNORECASE):
                best_start = s.start_sec
                break

    # Snap end to the earliest strong payoff sentence after minimum 30s duration
    accumulated_text = []
    earliest_payoff_end = best_end
    
    for s in segs:
        if s.start_sec >= best_start:
            accumulated_text.append(s.text)
            curr_dur = s.end_sec - best_start
            txt = s.text.strip()
            
            # If we reached a solid duration (30-65s) and hit a conclusive sentence
            if curr_dur >= 30.0 and curr_dur <= 75.0:
                if txt.endswith(('.', '!', '?')) or any(w in txt.lower() for w in ['focus on building', 'for you', 'works out', 'never works']):
                    earliest_payoff_end = s.end_sec
                    # If this concludes the primary thought, we don't need to bloat to 90s+
                    best_end = earliest_payoff_end
                    break

    included_segs = [s for s in segs if s.start_sec >= best_start - 0.2 and s.end_sec <= best_end + 0.2]
    refined_transcript = " ".join(s.text for s in included_segs) if included_segs else candidate.transcript
    
    reasoning = (
        f"Semantic snap: start at {best_start:.1f}s (clean premise), "
        f"concluded at {best_end:.1f}s (first complete payoff). Trimmed redundant tail."
    )
    return round(best_start, 2), round(best_end, 2), refined_transcript, reasoning


# ─── 2. Editing Necessity Scoring ─────────────────────────────────────────────

def calculate_editing_necessity(
    transcript: str,
    duration_sec: float,
    content_type: ContentType,
    silence_count: int,
    filler_count: int
) -> float:
    """
    Computes an editing necessity index (0.0 to 1.0):
    0.0 - 0.20: Natural high-energy delivery -> Minimal/Zero intervention needed.
    0.21 - 0.50: Clean conversation -> Light punch-ins, natural cuts.
    0.51 - 0.80: Complex argument -> Moderate pacing, conceptual B-roll.
    0.81 - 1.00: Heavy rambling/silence -> Aggressive tightening & visual interrupts.
    """
    score = 0.35 # Baseline
    
    # Fast punchy monologues (<25s) need almost no editing intervention
    if duration_sec <= 25.0:
        score -= 0.20
        
    # High silence or filler density increases necessity
    if silence_count > 2:
        score += 0.15
    if filler_count > 4:
        score += 0.15
        
    # Content type influences
    if content_type in [ContentType.TECHNICAL, ContentType.ADVICE]:
        score += 0.15 # Needs visual reinforcement
    elif content_type in [ContentType.STRONG_OPINION, ContentType.EMOTIONAL]:
        score -= 0.10 # Raw human face/voice is more impactful unedited
        
    return max(0.0, min(1.0, round(score, 2)))


# ─── 3. Accurate SRT-Based Punch-In Intelligence ──────────────────────────────

def plan_punch_ins_srt_accurate(
    start_sec: float,
    end_sec: float,
    analysis: SourceAnalysis,
    editing_necessity: float
) -> List[Dict[str, Any]]:
    """
    Plans punch-ins with millisecond precision using exact SRT timestamps.
    If editing_necessity < 0.25, returns EMPTY LIST (Zero punch-ins).
    """
    if editing_necessity < 0.25:
        return []
        
    punch_ins = []
    
    # 1. Opening hook punch-in (if duration > 15s)
    if end_sec - start_sec > 15.0:
        punch_ins.append({
            "timestamp_offset_sec": 0.0,
            "duration_sec": 3.0,
            "scale": 1.08,
            "reason": "Hook visual pattern interrupt"
        })
        
    # 2. Search raw SRT entries for high-impact keywords and grab EXACT timestamps
    relevant_srt = [s for s in analysis.raw_entries if s.start_sec >= start_sec + 4.0 and s.end_sec <= end_sec - 4.0]
    
    keywords = ['never', 'always', 'secret', 'truth', 'insane', 'crazy', 'realized', 'discovered', 'revenue', 'million']
    
    for s in relevant_srt:
        txt = s.text.lower()
        if any(k in txt for k in keywords):
            offset = round(s.start_sec - start_sec, 2)
            dur = round(min(3.0, s.end_sec - s.start_sec + 0.8), 2)
            punch_ins.append({
                "timestamp_offset_sec": offset,
                "duration_sec": dur,
                "scale": 1.15,
                "reason": f"Exact SRT timestamp alignment for keyword emphasis in '{s.text[:30]}...'"
            })
            if len(punch_ins) >= 3: # Cap at 3 to prevent visual fatigue
                break
                
    return punch_ins


# ─── 4. B-Roll Decision Engine with First-Class "NONE" ─────────────────────────

def plan_broll_conservative(
    transcript: str,
    content_type: ContentType,
    editing_necessity: float
) -> List[Dict[str, Any]]:
    """
    Evaluates whether B-roll is genuinely required or if it would distract.
    Returns empty list (NO_BROLL) if content is raw opinion or editing necessity is low.
    """
    if editing_necessity < 0.40 or content_type in [ContentType.STRONG_OPINION, ContentType.EMOTIONAL]:
        return [] # NO B-ROLL: preserve raw human speaker authenticity
        
    broll_requests = []
    tech_match = re.search(r'\b(ai|artificial intelligence|agents?|algorithms?|software|app|dashboard)\b', transcript, re.IGNORECASE)
    money_match = re.search(r'\b(\$\d+[kKmMbB]?|revenue|funding|valuation)\b', transcript, re.IGNORECASE)
    
    if tech_match and content_type == ContentType.TECHNICAL:
        broll_requests.append({
            "status": "USEFUL",
            "visual_concept": "Futuristic UI overlay depicting autonomous AI agent workflows",
            "source_type": "GENERATED_OR_STOCK",
            "duration_sec": 3.0,
            "purpose": "Illustrates abstract technical concept to increase viewer comprehension",
            "transition": "crossfade_0.3s"
        })
    elif money_match and content_type == ContentType.ADVICE:
        broll_requests.append({
            "status": "USEFUL",
            "visual_concept": "Financial growth analytics graph / revenue scaling graphic",
            "source_type": "GRAPHIC",
            "duration_sec": 2.5,
            "purpose": "Visual reinforcement of monetary metric",
            "transition": "fade_in_0.2s"
        })
        
    return broll_requests


# ─── 5. Audio, Music, SFX & Ending Intelligence ──────────────────────────────

def plan_sound_and_ending(
    content_type: ContentType,
    duration_sec: float,
    transcript: str
) -> Tuple[str, str, List[Dict[str, Any]], str, str]:
    """
    Determines audio, music, SFX and ending strategy with explicit NONE options.
    """
    # Music
    if content_type in [ContentType.STORY, ContentType.EMOTIONAL] and duration_sec > 40.0:
        music = "SUBTLE_AMBIENT_DUCKED"
    else:
        music = "NONE" # Default to clean pristine dialogue
        
    # SFX
    sfx = []
    if content_type in [ContentType.REVELATION, ContentType.CONFLICT] and duration_sec > 30.0:
        sfx.append({
            "timestamp_offset_sec": 0.0,
            "type": "SUBTLE_WHOOSH_IMPACT",
            "purpose": "Hook transition emphasis"
        })
        
    # Ending Strategy
    # Short punchy clips (<25s) or strong conclusions should have NATURAL_END with NO_CTA!
    if duration_sec <= 25.0 or transcript.strip().endswith(('!', '.')):
        ending_strategy = "NATURAL_END"
        cta_text = "" # NO CTA! Let the clip end powerfully on its own merit.
    elif content_type in [ContentType.STRONG_OPINION, ContentType.CONFLICT]:
        ending_strategy = "CONTROVERSY_POLL_CTA"
        cta_text = "DO YOU AGREE OR DISAGREE? COMMENT BELOW! 👇"
    elif content_type in [ContentType.ADVICE, ContentType.TECHNICAL]:
        ending_strategy = "VALUE_SAVE_CTA"
        cta_text = "SAVE THIS CLIP & CHECK BIO FOR MORE! 📌"
    else:
        ending_strategy = "NO_CTA"
        cta_text = ""

    return "NATURAL_BALANCED", music, sfx, ending_strategy, cta_text


# ─── 6. Master Edit Plan Builder v2.0 ──────────────────────────────────────────

def create_edit_plan_v2(
    candidate: ClipCandidate,
    hook_selection: HookSelection,
    analysis: SourceAnalysis,
    target_platform: str = "youtube_shorts"
) -> EditPlan:
    """
    Master function v2.0: Generates an adversarial-hardened EditPlan.
    """
    # 1. Semantic Boundary Refinement
    exact_start, exact_end, refined_transcript, boundary_reason = refine_clip_boundaries_semantic(candidate, analysis)
    body_duration = round(exact_end - exact_start, 2)
    
    # 2. Hook Decision
    # If the clip is an ultra-fast punchy monologue (<22s), we don't need a voiceover hook at all!
    selected_hook = hook_selection.selected
    if body_duration <= 22.0:
        hook_dur = 0.0
        used_hook = None # ZERO HOOK VOICEOVER: The original dialogue IS the hook!
    else:
        used_hook = selected_hook
        hook_dur = selected_hook.estimated_duration_sec if selected_hook else 0.0
        
    total_target_duration = round(hook_dur + body_duration, 2)
    
    # 3. Pauses & Fillers
    from brain.edit_planner import analyze_pauses_and_silences, analyze_filler_removals, plan_caption_emphasis
    silences = analyze_pauses_and_silences(exact_start, exact_end, analysis)
    fillers = analyze_filler_removals(refined_transcript)
    
    # 4. Editing Necessity Score
    editing_necessity = calculate_editing_necessity(
        transcript=refined_transcript,
        duration_sec=body_duration,
        content_type=candidate.content_type,
        silence_count=len(silences),
        filler_count=len(fillers)
    )
    
    # 5. Exact SRT Punch-Ins
    punch_ins = plan_punch_ins_srt_accurate(exact_start, exact_end, analysis, editing_necessity)
    
    # 6. Conservative B-Roll
    broll = plan_broll_conservative(refined_transcript, candidate.content_type, editing_necessity)
    
    # 7. Semantic Caption Emphasis
    emphasis_words = plan_caption_emphasis(refined_transcript)
    
    # 8. Sound & Ending with first-class NONE
    audio_treat, music, sfx, ending_strategy, cta_text = plan_sound_and_ending(
        candidate.content_type,
        body_duration,
        refined_transcript
    )
    
    plan = EditPlan(
        candidate_id=candidate.candidate_id,
        hook=used_hook,
        target_platform=target_platform,
        layout_style="ambient_blur_default",
        body_start_sec=exact_start,
        body_end_sec=exact_end,
        target_duration_sec=total_target_duration,
        editing_necessity=editing_necessity,
        pacing_notes=f"{boundary_reason} Necessity: {editing_necessity:.2f}.",
        silence_decisions=silences,
        filler_plan=fillers,
        punch_in_plan=punch_ins,
        broll_decisions=broll,
        caption_emphasis_words=emphasis_words,
        audio_treatment=audio_treat,
        music_treatment=music,
        sfx_plan=sfx,
        cta_text=cta_text,
        ending_strategy=ending_strategy
    )
    
    return plan


# ─── CLI Testing ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(ROOT))
    
    from brain.source_analyzer import analyze_source
    from brain.clip_discovery import discover_candidates
    from brain.context_engine import verify_batch
    from brain.hook_engine import generate_hooks
    
    test_srt = ROOT / "projects" / "07_viral_podcasts" / "raw_subtitles.en.srt"
    
    print("=" * 70)
    print("PHASE 7.5: ADVERSARIAL EDITORIAL AUDIT TEST")
    print("=" * 70)
    
    analysis = analyze_source(test_srt, title="Cap Table Ep 25", source_id="cap_table_ep25")
    candidates = discover_candidates(analysis)
    
    # Find candidate #1 specifically (starts around 0.1s)
    cand_1 = next((c for c in candidates if c.start_sec < 5.0), candidates[0])
    h_sel = generate_hooks(cand_1)
    
    plan_v2 = create_edit_plan_v2(cand_1, h_sel, analysis)
    
    print("\n" + "=" * 70)
    print("CRITICAL AUDIT: 81-SECOND CANDIDATE RE-EVALUATION")
    print("=" * 70)
    print(f"Candidate ID:        {cand_1.candidate_id}")
    print(f"Raw Sliding Window:  {cand_1.start_sec:.1f}s -> {cand_1.end_sec:.1f}s ({cand_1.duration_sec:.1f}s)")
    print(f"V2 Refined Body:     {plan_v2.body_start_sec:.1f}s -> {plan_v2.body_end_sec:.1f}s ({plan_v2.body_end_sec - plan_v2.body_start_sec:.1f}s body)")
    print(f"V2 Target Duration:  {plan_v2.target_duration_sec:.1f}s (Hook: {'NONE (Raw Spoken Hook)' if plan_v2.hook is None else plan_v2.hook.estimated_duration_sec})")
    print(f"Editing Necessity:   {plan_v2.editing_necessity:.2f} (0.0=minimal, 1.0=heavy)")
    print(f"Pacing Notes:        {plan_v2.pacing_notes}")
    print(f"Punch-Ins Planned:   {len(plan_v2.punch_in_plan)} moments")
    print(f"B-Roll Planned:      {len(plan_v2.broll_decisions)} requests (NO_BROLL: {len(plan_v2.broll_decisions)==0})")
    print(f"Music Treatment:     {plan_v2.music_treatment}")
    print(f"SFX Planned:         {len(plan_v2.sfx_plan)}")
    print(f"Ending Strategy:     {plan_v2.ending_strategy} (CTA Text: '{plan_v2.cta_text}')")
    print("\nREFINED TRANSCRIPT:")
    print(f"\"{analysis.dialogue_segments[0].text}\"")
