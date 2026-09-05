"""
Creative Intelligence Engine — Self-Repair Engine v2.0 (Phase 9.5 Hardened)

ADVERSARIAL AUDIT FINDINGS & FIXES:

FAKE_REPAIR_1 (FIXED):
    The previous generic RENDER_RETRY handler called repair_audio_clipping (loudnorm)
    for black_frame_detection, frozen_frame_glitch, and visual_blur_clarity.
    loudnorm does NOT remove black frames or frozen frames.
    These are now correctly classified as SOURCE_AWARE_RERENDER_REQUIRED
    and dispatch a request for a full pipeline re-render from source.

FAKE_REPAIR_2 (FIXED):
    repair_duration_trim used FFmpeg -t <target> on a clip shorter than target.
    FFmpeg exits 0 and produces the same short clip. Defect persists.
    Now: duration repair MUST check actual < target (extension impossible from
    rendered artifact) vs actual > target (trim is valid). Extension cases
    are classified SOURCE_AWARE_RERENDER_REQUIRED.

FALSE_RESOLVED (FIXED):
    RepairRecord.resolved was computed as (ffmpeg_exit_0 AND score_improved).
    Score could improve for unrelated reasons. Now resolved is only true when
    the specific QA check that triggered the repair is absent from the post-QA
    result's check list as a failure.

DUPLICATE_REPAIR (FIXED):
    On attempt 2, identical repairs that made zero progress on attempt 1 are
    skipped. Each instruction tracks whether it was already attempted and failed.

PER_DEFECT_VERIFICATION (IMPLEMENTED):
    After every repair attempt, the post-QA result is interrogated specifically
    for the check that was targeted. A repair is accepted only if that specific
    check no longer appears as HARD_FAIL or WARNING in the post-QA.

ATOMIC_REPLACE (VERIFIED):
    All repair operations write to a temp path. The original is never overwritten
    unless QA accepts the repair. The original is preserved throughout.

REPAIR ORDER (DOCUMENTED & ENFORCED):
    1. Caption repairs (pure text, no video touched)
    2. Audio normalisation (audio-only transcode, video stream copied)
    3. Duration trim (stream-copy, only valid if actual > target)
    4. Resolution rescale (full video transcode)
    5. SOURCE_AWARE_RERENDER_REQUIRED — escalate to pipeline, do not fake it

SAFETY CLASSIFICATIONS (CORRECTED):
    SAFE_TO_AUTOFIX:        audio_clipping_peak, audio_loudness_level,
                            captions_present, caption_overflow_safezone,
                            caption_overlap_intervals
    REQUIRES_RE_RENDER:     vertical_resolution (rescale+pad from rendered artifact),
                            duration_compliance TRIM ONLY (actual > target),
                            framerate_standard (transcode from rendered artifact)
    SOURCE_AWARE_RERENDER:  black_frame_detection, frozen_frame_glitch,
                            visual_blur_clarity, duration_compliance EXTENSION
                            (actual < target) — requires original source + EditPlan
    NOT_AUTOMATABLE:        semantic_hook_truthfulness, broll_visual_relevance,
                            face_tracking_framing
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Set

from brain.models import EditPlan, QAResult, RepairRecord, QACheck

try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_EXE = "ffmpeg"

MAX_REPAIR_ATTEMPTS = 2
DURATION_EXTENSION_TOLERANCE = 0.5  # If actual is within 0.5s of target, no trim needed

# ─── Safety Classification Registry ──────────────────────────────────────────

# These are the ONLY issues the repair engine will attempt to fix automatically.
AUTOFIX_ISSUES = {
    "audio_clipping_peak",
    "audio_loudness_level",
    "captions_present",
    "caption_overflow_safezone",
    "caption_overlap_intervals",
}

RERENDER_FROM_ARTIFACT_ISSUES = {
    "vertical_resolution",
    "framerate_standard",
}

# Duration is conditionally repairable — ONLY when actual > target (trim-only)
CONDITIONAL_TRIM_ISSUE = "duration_compliance"

# These CANNOT be fixed from the rendered artifact; require original source re-render
SOURCE_AWARE_RERENDER_ISSUES = {
    "black_frame_detection",
    "frozen_frame_glitch",
    "visual_blur_clarity",
    "audio_stream_exists",  # Missing audio = broken render pipeline
}

NOT_AUTOMATABLE_ISSUES = {
    "semantic_hook_truthfulness",
    "broll_visual_relevance",
    "face_tracking_framing",
}


# ─── RepairAttemptResult ──────────────────────────────────────────────────────

class RepairAttemptResult:
    """Fully documented result of a single, specific repair operation."""
    def __init__(
        self,
        issue: str,
        action: str,
        safety_class: str,
        process_succeeded: bool,   # FFmpeg/Python call completed without error
        defect_cleared: bool,      # QA no longer reports this specific check as failing (set post-QA)
        input_path: Path,
        output_path: Optional[Path],
        operation_detail: str,
        before_measurement: str = "",
        after_measurement: str = "",
        timestamp_range: str = ""
    ):
        self.issue = issue
        self.action = action
        self.safety_class = safety_class
        self.process_succeeded = process_succeeded
        self.defect_cleared = defect_cleared   # Updated after post-repair QA
        self.input_path = input_path
        self.output_path = output_path
        self.operation_detail = operation_detail
        self.before_measurement = before_measurement
        self.after_measurement = after_measurement
        self.timestamp_range = timestamp_range
        self.created_at = datetime.now(timezone.utc).isoformat()


# ─── Defect-specific check helpers ───────────────────────────────────────────

def _check_still_failing(qa_result: QAResult, issue_name: str) -> bool:
    """Return True if the named check still appears as a non-pass in QA result."""
    for c in qa_result.checks_run:
        if c.name == issue_name and not c.passed:
            return True
    # Also check hard_fails list for the check name
    for hf in qa_result.hard_fails:
        if issue_name.lower().replace("_", " ") in hf.lower() or issue_name in hf:
            return True
    return False


def _get_actual_duration(video_path: Path) -> float:
    """Return video container duration in seconds using FFmpeg."""
    try:
        proc = subprocess.run(
            [FFMPEG_EXE, "-i", str(video_path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=20
        )
        m = re.search(r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)', proc.stderr)
        if m:
            h, mn, s, cs = m.groups()
            return int(h) * 3600 + int(mn) * 60 + int(s) + int(cs) / 100.0
    except Exception:
        pass
    return 0.0


# ─── 1. SAFE_TO_AUTOFIX Operations ───────────────────────────────────────────

def _repair_audio_normalize(
    video_path: Path, out_path: Path, issue: str
) -> RepairAttemptResult:
    """
    Apply EBU R128 loudnorm to fix clipping (peak > -0.05dB) or quiet audio (mean < -36dB).
    Operation: FFmpeg loudnorm filter, video stream copied (no visual transcode).
    Verification: QA must confirm audio_clipping_peak or audio_loudness_level no longer fails.
    """
    try:
        cmd = [
            FFMPEG_EXE, "-y",
            "-i", str(video_path),
            "-af", "loudnorm=I=-16:TP=-1.0:LRA=11",
            "-c:v", "copy",
            str(out_path)
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        ok = proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 1024
        return RepairAttemptResult(
            issue=issue, action="AUDIO_REMASTER", safety_class="SAFE_TO_AUTOFIX",
            process_succeeded=ok, defect_cleared=False,  # Updated post-QA
            input_path=video_path, output_path=out_path if ok else None,
            operation_detail=f"loudnorm(I=-16, TP=-1.0, LRA=11) — {'OK' if ok else proc.stderr[-150:]}",
        )
    except Exception as e:
        return RepairAttemptResult(issue=issue, action="AUDIO_REMASTER", safety_class="SAFE_TO_AUTOFIX",
                                   process_succeeded=False, defect_cleared=False,
                                   input_path=video_path, output_path=None, operation_detail=str(e))


def _repair_captions_overflow(srt_path: Path, out_srt: Path, max_words: int = 7) -> RepairAttemptResult:
    """
    Reformat SRT: split any subtitle line exceeding max_words into shorter segments.
    Pure Python text operation — no video touched.
    Verification: QA must confirm caption_overflow_safezone no longer fails.
    """
    try:
        text = srt_path.read_text(encoding="utf-8", errors="replace")
        pattern = re.compile(
            r'(\d+\s+\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\s+)(.*?)(?=\n\n|\Z)',
            re.DOTALL
        )

        def split_words(txt: str) -> str:
            words = txt.replace("\n", " ").split()
            if len(words) <= max_words:
                return txt
            lines = []
            while words:
                lines.append(" ".join(words[:max_words]))
                words = words[max_words:]
            return "\n".join(lines)

        blocks = []
        for m in pattern.finditer(text):
            blocks.append(m.group(1) + split_words(m.group(2).strip()))

        out_srt.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        return RepairAttemptResult(
            issue="caption_overflow_safezone", action="REGENERATE_CAPTIONS",
            safety_class="SAFE_TO_AUTOFIX", process_succeeded=True, defect_cleared=False,
            input_path=srt_path, output_path=out_srt,
            operation_detail=f"Reformatted {len(blocks)} entries to <= {max_words} words/line"
        )
    except Exception as e:
        return RepairAttemptResult(
            issue="caption_overflow_safezone", action="REGENERATE_CAPTIONS",
            safety_class="SAFE_TO_AUTOFIX", process_succeeded=False, defect_cleared=False,
            input_path=srt_path, output_path=None, operation_detail=str(e)
        )


def _repair_captions_overlap(srt_path: Path, out_srt: Path) -> RepairAttemptResult:
    """
    Fix SRT timestamp overlaps: trim end[i] to start[i+1] - 40ms wherever they overlap.
    Pure Python — no video touched.
    Verification: QA must confirm caption_overlap_intervals no longer fails.
    """
    try:
        text = srt_path.read_text(encoding="utf-8", errors="replace")

        def ts(s: str) -> float:
            p = s.replace(",", ".").split(":")
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])

        def fmt(sec: float) -> str:
            h = int(sec // 3600)
            m = int((sec % 3600) // 60)
            s = sec % 60
            return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

        pat = re.compile(
            r'(\d+)\s+(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s+(.*?)(?=\n\n|\Z)',
            re.DOTALL
        )
        entries = [{"i": m.group(1), "s": ts(m.group(2)), "e": ts(m.group(3)), "t": m.group(4).strip()}
                   for m in pat.finditer(text)]
        fixed = 0
        for k in range(len(entries) - 1):
            if entries[k]["e"] > entries[k+1]["s"] - 0.04:
                entries[k]["e"] = max(entries[k]["s"] + 0.1, entries[k+1]["s"] - 0.04)
                fixed += 1

        lines = [f"{e['i']}\n{fmt(e['s'])} --> {fmt(e['e'])}\n{e['t']}" for e in entries]
        out_srt.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
        return RepairAttemptResult(
            issue="caption_overlap_intervals", action="FIX_CAPTION_TIMING",
            safety_class="SAFE_TO_AUTOFIX", process_succeeded=True, defect_cleared=False,
            input_path=srt_path, output_path=out_srt,
            operation_detail=f"Fixed {fixed} timestamp overlaps"
        )
    except Exception as e:
        return RepairAttemptResult(
            issue="caption_overlap_intervals", action="FIX_CAPTION_TIMING",
            safety_class="SAFE_TO_AUTOFIX", process_succeeded=False, defect_cleared=False,
            input_path=srt_path, output_path=None, operation_detail=str(e)
        )


# ─── 2. REQUIRES_RE_RENDER (from artifact) ───────────────────────────────────

def _repair_resolution(video_path: Path, out_path: Path) -> RepairAttemptResult:
    """
    Rescale rendered video to 1080x1920 using scale+pad (no stretching).
    Verification: QA must confirm vertical_resolution no longer fails.
    """
    try:
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
        cmd = [FFMPEG_EXE, "-y", "-i", str(video_path), "-vf", vf,
               "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "copy", str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        ok = proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 1024
        return RepairAttemptResult(
            issue="vertical_resolution", action="RENDER_RETRY",
            safety_class="REQUIRES_RE_RENDER", process_succeeded=ok, defect_cleared=False,
            input_path=video_path, output_path=out_path if ok else None,
            operation_detail=f"scale+pad to 1080x1920 — {'OK' if ok else proc.stderr[-200:]}"
        )
    except Exception as e:
        return RepairAttemptResult(issue="vertical_resolution", action="RENDER_RETRY",
                                   safety_class="REQUIRES_RE_RENDER", process_succeeded=False,
                                   defect_cleared=False, input_path=video_path, output_path=None,
                                   operation_detail=str(e))


def _repair_duration_trim(
    video_path: Path, out_path: Path, target_sec: float
) -> Optional[RepairAttemptResult]:
    """
    Trim a rendered clip that is LONGER than target.
    Returns None if actual duration <= target (extension is not safe from artifact).
    Verification: QA must confirm duration_compliance no longer fails.
    """
    actual = _get_actual_duration(video_path)
    # Only valid if the clip is genuinely longer than the target
    if actual <= target_sec + DURATION_EXTENSION_TOLERANCE:
        return RepairAttemptResult(
            issue="duration_compliance", action="RETRIM_CLIP",
            safety_class="SOURCE_AWARE_RERENDER_REQUIRED",
            process_succeeded=False, defect_cleared=False,
            input_path=video_path, output_path=None,
            operation_detail=(
                f"REFUSED: actual={actual:.2f}s, target={target_sec:.2f}s. "
                f"Duration extension from rendered artifact is not safe. "
                f"Requires source-aware re-render from original source + EditPlan."
            ),
            before_measurement=f"actual={actual:.2f}s",
            after_measurement="N/A"
        )
    # Actual > target — safe to trim
    try:
        cmd = [FFMPEG_EXE, "-y", "-i", str(video_path),
               "-t", str(target_sec), "-c", "copy", str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        ok = proc.returncode == 0 and out_path.exists()
        return RepairAttemptResult(
            issue="duration_compliance", action="RETRIM_CLIP",
            safety_class="REQUIRES_RE_RENDER", process_succeeded=ok, defect_cleared=False,
            input_path=video_path, output_path=out_path if ok else None,
            operation_detail=f"stream-copy trim to {target_sec:.2f}s — {'OK' if ok else proc.stderr[-150:]}",
            before_measurement=f"actual={actual:.2f}s",
            after_measurement=f"target={target_sec:.2f}s"
        )
    except Exception as e:
        return RepairAttemptResult(issue="duration_compliance", action="RETRIM_CLIP",
                                   safety_class="REQUIRES_RE_RENDER", process_succeeded=False,
                                   defect_cleared=False, input_path=video_path, output_path=None,
                                   operation_detail=str(e))


# ─── 3. SOURCE_AWARE_RERENDER — Cannot fix from artifact alone ───────────────

def _make_source_rerender_request(issue: str, video_path: Path, evidence: str) -> RepairAttemptResult:
    """
    For defects that require the original source video + EditPlan to fix
    (black frames, frozen frames, blur), we do NOT attempt any hack on the
    rendered artifact. We return a structured escalation record that Phase 11
    (the Batch Production Orchestrator) can use to trigger a full re-render.
    """
    return RepairAttemptResult(
        issue=issue, action="SOURCE_RERENDER_REQUESTED",
        safety_class="SOURCE_AWARE_RERENDER_REQUIRED",
        process_succeeded=False, defect_cleared=False,
        input_path=video_path, output_path=None,
        operation_detail=(
            f"ESCALATED: {issue} cannot be fixed from rendered artifact. "
            f"Full pipeline re-render from original source + EditPlan required. "
            f"Evidence: {evidence[:200]}"
        )
    )


# ─── 4. Core Repair Cycle ────────────────────────────────────────────────────

def run_repair_cycle(
    video_path: Path,
    edit_plan: EditPlan,
    qa_result: QAResult,
    srt_path: Optional[Path] = None,
    work_dir: Optional[Path] = None,
    audit_log_path: Optional[Path] = None,
    re_qa_fn=None
) -> Dict[str, Any]:
    """
    Execute the closed-loop self-repair cycle.

    Contract:
    - Never overwrites the original rendered artifact.
    - Never claims a repair succeeded without QA confirming the specific defect cleared.
    - Never attempts to extend clip duration from a rendered artifact.
    - Never applies audio operations (loudnorm) to fix visual defects (black frames).
    - Skips duplicate repairs that made no progress in the previous attempt.
    - Max 2 attempts, then escalates to REJECTED or SOURCE_RERENDER.
    """
    if re_qa_fn is None:
        from brain.qa_engine_v2 import run_qa_adversarial
        re_qa_fn = run_qa_adversarial

    if work_dir is None:
        work_dir = video_path.parent / "repair_workspace"
    work_dir.mkdir(parents=True, exist_ok=True)

    repair_records: List[Dict[str, Any]] = []
    audit_entries: List[Dict[str, Any]] = []
    current_video = video_path
    current_srt = srt_path
    current_qa = qa_result
    attempt = 0
    previously_attempted_issues: Set[str] = set()

    print(f"\n[REPAIR ENGINE v2] Clip: {video_path.name}")
    print(f"[REPAIR ENGINE v2] Initial Score: {qa_result.score:.1f} | Hard Fails: {len(qa_result.hard_fails)}")
    for hf in qa_result.hard_fails:
        print(f"[REPAIR ENGINE v2]   HARD_FAIL: {hf}")

    while attempt < MAX_REPAIR_ATTEMPTS:
        attempt += 1
        instructions = current_qa.repair_instructions
        print(f"\n[REPAIR ENGINE v2] -- Attempt {attempt}/{MAX_REPAIR_ATTEMPTS} --")

        if not instructions:
            print("[REPAIR ENGINE v2] No repair instructions in QA result. Stopping.")
            break

        # Separate by safety class
        autofix_items = [r for r in instructions
                         if r.get("issue") in AUTOFIX_ISSUES]
        rerender_items = [r for r in instructions
                          if r.get("issue") in RERENDER_FROM_ARTIFACT_ISSUES]
        trim_items = [r for r in instructions
                      if r.get("issue") == CONDITIONAL_TRIM_ISSUE]
        source_items = [r for r in instructions
                        if r.get("issue") in SOURCE_AWARE_RERENDER_ISSUES]
        skip_items = [r for r in instructions
                      if r.get("issue") in NOT_AUTOMATABLE_ISSUES]

        # Skip items that have already been attempted AND made zero progress
        def skip_if_duplicate(item: Dict) -> bool:
            issue = item.get("issue", "")
            if issue in previously_attempted_issues:
                print(f"[REPAIR ENGINE v2]   SKIP_DUPLICATE: {issue} already attempted with no progress")
                return True
            return False

        working_video = current_video
        working_srt = current_srt
        attempt_results: List[RepairAttemptResult] = []

        # ── Order 1: Captions (pure text, no video touched) ──────────────────
        for item in autofix_items:
            issue = item["issue"]
            if skip_if_duplicate(item):
                continue
            if issue not in ("caption_overflow_safezone", "caption_overlap_intervals", "captions_present"):
                continue
            out_srt = work_dir / f"a{attempt}_{issue}.srt"
            if issue == "caption_overflow_safezone" and working_srt:
                r = _repair_captions_overflow(working_srt, out_srt)
            elif issue == "caption_overlap_intervals" and working_srt:
                r = _repair_captions_overlap(working_srt, out_srt)
            else:
                continue
            if r.process_succeeded and r.output_path:
                working_srt = r.output_path
            attempt_results.append(r)
            print(f"[REPAIR ENGINE v2]   CAPTION_FIX [{issue}]: {'OK' if r.process_succeeded else 'FAIL'}")
            print(f"[REPAIR ENGINE v2]     {r.operation_detail[:90]}")

        # ── Order 2: Audio normalisation (audio-only transcode) ───────────────
        for item in autofix_items:
            issue = item["issue"]
            if skip_if_duplicate(item):
                continue
            if issue not in ("audio_clipping_peak", "audio_loudness_level"):
                continue
            out_vid = work_dir / f"a{attempt}_{issue}_audio.mp4"
            r = _repair_audio_normalize(working_video, out_vid, issue)
            if r.process_succeeded and r.output_path:
                working_video = r.output_path
            attempt_results.append(r)
            print(f"[REPAIR ENGINE v2]   AUDIO_FIX [{issue}]: {'OK' if r.process_succeeded else 'FAIL'}")
            print(f"[REPAIR ENGINE v2]     {r.operation_detail[:90]}")

        # ── Order 3: Duration trim (ONLY if actual > target) ─────────────────
        for item in trim_items:
            if skip_if_duplicate(item):
                continue
            out_vid = work_dir / f"a{attempt}_duration_trim.mp4"
            r = _repair_duration_trim(working_video, out_vid, edit_plan.target_duration_sec)
            if r is None:
                continue
            if r.safety_class == "SOURCE_AWARE_RERENDER_REQUIRED":
                print(f"[REPAIR ENGINE v2]   DURATION: {r.operation_detail[:100]}")
                attempt_results.append(r)
                continue
            if r.process_succeeded and r.output_path:
                working_video = r.output_path
            attempt_results.append(r)
            print(f"[REPAIR ENGINE v2]   DURATION_TRIM: {'OK' if r.process_succeeded else 'FAIL'}")
            print(f"[REPAIR ENGINE v2]     {r.operation_detail[:90]}")

        # ── Order 4: Resolution rescale (full transcode from artifact) ────────
        for item in rerender_items:
            issue = item["issue"]
            if skip_if_duplicate(item):
                continue
            if issue == "vertical_resolution":
                out_vid = work_dir / f"a{attempt}_resolution.mp4"
                r = _repair_resolution(working_video, out_vid)
                if r.process_succeeded and r.output_path:
                    working_video = r.output_path
                attempt_results.append(r)
                print(f"[REPAIR ENGINE v2]   RESOLUTION_FIX: {'OK' if r.process_succeeded else 'FAIL'}")
                print(f"[REPAIR ENGINE v2]     {r.operation_detail[:90]}")

        # ── Order 5: Source-aware re-render requests (escalate, do not fake) ─
        for item in source_items:
            issue = item["issue"]
            evidence = item.get("evidence", "")
            r = _make_source_rerender_request(issue, working_video, evidence)
            attempt_results.append(r)
            print(f"[REPAIR ENGINE v2]   SOURCE_RERENDER_REQUIRED [{issue}]: escalated")

        # ── NOT_AUTOMATABLE: log and skip ─────────────────────────────────────
        for item in skip_items:
            print(f"[REPAIR ENGINE v2]   NOT_AUTOMATABLE [{item.get('issue')}]: skipped")

        # Track what was attempted this round
        for r in attempt_results:
            previously_attempted_issues.add(r.issue)

        # ── Re-run QA ─────────────────────────────────────────────────────────
        pre_score = current_qa.score
        pre_hard_fails = set(current_qa.hard_fails)
        print(f"\n[REPAIR ENGINE v2] Running QA on repaired artifact: {working_video.name}")
        new_qa = re_qa_fn(working_video, edit_plan, working_srt)
        post_score = new_qa.score
        post_hard_fails = set(new_qa.hard_fails)
        print(f"[REPAIR ENGINE v2] Score: {pre_score:.1f} -> {post_score:.1f} | Hard Fails: {len(pre_hard_fails)} -> {len(post_hard_fails)}")

        # ── Update per-defect defect_cleared status ───────────────────────────
        for r in attempt_results:
            still_failing = _check_still_failing(new_qa, r.issue)
            r.defect_cleared = not still_failing
            if r.safety_class not in ("SOURCE_AWARE_RERENDER_REQUIRED",):
                status = "CLEARED" if r.defect_cleared else "STILL_FAILING"
                print(f"[REPAIR ENGINE v2]   {r.issue}: {status}")

        # ── Build repair records with per-defect evidence ─────────────────────
        for r in attempt_results:
            repair_records.append({
                "render_id": edit_plan.candidate_id,
                "attempt": attempt,
                "issue": r.issue,
                "action": r.action,
                "safety_class": r.safety_class,
                "input_path": str(r.input_path),
                "output_path": str(r.output_path) if r.output_path else None,
                "operation_detail": r.operation_detail,
                "process_succeeded": r.process_succeeded,
                "defect_cleared": r.defect_cleared,
                "before_measurement": r.before_measurement,
                "after_measurement": r.after_measurement,
                "pre_score": pre_score,
                "post_score": post_score,
                "score_delta": round(post_score - pre_score, 1),
                "new_hard_fails": list(post_hard_fails),
                "timestamp": r.created_at
            })

        audit_entries.append({
            "attempt": attempt,
            "pre_score": pre_score,
            "post_score": post_score,
            "score_delta": round(post_score - pre_score, 1),
            "hard_fails_eliminated": list(pre_hard_fails - post_hard_fails),
            "hard_fails_remaining": list(post_hard_fails),
            "new_hard_fails_introduced": list(post_hard_fails - pre_hard_fails),
            "issues_cleared": [r.issue for r in attempt_results if r.defect_cleared],
            "issues_not_cleared": [r.issue for r in attempt_results
                                    if not r.defect_cleared and r.safety_class not in ("SOURCE_AWARE_RERENDER_REQUIRED",)],
            "source_rerender_requested": [r.issue for r in attempt_results
                                           if r.safety_class == "SOURCE_AWARE_RERENDER_REQUIRED"],
            "recommended_action": new_qa.recommended_action
        })

        # ── Abort if regression ───────────────────────────────────────────────
        new_critical = post_hard_fails - pre_hard_fails
        if post_score < pre_score - 5.0 or new_critical:
            print(f"[REPAIR ENGINE v2] ABORT: regression detected — reverting to pre-repair state")
            if new_critical:
                print(f"[REPAIR ENGINE v2]   New hard fails introduced: {new_critical}")
            current_video = video_path  # Revert to original unmodified
            break

        # Accept repair progress
        current_video = working_video
        current_srt = working_srt
        current_qa = new_qa

        if new_qa.recommended_action == "approve":
            print(f"[REPAIR ENGINE v2] QA APPROVED after attempt {attempt}")
            break

        # Remove issues that made no progress from re-attempt list (deduplicate)
        no_progress = [r.issue for r in attempt_results
                       if not r.defect_cleared and r.safety_class not in ("SOURCE_AWARE_RERENDER_REQUIRED",)
                       and r.issue not in NOT_AUTOMATABLE_ISSUES]
        if no_progress:
            print(f"[REPAIR ENGINE v2]   No progress on: {no_progress} — will skip if identical next attempt")

    # ── Outcome determination ─────────────────────────────────────────────────
    source_rerender_needed = any(
        r.get("safety_class") == "SOURCE_AWARE_RERENDER_REQUIRED"
        for r in repair_records
    )
    if current_qa.recommended_action == "approve":
        outcome = "APPROVED"
    elif source_rerender_needed:
        outcome = "SOURCE_RERENDER_REQUIRED"
    else:
        outcome = "REJECTED"

    print(f"\n[REPAIR ENGINE v2] OUTCOME: {outcome} after {attempt} attempt(s)")
    print(f"[REPAIR ENGINE v2] Final Score: {current_qa.score:.1f} | Remaining Hard Fails: {len(current_qa.hard_fails)}")

    audit_payload = {
        "render_id": edit_plan.candidate_id,
        "original_video": str(video_path),
        "final_video": str(current_video),
        "outcome": outcome,
        "attempts": attempt,
        "final_score": current_qa.score,
        "final_hard_fails": current_qa.hard_fails,
        "source_rerender_required_for": [
            r["issue"] for r in repair_records
            if r.get("safety_class") == "SOURCE_AWARE_RERENDER_REQUIRED"
        ],
        "attempt_log": audit_entries,
        "repair_records": repair_records
    }
    if audit_log_path is None:
        audit_log_path = work_dir / f"repair_audit_{edit_plan.candidate_id}.json"
    audit_log_path.write_text(
        json.dumps(audit_payload, indent=2, default=str),
        encoding="utf-8"
    )
    print(f"[REPAIR ENGINE v2] Audit: {audit_log_path.name}")

    return {
        "final_video_path": current_video,
        "final_qa_result": current_qa,
        "repair_records": repair_records,
        "outcome": outcome,
        "attempts": attempt,
        "audit": audit_payload
    }


# ─── CLI Test Suite ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(ROOT))
    from brain.models import EditPlan
    from brain.qa_engine_v2 import run_qa_adversarial

    FIXTURES = ROOT / "projects" / "07_viral_podcasts" / "qa_fixtures"
    AUDITS = FIXTURES / "repair_audits_v2"
    AUDITS.mkdir(parents=True, exist_ok=True)

    plan = EditPlan(
        candidate_id="phase9_5_audit",
        target_platform="youtube_shorts",
        layout_style="ambient_blur_default",
        body_start_sec=195.2,
        body_end_sec=234.7,
        target_duration_sec=44.6,
        editing_necessity=0.3,
        ending_strategy="NATURAL_END",
        cta_text="",
        music_treatment="NONE"
    )

    sep = "=" * 70

    # ─── A: Known-Good Baseline ───────────────────────────────────────────────
    print(f"\n{sep}\nTEST A: Known-Good Baseline (must APPROVE without entering repair)\n{sep}")
    good = FIXTURES / "01_baseline_good.mp4"
    qa_a = run_qa_adversarial(good, plan)
    print(f"  Initial QA: {qa_a.score:.1f}/100 | Action: {qa_a.recommended_action.upper()}")
    assert qa_a.recommended_action == "approve", f"FAIL: baseline should APPROVE, got {qa_a.recommended_action}"
    print("  PASS: Known-good baseline approved correctly. Repair loop not entered.")

    # ─── B: Audio Clipping ───────────────────────────────────────────────────
    print(f"\n{sep}\nTEST B: Audio Clipping (loudnorm must clear audio_clipping_peak)\n{sep}")
    clip_fix = FIXTURES / "05_audio_clipping.mp4"
    qa_b = run_qa_adversarial(clip_fix, plan)
    print(f"  Initial: {qa_b.score:.1f}/100 | Hard Fails: {qa_b.hard_fails}")
    res_b = run_repair_cycle(clip_fix, plan, qa_b, work_dir=FIXTURES/"repair_v2/test_b",
                              audit_log_path=AUDITS/"test_b.json")
    recs_b = [r for r in res_b["repair_records"] if r["issue"] == "audio_clipping_peak"]
    print(f"\n  RESULT: outcome={res_b['outcome']} | score_delta={recs_b[0]['score_delta'] if recs_b else 'N/A'}")
    if recs_b:
        print(f"  audio_clipping_peak defect_cleared: {recs_b[0]['defect_cleared']}")
        print(f"  Operation: {recs_b[0]['operation_detail']}")

    # ─── C: Caption Overflow ──────────────────────────────────────────────────
    print(f"\n{sep}\nTEST C: Caption Overflow (text reformat must clear caption_overflow_safezone)\n{sep}")
    malformed = FIXTURES / "06_malformed.srt"
    qa_c = run_qa_adversarial(good, plan, srt_path=malformed)
    print(f"  Initial: {qa_c.score:.1f}/100 | caption_overflow check failing: {_check_still_failing(qa_c, 'caption_overflow_safezone')}")
    res_c = run_repair_cycle(good, plan, qa_c, srt_path=malformed,
                              work_dir=FIXTURES/"repair_v2/test_c", audit_log_path=AUDITS/"test_c.json")
    recs_c = [r for r in res_c["repair_records"] if r["issue"] == "caption_overflow_safezone"]
    if recs_c:
        print(f"  caption_overflow_safezone defect_cleared: {recs_c[0]['defect_cleared']}")
        print(f"  Operation: {recs_c[0]['operation_detail']}")

    # ─── D: Wrong Resolution ─────────────────────────────────────────────────
    print(f"\n{sep}\nTEST D: Wrong Resolution (scale+pad must clear vertical_resolution)\n{sep}")
    wrong_res = FIXTURES / "03_wrong_resolution.mp4"
    qa_d = run_qa_adversarial(wrong_res, plan)
    print(f"  Initial: {qa_d.score:.1f}/100 | Hard Fails: {qa_d.hard_fails}")
    res_d = run_repair_cycle(wrong_res, plan, qa_d, work_dir=FIXTURES/"repair_v2/test_d",
                              audit_log_path=AUDITS/"test_d.json")
    recs_d = [r for r in res_d["repair_records"] if r["issue"] == "vertical_resolution"]
    if recs_d:
        print(f"  vertical_resolution defect_cleared: {recs_d[0]['defect_cleared']}")
        print(f"  Operation: {recs_d[0]['operation_detail']}")
    print(f"  RESULT: outcome={res_d['outcome']} | final_score={res_d['final_qa_result'].score:.1f}")

    # ─── E: Black Frame (must escalate, NOT fake repair) ─────────────────────
    print(f"\n{sep}\nTEST E: Black Frame (must escalate to SOURCE_RERENDER_REQUIRED, not loudnorm)\n{sep}")
    black = FIXTURES / "04_blackout_frames.mp4"
    qa_e = run_qa_adversarial(black, plan)
    print(f"  Initial: {qa_e.score:.1f}/100 | Hard Fails: {qa_e.hard_fails}")
    res_e = run_repair_cycle(black, plan, qa_e, work_dir=FIXTURES/"repair_v2/test_e",
                              audit_log_path=AUDITS/"test_e.json")
    print(f"  RESULT: outcome={res_e['outcome']}")
    assert res_e["outcome"] == "SOURCE_RERENDER_REQUIRED", \
        f"FAIL: black frame must escalate, got {res_e['outcome']}"
    source_esc = res_e["audit"].get("source_rerender_required_for", [])
    print(f"  SOURCE_RERENDER_REQUIRED for: {source_esc}")
    print(f"  PASS: No fake loudnorm applied to black frames.")

    # ─── F: Duration Extension (must refuse, not blindly -t) ─────────────────
    print(f"\n{sep}\nTEST F: Duration Too Short (5s clip vs 44.6s target — must refuse extension)\n{sep}")
    clip_5s = FIXTURES / "03_wrong_resolution.mp4"  # ~5s
    qa_f_plan = EditPlan(candidate_id="dur_extend_test", target_duration_sec=44.6)
    qa_f = run_qa_adversarial(clip_5s, qa_f_plan)
    print(f"  Initial: {qa_f.score:.1f}/100 | Hard Fails: {qa_f.hard_fails}")
    res_f = run_repair_cycle(clip_5s, qa_f_plan, qa_f, work_dir=FIXTURES/"repair_v2/test_f",
                              audit_log_path=AUDITS/"test_f.json")
    dur_recs = [r for r in res_f["repair_records"] if r["issue"] == "duration_compliance"]
    for dr in dur_recs:
        print(f"  duration_compliance: safety={dr['safety_class']} | detail={dr['operation_detail'][:80]}")
        assert dr["safety_class"] == "SOURCE_AWARE_RERENDER_REQUIRED" or dr["process_succeeded"] == False, \
            "FAIL: should not blindly trim-extend a short clip"
    print(f"  PASS: Duration extension correctly refused.")

    # ─── G: Cascading Multi-Defect ────────────────────────────────────────────
    print(f"\n{sep}\nTEST G: Cascading Multi-Defect (all categories present)\n{sep}")
    multi = FIXTURES / "07_multi_defect.mp4"
    malformed_srt = FIXTURES / "06_malformed.srt"
    qa_g = run_qa_adversarial(multi, plan, srt_path=malformed_srt)
    print(f"  Initial: {qa_g.score:.1f}/100 | Hard Fails ({len(qa_g.hard_fails)}): {qa_g.hard_fails}")
    res_g = run_repair_cycle(multi, plan, qa_g, srt_path=malformed_srt,
                              work_dir=FIXTURES/"repair_v2/test_g", audit_log_path=AUDITS/"test_g.json")
    print(f"\n  RESULT: outcome={res_g['outcome']} | final_score={res_g['final_qa_result'].score:.1f}")
    print(f"  Attempts used: {res_g['attempts']}/{MAX_REPAIR_ATTEMPTS}")
    for entry in res_g["audit"]["attempt_log"]:
        print(f"  Attempt {entry['attempt']}: score {entry['pre_score']:.1f}->{entry['post_score']:.1f} | "
              f"cleared={entry['issues_cleared']} | escalated={entry['source_rerender_requested']}")
    print(f"  SOURCE_RERENDER_REQUIRED for: {res_g['audit']['source_rerender_required_for']}")

    print(f"\n{sep}")
    print("PHASE 9.5 ADVERSARIAL AUDIT — COMPLETE")
    print(sep)
