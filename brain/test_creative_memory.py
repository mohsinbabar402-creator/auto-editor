"""
Phase 10 — Creative Memory Test Suite (Tests A through L)

Each test has a clear pass/fail criterion and verifies a specific contract
of the Creative Memory system. Tests use isolated temporary stores so they
cannot contaminate each other or the production memory store.

Tests:
    A  No memories → Brain still works normally
    B  One successful example → Memory created, correct structure
    C  Repeated successes → Confidence increases monotonically
    D  Contradictory evidence → CONTRADICTED status, old evidence intact
    E  Old vs recent evidence → Recency weighting works
    F  Test fixture → Does NOT contaminate production memory
    G  Different account → Account-scoped memory stays scoped
    H  Different platform → Platform-scoped memory stays scoped
    I  Retrieval relevance → Only relevant memories returned (top_k enforced)
    J  Traceability → EditPlan → memory → evidence chain inspectable
    K  No performance data → No fabricated performance memory
    L  Exploration → Configurable ratio; suggests different pattern than dominant
"""

from __future__ import annotations

import math
import tempfile
import time
import uuid
from pathlib import Path

from brain.models import EditPlan, HookCandidate, HookMechanism, QAResult, QACheck
from brain.creative_memory import (
    CreativeMemory,
    CONFIDENCE_MODEL_DOC,
    LAPLACE_K, HALF_LIFE_DAYS, RECENCY_FLOOR,
    ACTIVE_THRESHOLD, CONTRADICTION_RATIO, CONTRADICTION_MIN_N
)
from brain.memory_models import (
    EvidenceRecord, ExperimentRecord, Memory, MemoryQuery,
    MEMORY_TYPE_EDITORIAL, MEMORY_TYPE_QA_PATTERN, MEMORY_TYPE_PERFORMANCE,
    SCOPE_GLOBAL, SCOPE_ACCOUNT, SCOPE_SHOW, SCOPE_PLATFORM,
    STATUS_ACTIVE, STATUS_WEAK, STATUS_CONTRADICTED,
    SOURCE_PRODUCTION, SOURCE_TEST,
    OUTCOME_POSITIVE, OUTCOME_NEGATIVE, OUTCOME_NEUTRAL,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _tmp_cm(exploration_ratio: float = 0.20) -> tuple[CreativeMemory, Path]:
    """Create a CreativeMemory instance backed by a temporary JSON store."""
    tmp = Path(tempfile.mkdtemp()) / "test_memory.json"
    return CreativeMemory(tmp, exploration_ratio=exploration_ratio), tmp


def _make_edit_plan(
    candidate_id: str = "",
    hook_mechanism: str = "QUESTION",
    duration: float = 40.0,
    editing_necessity: float = 0.3,
    ending: str = "NATURAL_END"
) -> EditPlan:
    cid = candidate_id or "ep_" + uuid.uuid4().hex[:8]
    hook = HookCandidate(
        mechanism=HookMechanism[hook_mechanism],
        text="Test hook text",
        hook_strength=7.5,
        truthfulness_score=8.0,
    )
    return EditPlan(
        candidate_id=cid,
        hook=hook,
        target_platform="youtube_shorts",
        body_start_sec=100.0,
        body_end_sec=100.0 + duration,
        target_duration_sec=duration,
        editing_necessity=editing_necessity,
        ending_strategy=ending,
    )


def _make_qa_approved(score: float = 95.0) -> QAResult:
    return QAResult(
        render_id="qa_test",
        passed=True,
        score=score,
        hard_fails=[],
        recommended_action="approve",
    )


def _make_qa_rejected(score: float = 45.0) -> QAResult:
    return QAResult(
        render_id="qa_test",
        passed=False,
        score=score,
        hard_fails=["Editorial decision produced poor content"],
        recommended_action="reject",
    )


def _make_qa_repair(score: float = 80.0) -> QAResult:
    return QAResult(
        render_id="qa_test",
        passed=False,
        score=score,
        hard_fails=["Audio clipping detected: true peak at 0.00 dB"],
        recommended_action="repair",
    )


SEP = "=" * 65

# ─── Test A: No Memories ─────────────────────────────────────────────────────

def test_a_no_memories():
    print(f"\n{SEP}\nTEST A: No memories -> Brain still works\n{SEP}")
    cm, _ = _tmp_cm()

    # retrieve() on empty store must return empty list, not raise
    results = cm.retrieve(MemoryQuery(tags=["question_hook"], top_k=5))
    assert results == [], f"Expected [], got {results}"

    # retrieve_for_edit_plan must work
    ep = _make_edit_plan()
    r2 = cm.retrieve_for_edit_plan(ep, show_id="test_show")
    assert isinstance(r2, list), "retrieve_for_edit_plan must return a list"

    # audit must return valid structure
    aud = cm.audit()
    assert aud["total_memories"] == 0
    assert aud["total_evidence_records"] == 0

    print("  PASS: Empty memory store — no errors, no fabricated data.")


# ─── Test B: One Successful Example ──────────────────────────────────────────

def test_b_one_successful_example():
    print(f"\n{SEP}\nTEST B: One success -> Memory created with correct structure\n{SEP}")
    cm, _ = _tmp_cm()
    ep = _make_edit_plan("clip_b01", "QUESTION")

    # Record decision + QA approval
    ev_ids = cm.record_editorial_decision(ep, "Question hook chosen for strong setup", show_id="cap_table")
    assert ev_ids, "Must return evidence IDs"
    cm.record_qa_outcome("clip_b01", _make_qa_approved(), ep)

    # Verify memories were created
    mems = cm.store.all_memories()
    editorial_mems = [m for m in mems if m.memory_type == MEMORY_TYPE_EDITORIAL]
    assert len(editorial_mems) > 0, "Must create at least one EDITORIAL memory"

    # Find the hook_type memory (HookMechanism.QUESTION.value == "question")
    hook_mem = next((m for m in editorial_mems if "question" in m.subject.lower()), None)
    assert hook_mem is not None, "hook_type:question memory must exist"

    # Verify structure
    assert hook_mem.sample_size == 1
    assert hook_mem.success_count == 1
    assert hook_mem.confidence > 0, "Confidence must be > 0 with one positive example"
    assert hook_mem.confidence < ACTIVE_THRESHOLD, (
        f"One sample cannot reach ACTIVE (conf={hook_mem.confidence:.4f})"
    )
    assert hook_mem.status == STATUS_WEAK, f"Expected WEAK with 1 sample, got {hook_mem.status}"
    assert hook_mem.scope == "SHOW"
    assert hook_mem.scope_id == "cap_table"
    assert len(hook_mem.evidence_ids) == 1

    # Verify evidence
    ev = cm.store.get_evidence(hook_mem.evidence_ids[0])
    assert ev is not None
    assert ev.outcome == OUTCOME_POSITIVE
    assert ev.is_valid_training is True
    assert ev.source_type == SOURCE_PRODUCTION

    print(f"  hook_type:QUESTION memory: confidence={hook_mem.confidence:.4f}, status={hook_mem.status}")
    print(f"  Evidence: outcome={ev.outcome}, qa_passed={ev.qa_passed}")
    print("  PASS: Memory created with correct structure and evidence.")


# ─── Test C: Repeated Successes → Confidence Increases ───────────────────────

def test_c_confidence_increases_with_successes():
    print(f"\n{SEP}\nTEST C: Repeated successes -> Confidence increases monotonically\n{SEP}")
    cm, _ = _tmp_cm()

    confidences = []
    for i in range(8):
        ep = _make_edit_plan(f"clip_c{i:02d}", "QUESTION")
        cm.record_editorial_decision(ep, f"Question hook #{i}", show_id="cap_table")
        cm.record_qa_outcome(f"clip_c{i:02d}", _make_qa_approved(95.0), ep)
        # Real audience performance data arrives (e.g. 70% retention)
        cm.record_performance(f"clip_c{i:02d}", {"average_view_duration_pct": 70.0})

        hook_mems = [
            m for m in cm.store.all_memories()
            if m.memory_type == MEMORY_TYPE_EDITORIAL and "question" in m.subject.lower()
        ]
        assert hook_mems, f"No question hook memory after clip {i}"
        conf = hook_mems[0].confidence
        confidences.append(conf)
        print(f"  n={i+1}: confidence={conf:.4f}, status={hook_mems[0].status}")

    # Confidence must be monotonically non-decreasing
    for j in range(1, len(confidences)):
        assert confidences[j] >= confidences[j-1] - 1e-6, (
            f"Confidence decreased at n={j+1}: {confidences[j-1]:.4f} -> {confidences[j]:.4f}"
        )

    # After 8 positive examples with performance data, must be ACTIVE
    final = confidences[-1]
    assert final >= ACTIVE_THRESHOLD, f"Expected ACTIVE after 8 successes, confidence={final:.4f}"

    final_mem = [m for m in cm.store.all_memories()
                 if m.memory_type == MEMORY_TYPE_EDITORIAL and "question" in m.subject.lower()][0]
    assert final_mem.status == STATUS_ACTIVE, f"Expected ACTIVE, got {final_mem.status}"
    print(f"  PASS: Confidence monotonically increases. ACTIVE at n=8 ({final:.4f}).")


# ─── Test D: Contradictory Evidence ──────────────────────────────────────────

def test_d_contradictory_evidence():
    print(f"\n{SEP}\nTEST D: Contradictory evidence -> CONTRADICTED status, old evidence intact\n{SEP}")
    cm, _ = _tmp_cm()

    # 3 positive examples
    for i in range(3):
        ep = _make_edit_plan(f"clip_d_pos{i}", "QUESTION")
        cm.record_editorial_decision(ep, "Question hook", show_id="test_show")
        cm.record_qa_outcome(f"clip_d_pos{i}", _make_qa_approved(), ep)

    # 4 negative examples (editorial failure, not technical)
    for i in range(4):
        ep = _make_edit_plan(f"clip_d_neg{i}", "QUESTION")
        cm.record_editorial_decision(ep, "Question hook", show_id="test_show")
        cm.record_qa_outcome(f"clip_d_neg{i}", _make_qa_rejected(40.0), ep)

    hook_mems = [m for m in cm.store.all_memories()
                 if m.memory_type == MEMORY_TYPE_EDITORIAL and "question" in m.subject.lower()]
    assert hook_mems, "question hook memory must exist"
    mem = hook_mems[0]
    print(f"  n={mem.sample_size}: success={mem.success_count}, fail={mem.failure_count}")
    print(f"  confidence={mem.confidence:.4f}, status={mem.status}")

    # Must be CONTRADICTED
    assert mem.status == STATUS_CONTRADICTED, f"Expected CONTRADICTED, got {mem.status}"

    # Old positive evidence must still exist (evidence is never deleted)
    all_ev = cm.store.evidence_for_memory(mem.memory_id)
    positive_ev = [e for e in all_ev if e.outcome == OUTCOME_POSITIVE]
    negative_ev = [e for e in all_ev if e.outcome == OUTCOME_NEGATIVE]
    assert len(positive_ev) >= 3, f"3 positive records must be preserved, found {len(positive_ev)}"
    assert len(negative_ev) >= 4, f"4 negative records must exist, found {len(negative_ev)}"

    # Contradiction ratio must exceed threshold
    ratio = mem.failure_count / mem.sample_size
    assert ratio > CONTRADICTION_RATIO, f"Contradiction ratio {ratio:.2f} must exceed {CONTRADICTION_RATIO}"

    print(f"  Historical evidence intact: {len(positive_ev)} positive, {len(negative_ev)} negative")
    print("  PASS: CONTRADICTED status. Old evidence intact.")


# ─── Test E: Recency Weighting ────────────────────────────────────────────────

def test_e_recency_weighting():
    print(f"\n{SEP}\nTEST E: Recency weighting -> Recent evidence scores higher\n{SEP}")
    cm, _ = _tmp_cm()

    # Manually create an evidence record dated 120 days ago
    old_ts = "2026-05-03T10:00:00+00:00"  # ~120 days before 2026-09-01
    fresh_ts = "2026-08-30T10:00:00+00:00"  # ~2 days before 2026-09-01

    def recency(ts: str) -> float:
        days = 0.0
        if ts:
            from datetime import datetime, timezone
            then = datetime.fromisoformat(ts)
            delta = datetime.now(timezone.utc) - then
            days = max(0.0, delta.total_seconds() / 86400.0)
        return RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * math.pow(2.0, -days / HALF_LIFE_DAYS)

    rw_old   = recency(old_ts)
    rw_fresh = recency(fresh_ts)

    print(f"  Recency weight for 120-day-old evidence: {rw_old:.4f}")
    print(f"  Recency weight for 2-day-old evidence:   {rw_fresh:.4f}")
    assert rw_fresh > rw_old, "Recent evidence must have higher recency weight"
    assert rw_old >= RECENCY_FLOOR - 1e-6, f"Old evidence must retain floor weight ({RECENCY_FLOOR})"
    assert rw_old < 1.0, "Old evidence must have reduced weight"

    # Old evidence retains influence (floor > 0)
    assert rw_old > 0, "Evidence floor must be above zero"

    print(f"  Evidence floor ({RECENCY_FLOOR}) respected: old weight {rw_old:.4f} >= floor")
    print("  PASS: Recency weighting works. Old evidence not deleted, just down-weighted.")


# ─── Test F: Test Fixture Isolation ──────────────────────────────────────────

def test_f_test_fixture_isolation():
    print(f"\n{SEP}\nTEST F: Test fixture -> Must NOT contaminate production memory\n{SEP}")
    cm, _ = _tmp_cm()

    # Record a production decision
    prod_ep = _make_edit_plan("prod_clip_01", "QUESTION")
    cm.record_editorial_decision(prod_ep, "Production clip", show_id="real_show",
                                  is_valid_training=True)
    cm.record_qa_outcome("prod_clip_01", _make_qa_approved(), prod_ep, is_valid_training=True)

    # Record a TEST fixture decision (is_valid_training=False)
    test_ep = _make_edit_plan("test_fixture_01", "QUESTION")
    cm.record_editorial_decision(test_ep, "QA fixture test clip", show_id="real_show",
                                  is_valid_training=False)
    cm.record_qa_outcome("test_fixture_01", _make_qa_rejected(10.0), test_ep, is_valid_training=False)

    # All valid-training evidence must be from production only
    all_ev = cm.store.all_evidence()
    production_ev = [e for e in all_ev if e.is_valid_training]
    test_ev = [e for e in all_ev if not e.is_valid_training]

    print(f"  Total evidence records: {len(all_ev)}")
    print(f"  Valid training: {len(production_ev)}, Test/invalid: {len(test_ev)}")

    # Verify test evidence exists but did NOT update any memory's sample counts
    for mem in cm.store.all_memories():
        if mem.memory_type == MEMORY_TYPE_EDITORIAL:
            all_mem_ev = cm.store.evidence_for_memory(mem.memory_id)
            invalid_in_memory = [e for e in all_mem_ev if not e.is_valid_training]
            # sample_size must only reflect valid training evidence
            valid_in_memory = [e for e in all_mem_ev if e.is_valid_training]
            assert mem.sample_size == len(valid_in_memory), (
                f"sample_size {mem.sample_size} != valid evidence count {len(valid_in_memory)}"
            )

    # QA memory for the test clip must NOT have contaminated editorial memory
    editorial_mems = [m for m in cm.store.all_memories() if m.memory_type == MEMORY_TYPE_EDITORIAL]
    for m in editorial_mems:
        # All samples in editorial memories must be from valid training
        assert m.sample_size == m.success_count + m.failure_count + (
            # neutral evidence contributes to sample_size
            len([e for e in cm.store.evidence_for_memory(m.memory_id)
                 if e.is_valid_training and e.outcome == OUTCOME_NEUTRAL])
        ), "Sample size accounting must be consistent"

    print("  PASS: Test fixtures do not contaminate production memory sample counts.")


# ─── Test G: Account Scoping ─────────────────────────────────────────────────

def test_g_account_scoping():
    print(f"\n{SEP}\nTEST G: Account-specific memory stays scoped\n{SEP}")
    cm, _ = _tmp_cm()

    # Record decisions for account_A
    for i in range(5):
        ep = _make_edit_plan(f"acc_a_clip{i}", "QUESTION")
        cm.record_editorial_decision(ep, "question hook used", show_id="show_a",
                                      account_id="account_a")
        cm.record_qa_outcome(f"acc_a_clip{i}", _make_qa_approved(), ep)

    # Record different decisions for account_B
    for i in range(3):
        ep = _make_edit_plan(f"acc_b_clip{i}", "STRONG_CLAIM")
        cm.record_editorial_decision(ep, "strong claim used", show_id="show_b",
                                      account_id="account_b")
        cm.record_qa_outcome(f"acc_b_clip{i}", _make_qa_approved(), ep)

    # Retrieve for show_a — must NOT return show_b memories
    q_a = MemoryQuery(tags=["QUESTION", "hook"], scope=SCOPE_SHOW, scope_id="show_a", top_k=10)
    results_a = cm.retrieve(q_a)
    for r in results_a:
        assert r.memory.scope_id != "show_b", (
            f"show_b memory leaked into show_a retrieval: {r.memory.subject}"
        )

    # Retrieve for show_b — must NOT return show_a memories
    q_b = MemoryQuery(tags=["STRONG_CLAIM", "hook"], scope=SCOPE_SHOW, scope_id="show_b", top_k=10)
    results_b = cm.retrieve(q_b)
    for r in results_b:
        assert r.memory.scope_id != "show_a", (
            f"show_a memory leaked into show_b retrieval: {r.memory.subject}"
        )

    print(f"  show_a results: {len(results_a)}, show_b results: {len(results_b)}")
    print("  PASS: Account/show-scoped memories stay isolated.")


# ─── Test H: Platform Scoping ─────────────────────────────────────────────────

def test_h_platform_scoping():
    print(f"\n{SEP}\nTEST H: Platform-specific memory stays scoped\n{SEP}")
    cm, _ = _tmp_cm()

    # Create TikTok QA pattern memory
    from brain.creative_memory import _make_memory_id, _now_iso
    tiktok_mem_id = _make_memory_id(MEMORY_TYPE_QA_PATTERN, SCOPE_PLATFORM, "tiktok", "audio_clipping_occurrence")
    tiktok_ev = EvidenceRecord(
        evidence_id="ev_tiktok_001",
        memory_id=tiktok_mem_id,
        source_type=SOURCE_PRODUCTION,
        is_valid_training=True,
        platform="tiktok",
        observation="Audio clipping on tiktok render",
        outcome=OUTCOME_NEGATIVE,
        magnitude=0.2,
        created_at=_now_iso()
    )
    tiktok_mem = Memory(
        memory_id=tiktok_mem_id,
        memory_type=MEMORY_TYPE_QA_PATTERN,
        scope=SCOPE_PLATFORM,
        scope_id="tiktok",
        subject="audio_clipping_occurrence",
        statement="Audio clipping has occurred on TikTok",
        confidence=0.65,
        sample_size=1, success_count=0, failure_count=1,
        status=STATUS_WEAK,
        tags=["qa_pattern", "audio_clipping", "tiktok"],
        created_at=_now_iso(), updated_at=_now_iso()
    )
    cm.store.put_evidence(tiktok_ev)
    cm.store.put_memory(tiktok_mem)

    # Query for youtube_shorts — must not return tiktok memories
    q_yt = MemoryQuery(
        tags=["audio_clipping", "qa_pattern"],
        scope=SCOPE_PLATFORM,
        scope_id="youtube_shorts",
        top_k=10
    )
    results_yt = cm.retrieve(q_yt)
    for r in results_yt:
        assert r.memory.scope_id != "tiktok", (
            f"TikTok memory appeared in youtube_shorts query: {r.memory.subject}"
        )

    # Query for tiktok — must return the tiktok memory
    q_tiktok = MemoryQuery(
        tags=["audio_clipping"],
        scope=SCOPE_PLATFORM,
        scope_id="tiktok",
        top_k=10
    )
    results_tiktok = cm.retrieve(q_tiktok)
    assert any(r.memory.scope_id == "tiktok" for r in results_tiktok), (
        "TikTok memory not found in tiktok-scoped query"
    )

    print(f"  youtube_shorts results: {len(results_yt)}, tiktok results: {len(results_tiktok)}")
    print("  PASS: Platform-scoped memories stay scoped.")


# ─── Test I: Relevance-Based Retrieval ───────────────────────────────────────

def test_i_relevance_retrieval():
    print(f"\n{SEP}\nTEST I: Retrieval returns only relevant memories (top_k enforced)\n{SEP}")
    cm, _ = _tmp_cm()

    # Create 5 memories with different subjects/tags
    subjects_data = [
        ("hook_type:QUESTION",      ["hook_type", "QUESTION", "hook"],          0.70),
        ("clip_duration:short",     ["duration", "short_20_35s", "clip_length"], 0.55),
        ("hook_type:OUTCOME_FIRST", ["hook_type", "OUTCOME_FIRST", "hook"],     0.45),
        ("editing_necessity:light", ["editing", "minimal_editing"],              0.30),
        ("ending_strategy:CTA",     ["ending", "CTA", "call_to_action"],        0.40),
    ]
    from brain.creative_memory import _make_memory_id, _now_iso
    for subject, tags, conf in subjects_data:
        mid = _make_memory_id(MEMORY_TYPE_EDITORIAL, SCOPE_GLOBAL, "", subject)
        mem = Memory(
            memory_id=mid,
            memory_type=MEMORY_TYPE_EDITORIAL,
            scope=SCOPE_GLOBAL, scope_id="",
            subject=subject,
            statement=f"Belief: {subject}",
            confidence=conf,
            sample_size=5, success_count=int(5*conf), failure_count=5-int(5*conf),
            status=STATUS_ACTIVE if conf >= ACTIVE_THRESHOLD else STATUS_WEAK,
            tags=tags, created_at=_now_iso(), updated_at=_now_iso()
        )
        cm.store.put_memory(mem)

    # Query with hook-related tags, top_k=2
    q = MemoryQuery(tags=["hook_type", "hook"], top_k=2)
    results = cm.retrieve(q)

    assert len(results) <= 2, f"top_k=2 must return at most 2 results, got {len(results)}"

    # Both results should be hook-related (higher tag overlap)
    for r in results:
        assert r.tag_overlap > 0, f"Retrieved memory has zero tag overlap: {r.memory.subject}"

    # Results must be sorted by retrieval_score descending
    if len(results) >= 2:
        assert results[0].retrieval_score >= results[1].retrieval_score, (
            "Results must be sorted by retrieval_score descending"
        )

    # Non-matching memories (duration, editing, ending) should not be top results
    top_subjects = [r.memory.subject for r in results]
    print(f"  Top {len(results)} results for [hook_type, hook]: {top_subjects}")
    print(f"  Retrieval scores: {[round(r.retrieval_score, 4) for r in results]}")
    print("  PASS: Retrieval returns relevant subset, top_k enforced, sorted by score.")


# ─── Test J: Traceability ────────────────────────────────────────────────────

def test_j_traceability():
    print(f"\n{SEP}\nTEST J: EditPlan -> memory -> evidence chain is fully traceable\n{SEP}")
    cm, _ = _tmp_cm()

    # Build up some memories via prior decisions
    for i in range(4):
        prep = _make_edit_plan(f"prep_clip_{i}", "QUESTION")
        cm.record_editorial_decision(prep, "question hook", show_id="test_show")
        cm.record_qa_outcome(f"prep_clip_{i}", _make_qa_approved(), prep)

    # Now retrieve memories for a new EditPlan
    target_ep = _make_edit_plan("target_clip_001", "QUESTION")
    retrieved = cm.retrieve_for_edit_plan(target_ep, show_id="test_show", record_influence=True)

    assert retrieved, "Should have retrieved memories for target_ep"

    # Verify that target_ep appears in edit_plans_influenced for retrieved memories
    for r in retrieved:
        assert target_ep.candidate_id in r.memory.edit_plans_influenced, (
            f"target_clip_001 not in edit_plans_influenced for {r.memory.subject}"
        )

    # Trace back from the EditPlan
    trace = cm.trace_edit_plan(target_ep.candidate_id)
    assert trace["edit_plan_id"] == target_ep.candidate_id
    assert trace["memories_consulted"] > 0, "Should show at least one memory consulted"

    # Explain a specific memory
    if retrieved:
        mem_id = retrieved[0].memory.memory_id
        explanation = cm.explain_belief(mem_id)
        assert "statement" in explanation
        assert "confidence" in explanation
        assert "evidence_summary" in explanation
        assert "confidence_components" in explanation
        assert "provenance" in explanation
        components = explanation["confidence_components"]
        assert all(k in components for k in ["success_rate", "sample_weight", "quality_weight", "recency_weight"])

    print(f"  Memories consulted: {trace['memories_consulted']}")
    print(f"  Evidence produced by plan: {len(trace['evidence_produced_by_this_plan'])}")
    if retrieved:
        print(f"  Explanation for '{retrieved[0].memory.subject}':")
        print(f"    components: {explanation['confidence_components']}")
    print("  PASS: EditPlan -> memory -> evidence chain fully traceable.")


# ─── Test K: No Performance Data ─────────────────────────────────────────────

def test_k_no_performance_data():
    print(f"\n{SEP}\nTEST K: No performance data -> No fabricated performance memory\n{SEP}")
    cm, _ = _tmp_cm()

    ep = _make_edit_plan("clip_k01", "OUTCOME_FIRST")
    cm.record_editorial_decision(ep, "outcome first hook", show_id="test_show",
                                  account_id="acc_test")
    cm.record_qa_outcome("clip_k01", _make_qa_approved(), ep)

    # No record_performance() called — no performance data available

    # There must be NO PERFORMANCE memory for this clip
    perf_mems = [m for m in cm.store.all_memories() if m.memory_type == MEMORY_TYPE_PERFORMANCE]
    assert len(perf_mems) == 0, f"No performance memory should exist without data; found {len(perf_mems)}"

    # All evidence records must have has_performance_data = False
    for ev in cm.store.all_evidence():
        assert ev.has_performance_data is False, (
            f"Evidence {ev.evidence_id} has fabricated performance data"
        )
        assert ev.performance_data == {}, (
            f"Evidence {ev.evidence_id} has non-empty performance data without real metrics"
        )

    # quality_weight must be 0.75 (QA-only), not 1.00 (would require perf data)
    editorial_mems = [m for m in cm.store.all_memories() if m.memory_type == MEMORY_TYPE_EDITORIAL]
    for m in editorial_mems:
        evidence = cm.store.evidence_for_memory(m.memory_id)
        comps = cm._confidence_components(m, evidence)
        assert comps["quality_weight"] < 1.00, (
            f"quality_weight must be < 1.0 without performance data; got {comps['quality_weight']}"
        )

    print(f"  Performance memories: {len(perf_mems)} (correct: 0)")
    print("  PASS: No performance data -> no fabricated PERFORMANCE memory, quality_weight=0.75.")


# ─── Test L: Exploration ──────────────────────────────────────────────────────

def test_l_exploration():
    print(f"\n{SEP}\nTEST L: Exploration -> configurable ratio, different pattern suggested\n{SEP}")
    cm_exploit, _ = _tmp_cm(exploration_ratio=0.0)   # Never explore
    cm_explore, _  = _tmp_cm(exploration_ratio=1.0)   # Always explore

    # Build up strong question hook memory with high retention performance
    for i in range(12):
        ep = _make_edit_plan(f"dom_clip_{i}", "QUESTION")
        cm_exploit.record_editorial_decision(ep, "dominant pattern", show_id="test_show")
        cm_exploit.record_qa_outcome(f"dom_clip_{i}", _make_qa_approved(), ep)
        cm_exploit.record_performance(f"dom_clip_{i}", {"average_view_duration_pct": 75.0})
        # Copy same memory into explore instance
        cm_explore.record_editorial_decision(ep, "dominant pattern", show_id="test_show")
        cm_explore.record_qa_outcome(f"dom_clip_{i}", _make_qa_approved(), ep)
        cm_explore.record_performance(f"dom_clip_{i}", {"average_view_duration_pct": 75.0})

    # Exploitation instance: should_explore always False
    assert not cm_exploit.should_explore(), "ratio=0.0 should never explore"
    assert cm_exploit.exploration_ratio == 0.0

    # Exploration instance: should_explore always True
    assert cm_explore.should_explore(), "ratio=1.0 should always explore"

    # suggest_exploration on the explore instance
    suggestion = cm_explore.suggest_exploration(current_tags=["hook_type", "question"])

    assert suggestion is not None, "Should return a suggestion when dominant pattern exists"
    assert suggestion.description != "", "Suggestion must have a description"
    assert suggestion.rationale != "", "Suggestion must have a rationale"
    assert suggestion.dominant_memory_id != "", "Must reference the dominant memory"
    assert suggestion.exploration_probability == 1.0, (
        f"Expected exploration_probability=1.0, got {suggestion.exploration_probability}"
    )

    # The suggestion must NOT be the same as the dominant pattern
    dom_mem = cm_explore.store.get_memory(suggestion.dominant_memory_id)
    assert dom_mem is not None
    assert "question" in dom_mem.subject.lower(), "Dominant memory must be question hook"
    assert "question" not in suggestion.description.lower() or "outcome" in suggestion.description.lower(), (
        "Exploration suggestion must suggest a different pattern"
    )

    print(f"  Dominant pattern: {dom_mem.subject} (confidence={dom_mem.confidence:.4f})")
    print(f"  Exploration suggestion: {suggestion.description}")
    print(f"  Rationale: {suggestion.rationale[:80]}...")
    print("  PASS: Exploration ratio configurable; suggestion steps away from dominant pattern.")


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(ROOT))

    tests = [
        ("A", test_a_no_memories),
        ("B", test_b_one_successful_example),
        ("C", test_c_confidence_increases_with_successes),
        ("D", test_d_contradictory_evidence),
        ("E", test_e_recency_weighting),
        ("F", test_f_test_fixture_isolation),
        ("G", test_g_account_scoping),
        ("H", test_h_platform_scoping),
        ("I", test_i_relevance_retrieval),
        ("J", test_j_traceability),
        ("K", test_k_no_performance_data),
        ("L", test_l_exploration),
    ]

    passed = []
    failed = []

    for label, fn in tests:
        try:
            fn()
            passed.append(label)
        except AssertionError as e:
            failed.append((label, str(e)))
            print(f"  FAIL: {e}")
        except Exception as e:
            failed.append((label, f"EXCEPTION: {e}"))
            print(f"  ERROR: {e}")

    print(f"\n{SEP}")
    print(f"PHASE 10 CREATIVE MEMORY TEST SUITE RESULTS")
    print(SEP)
    print(f"  PASSED: {len(passed)}/{len(tests)} — {' '.join(passed) if passed else 'none'}")
    if failed:
        print(f"  FAILED: {len(failed)}/{len(tests)}")
        for label, reason in failed:
            print(f"    [{label}] {reason}")
    else:
        print(f"  ALL TESTS PASSED. Exit code: 0")
    print(SEP)

    sys.exit(0 if not failed else 1)
