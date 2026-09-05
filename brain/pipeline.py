"""
Creative Intelligence Engine -- Full Production Pipeline

PURPOSE:
    End-to-end autonomous pipeline that takes a podcast SRT transcript
    and independently produces a ranked set of production-ready clip
    briefs with hook selections, context verification, and complete
    creative decision records.

    This is the BRAIN's primary execution path.

    USER provides: SRT file + metadata
    BRAIN produces: Top N clip briefs ready for rendering

PIPELINE:
    1. SOURCE ANALYSIS    — Parse SRT, reconstruct dialogue, identify topics
    2. CLIP DISCOVERY     — Scan for best moments (variable windows, 14-vector scoring)
    3. CONTEXT INTEGRITY  — Verify each candidate preserves speaker meaning
    4. HOOK GENERATION    — Generate & select best truthful hook per candidate
    5. RANKING & SELECTION — Final rank, apply hard-fail filters, select top N
    6. DECISION RECORD    — Complete audit trail for every decision

NO USER INPUT REQUIRED FOR:
    - Timestamp selection
    - Hook creation
    - Creative decisions
    - Quality filtering
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import List, Optional
from dataclasses import asdict

# Ensure project root is importable
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from brain.models import (
    ClipCandidate, HookSelection, CreativeDecisionRecord,
    ContextSafety, CandidateStatus
)
from brain.source_analyzer import analyze_source, SourceAnalysis
from brain.clip_discovery import discover_candidates
from brain.context_engine import verify_context_integrity
from brain.hook_engine import generate_hooks


def run_creative_pipeline(
    srt_path: Path,
    title: str = "",
    url: str = "",
    source_id: str = "",
    max_candidates: int = 20,
    top_n: int = 5,
    min_score: float = 4.0,
    min_duration_sec: float = 30.0,
    max_duration_sec: float = 80.0,
) -> List[CreativeDecisionRecord]:
    """
    Run the full autonomous creative intelligence pipeline.

    Args:
        srt_path: Path to the SRT subtitle file
        title: Episode title
        url: Source URL
        source_id: Unique identifier for this source
        max_candidates: Maximum candidates to evaluate from discovery
        top_n: Number of final clips to produce
        min_score: Minimum final score to consider
        min_duration_sec: Minimum clip duration
        max_duration_sec: Maximum clip duration

    Returns:
        List of CreativeDecisionRecord objects, one per approved clip.
    """

    print("\n" + "=" * 70)
    print("CREATIVE INTELLIGENCE ENGINE -- AUTONOMOUS PIPELINE")
    print("=" * 70)

    # ─── STAGE 1: SOURCE ANALYSIS ────────────────────────────────────────
    print("\n[STAGE 1/5] Analyzing source content...")
    analysis = analyze_source(
        srt_path=srt_path,
        title=title,
        url=url,
        source_id=source_id or srt_path.stem
    )
    print(f"  Result: {len(analysis.dialogue_segments)} dialogue segments, "
          f"{len(analysis.speakers)} speakers, "
          f"{analysis.total_duration_sec / 60:.1f} min")

    # ─── STAGE 2: CLIP DISCOVERY ─────────────────────────────────────────
    print(f"\n[STAGE 2/5] Discovering candidate clip moments...")
    all_candidates = discover_candidates(
        analysis,
        min_window_sec=min_duration_sec,
        max_window_sec=max_duration_sec,
        min_score_threshold=min_score
    )
    print(f"  Result: {len(all_candidates)} unique candidates discovered")

    if not all_candidates:
        print("  [!] No candidates found above threshold. Try lowering min_score.")
        return []

    # Take top candidates for deeper analysis
    candidates = all_candidates[:max_candidates]
    print(f"  Proceeding with top {len(candidates)} for deep analysis")

    # ─── STAGE 3: CONTEXT INTEGRITY ──────────────────────────────────────
    print(f"\n[STAGE 3/5] Verifying context integrity...")
    verified = []
    rejected_context = 0

    for candidate in candidates:
        verify_context_integrity(candidate)

        if candidate.context_safety in (
            ContextSafety.MISLEADING, ContextSafety.REJECT
        ):
            candidate.status = CandidateStatus.REJECTED
            candidate.rejection_reason = f"Context: {candidate.context_safety.value}"
            rejected_context += 1
        else:
            verified.append(candidate)

    print(f"  Result: {len(verified)} passed, {rejected_context} rejected for context issues")

    if not verified:
        print("  [!] All candidates failed context integrity. Source may not be suitable.")
        return []

    # ─── STAGE 4: HOOK GENERATION ────────────────────────────────────────
    print(f"\n[STAGE 4/5] Generating hook variants for top candidates...")
    hook_map = {}

    for candidate in verified:
        selection = generate_hooks(candidate)
        hook_map[candidate.candidate_id] = selection

        if selection.selected:
            # Boost the candidate score based on hook quality
            hook_bonus = selection.selected.hook_strength * 0.1
            candidate.confidence = min(1.0, candidate.confidence + hook_bonus * 0.1)

    hookless = [c for c in verified if not hook_map.get(c.candidate_id, HookSelection()).selected]
    print(f"  Result: {len(verified) - len(hookless)} clips have viable hooks, "
          f"{len(hookless)} need manual hook review")

    # ─── STAGE 5: FINAL RANKING & SELECTION ──────────────────────────────
    print(f"\n[STAGE 5/5] Final ranking and selection (top {top_n})...")

    # Re-sort with hook quality factored in
    def composite_score(c: ClipCandidate) -> float:
        base = c.final_score
        hook_sel = hook_map.get(c.candidate_id)
        if hook_sel and hook_sel.selected:
            hook_factor = (hook_sel.selected.truthfulness_score * 0.3 +
                          hook_sel.selected.hook_strength * 0.7) / 10.0
            return base * (0.7 + 0.3 * hook_factor)
        return base * 0.7  # Penalize hookless candidates

    verified.sort(key=composite_score, reverse=True)
    selected = verified[:top_n]

    # ─── BUILD DECISION RECORDS & EDIT PLANS ────────────────────────────
    from brain.edit_planner import create_edit_plan
    records = []
    for i, candidate in enumerate(selected, 1):
        candidate.status = CandidateStatus.SELECTED
        hook_sel = hook_map.get(candidate.candidate_id, HookSelection())
        edit_plan = create_edit_plan(candidate, hook_sel, analysis)

        record = CreativeDecisionRecord(
            candidate=candidate,
            hook_selection=hook_sel,
            edit_plan=edit_plan,
            qa_results=[],
            repairs=[],
            final_status="SELECTED_FOR_PRODUCTION",
            final_cloud_path="",
        )
        records.append(record)

    print(f"\n  SELECTED {len(records)} CLIPS FOR PRODUCTION (EditPlans Generated)")

    return records


def print_production_brief(records: List[CreativeDecisionRecord]):
    """Print a human-readable production brief for all selected clips."""

    print("\n" + "=" * 70)
    print("PRODUCTION BRIEF -- AUTONOMOUS CREATIVE INTELLIGENCE")
    print("=" * 70)

    for i, record in enumerate(records, 1):
        c = record.candidate
        h = record.hook_selection

        print(f"\n{'-' * 60}")
        print(f"  CLIP {i} of {len(records)}")
        print(f"{'-' * 60}")
        print(f"  ID:       {c.candidate_id}")
        print(f"  Time:     {c.start_sec:.1f}s - {c.end_sec:.1f}s ({c.duration_sec:.0f}s)")
        print(f"  Type:     {c.content_type.value}")
        print(f"  Topic:    {c.topic}")
        print(f"  Speakers: {', '.join(c.speakers)}")
        print(f"  Score:    {c.final_score:.2f}/10")
        print(f"  Context:  {c.context_safety.value}")
        print(f"  Claims:   {len(c.claims)}")

        print(f"\n  TRANSCRIPT (first 300 chars):")
        print(f"  {c.transcript[:300]}...")

        if h and h.selected:
            print(f"\n  SELECTED HOOK:")
            print(f"    Mechanism: {h.selected.mechanism.value}")
            print(f"    Text:      \"{h.selected.text}\"")
            print(f"    Header:    \"{h.selected.header_text}\"")
            print(f"    Duration:  ~{h.selected.estimated_duration_sec:.1f}s")
            print(f"    Truth:     {h.selected.truthfulness_score:.1f}/10")
            print(f"    Strength:  {h.selected.hook_strength:.1f}/10")
            print(f"    Reasoning: {h.selection_reasoning}")
        else:
            print(f"\n  HOOK: Needs manual review")

        print(f"\n  VIRALITY SCORES:")
        s = c.scores
        print(f"    Hook={s.hook_potential:.1f} Curiosity={s.curiosity:.1f} "
              f"Novelty={s.novelty:.1f} Emotion={s.emotional_intensity:.1f}")
        print(f"    Story={s.story_quality:.1f} Payoff={s.payoff_strength:.1f} "
              f"Share={s.shareability:.1f} Comment={s.comment_potential:.1f}")
        print(f"    Relevance={s.audience_relevance:.1f} Value={s.practical_value:.1f} "
              f"Context={s.context_completeness:.1f}")
        print(f"    Weighted Total: {s.weighted_total:.2f}")

        print(f"\n  NEGATIVE FACTORS:")
        n = c.negatives
        print(f"    Boring={n.boring:.1f} Filler={n.filler_heavy:.1f} "
              f"Repetitive={n.repetitive:.1f} Context-Dep={n.context_dependent:.1f}")
        print(f"    Misleading={n.misleading_risk:.1f} Weak-Payoff={n.weak_payoff:.1f} "
              f"Length={n.excessive_length:.1f}")
        print(f"    Critical Fail: {'YES' if n.has_critical_failure else 'No'}")

        if record.edit_plan:
            ep = record.edit_plan
            clean_cta = ep.cta_text.encode('ascii', errors='ignore').decode('ascii')
            print(f"\n  EDIT PLAN (PHASE 7):")
            print(f"    Body Boundaries: {ep.body_start_sec:.1f}s -> {ep.body_end_sec:.1f}s ({ep.body_end_sec - ep.body_start_sec:.1f}s body)")
            print(f"    Target Duration: {ep.target_duration_sec:.1f}s total (with hook)")
            print(f"    Layout Style:    {ep.layout_style}")
            print(f"    Pacing Notes:    {ep.pacing_notes}")
            print(f"    Punch-Ins:       {len(getattr(ep, 'punch_in_plan', []))} planned")
            for p in getattr(ep, 'punch_in_plan', []):
                print(f"      - +{p['timestamp_offset_sec']}s ({p['duration_sec']}s, scale {p['scale']}x): {p['reason']}")
            print(f"    B-Roll Specs:    {len(ep.broll_decisions)} requests")
            for b in ep.broll_decisions:
                print(f"      - [{b['status']}] {b['visual_concept']} ({b['duration_sec']}s) -> {b['purpose']}")
            print(f"    Caption Emphasis:{', '.join(ep.caption_emphasis_words)}")
            print(f"    Ending Strategy: {ep.ending_strategy} -> \"{clean_cta}\"")

        if c.context_before:
            print(f"\n  CONTEXT BEFORE: ...{c.context_before[-100:]}...")
        if c.context_after:
            print(f"  CONTEXT AFTER:  {c.context_after[:100]}...")

        print(f"\n  STATUS: {record.final_status}")


def save_decision_records(records: List[CreativeDecisionRecord], output_path: Path):
    """Save decision records to JSON for audit trail and future learning."""

    def _serialize(obj):
        """Custom serializer for dataclasses and enums."""
        if hasattr(obj, '__dataclass_fields__'):
            d = {}
            for field_name in obj.__dataclass_fields__:
                val = getattr(obj, field_name)
                d[field_name] = _serialize(val)
            return d
        elif isinstance(obj, list):
            return [_serialize(item) for item in obj]
        elif hasattr(obj, 'value'):  # Enum
            return obj.value
        elif isinstance(obj, Path):
            return str(obj)
        return obj

    serialized = [_serialize(record) for record in records]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(serialized, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n[Pipeline] Decision records saved to: {output_path}")


# ─── CLI Entry Point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_srt = ROOT_DIR / "projects" / "07_viral_podcasts" / "raw_subtitles.en.srt"

    records = run_creative_pipeline(
        srt_path=test_srt,
        title="The Cap Table - Episode 25 (Clouted)",
        url="https://www.youtube.com/watch?v=example",
        source_id="cap_table_ep25",
        top_n=5,
        min_score=4.0,
        min_duration_sec=30.0,
        max_duration_sec=80.0,
    )

    if records:
        print_production_brief(records)

        # Save decision records for audit
        output_json = ROOT_DIR / "projects" / "07_viral_podcasts" / "decision_records.json"
        save_decision_records(records, output_json)
    else:
        print("\n[Pipeline] No clips selected. Source may not contain suitable content.")
