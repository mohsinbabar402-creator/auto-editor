"""
Creative Intelligence Engine — Creative Memory (Phase 10)

PURPOSE:
    Evidence-driven belief system for the Autonomous Content Factory Brain.

    The Brain uses Creative Memory to:
      1. Record what it decided and WHY (editorial memory)
      2. Record what QA found, separately from creative outcomes (QA pattern memory)
      3. Record audience performance when available, never invented (performance memory)
      4. Retrieve the most RELEVANT past evidence before a new editorial decision
      5. Update beliefs when new evidence contradicts existing ones
      6. Suggest controlled exploration when dominant patterns should be challenged

FUNDAMENTAL PRINCIPLE:
    Memory is evidence. Memory is NOT truth.
    Every belief must trace to specific EvidenceRecords.
    Beliefs change when evidence changes.
    Old evidence is NEVER deleted when a belief is contradicted.

CONFIDENCE MODEL (Deterministic):
    See CONFIDENCE_MODEL_DOC constant for the full formula.

SAFETY:
    - Memory never overrides hard QA rules
    - Technical QA defects (black frames, clipping) are never interpreted as
      creative failures — they update QA_PATTERN memories ONLY
    - Test/benchmark/synthetic fixtures never contaminate production memory
    - No performance data is ever fabricated
    - Memory is advisory — the editorial layer makes all final decisions
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain.memory_models import (
    EvidenceRecord, ExperimentRecord, ExplorationSuggestion,
    Memory, MemoryQuery, MemoryRetrievalResult,
    MEMORY_TYPE_CONTENT, MEMORY_TYPE_EDITORIAL,
    MEMORY_TYPE_QA_PATTERN, MEMORY_TYPE_PERFORMANCE, MEMORY_TYPE_STRATEGY,
    SCOPE_GLOBAL, SCOPE_ACCOUNT, SCOPE_SHOW, SCOPE_PLATFORM, SCOPE_FORMAT,
    STATUS_ACTIVE, STATUS_WEAK, STATUS_CONTRADICTED, STATUS_SUPERSEDED, STATUS_RETIRED,
    SOURCE_PRODUCTION, SOURCE_TEST,
    OUTCOME_POSITIVE, OUTCOME_NEGATIVE, OUTCOME_NEUTRAL,
)
from brain.models import EditPlan, QAResult


# ─── Confidence Model ─────────────────────────────────────────────────────────

CONFIDENCE_MODEL_DOC = """
CREATIVE MEMORY — CONFIDENCE CALCULATION (Deterministic, Inspectable)
======================================================================

Formula:
    confidence = success_rate * sample_weight * quality_weight * recency_weight

All components are independently inspectable and deterministic.
Confidence is NEVER assigned by an LLM or random process.

1. success_rate = success_count / max(sample_size, 1)
   Range: [0.0, 1.0]
   Meaning: Proportion of evidence that supports the belief.

2. sample_weight = sample_size / (sample_size + LAPLACE_K)
   LAPLACE_K = 5
   Range: [0.0, 1.0)
   N=0 ->  0.00  (no evidence = no confidence ceiling)
   N=5 ->  0.50
   N=10 -> 0.67
   N=25 -> 0.83
   N=50 -> 0.91
   Prevents small-sample overconfidence (Laplace smoothing).

3. quality_weight
   = 1.00  if any evidence has real performance data (audience metrics)
   = 0.75  if evidence is QA-outcome-only (approved/rejected) — no audience data
   = 0.50  if all evidence is NEUTRAL (decision recorded, outcome not yet known)
   Real audience data is stronger evidence than technical QA pass/fail alone.

4. recency_weight = RECENCY_FLOOR + (1 - RECENCY_FLOOR) * 2^(-days / HALF_LIFE_DAYS)
   RECENCY_FLOOR = 0.30
   HALF_LIFE_DAYS = 60
   day=0   -> 1.00  (fresh evidence)
   day=60  -> 0.65  (one half-life)
   day=120 -> 0.47
   day=180 -> 0.39
   day=365 -> 0.32  (approaching floor, old evidence still counts)
   Old evidence remains relevant (floor=0.30) but recent evidence dominates.

Status Thresholds (applied after confidence is computed):
   confidence >= 0.60                          -> ACTIVE
   0.30 <= confidence < 0.60                   -> WEAK
   failure_count / sample_size > 0.50
     AND sample_size >= 3                      -> CONTRADICTED
   Manually set                                -> SUPERSEDED or RETIRED

Constants:
   LAPLACE_K        = 5
   HALF_LIFE_DAYS   = 60
   RECENCY_FLOOR    = 0.30
   ACTIVE_THRESHOLD = 0.60
   WEAK_THRESHOLD   = 0.30
   CONTRADICTION_RATIO   = 0.50
   CONTRADICTION_MIN_N   = 3
"""

LAPLACE_K           = 5
HALF_LIFE_DAYS      = 60
RECENCY_FLOOR       = 0.30
ACTIVE_THRESHOLD    = 0.60
WEAK_THRESHOLD      = 0.30
CONTRADICTION_RATIO = 0.50
CONTRADICTION_MIN_N = 3

# Exploration configuration
DEFAULT_EXPLORATION_RATIO = 0.20  # 20% of decisions may explore new patterns


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_since(iso_timestamp: str) -> float:
    """Return fractional days between now and an ISO timestamp. 0 if empty."""
    if not iso_timestamp:
        return 0.0
    try:
        then = datetime.fromisoformat(iso_timestamp)
        delta = datetime.now(timezone.utc) - then
        return max(0.0, delta.total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _make_memory_id(memory_type: str, scope: str, scope_id: str, subject: str) -> str:
    """
    Deterministic memory ID derived from type + scope + subject.
    The same belief in the same context always maps to the same memory,
    ensuring evidence accumulates in one place rather than fragmenting.
    """
    key = f"{memory_type}|{scope}|{scope_id}|{subject}"
    return "mem_" + hashlib.sha256(key.encode()).hexdigest()[:14]


def _make_evidence_id() -> str:
    """Unique ID for each observation — each evidence record is distinct."""
    return "ev_" + uuid.uuid4().hex[:14]


# ─── MemoryStore (Persistence) ────────────────────────────────────────────────

class MemoryStore:
    """
    JSON-backed persistence for Memory and EvidenceRecord objects.

    All data lives in a single JSON file with three top-level sections:
        memories, evidence, experiments

    The store is loaded once at init and saved explicitly after mutations.
    Evidence records are NEVER deleted.
    """

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self._memories: Dict[str, Memory] = {}
        self._evidence: Dict[str, EvidenceRecord] = {}
        self._experiments: Dict[str, ExperimentRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.store_path.exists():
            return
        try:
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            for mid, m in raw.get("memories", {}).items():
                self._memories[mid] = Memory(**{
                    k: v for k, v in m.items() if k in Memory.__dataclass_fields__
                })
            for eid, e in raw.get("evidence", {}).items():
                self._evidence[eid] = EvidenceRecord(**{
                    k: v for k, v in e.items() if k in EvidenceRecord.__dataclass_fields__
                })
            for xid, x in raw.get("experiments", {}).items():
                self._experiments[xid] = ExperimentRecord(**{
                    k: v for k, v in x.items() if k in ExperimentRecord.__dataclass_fields__
                })
        except Exception as ex:
            print(f"[MEMORY_STORE] Warning: could not load store: {ex}")

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "memories":    {mid: asdict(m) for mid, m in self._memories.items()},
            "evidence":    {eid: asdict(e) for eid, e in self._evidence.items()},
            "experiments": {xid: asdict(x) for xid, x in self._experiments.items()},
        }
        self.store_path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8"
        )

    def put_memory(self, m: Memory) -> None:
        self._memories[m.memory_id] = m

    def get_memory(self, mid: str) -> Optional[Memory]:
        return self._memories.get(mid)

    def all_memories(self) -> List[Memory]:
        return list(self._memories.values())

    def put_evidence(self, e: EvidenceRecord) -> None:
        self._evidence[e.evidence_id] = e

    def get_evidence(self, eid: str) -> Optional[EvidenceRecord]:
        return self._evidence.get(eid)

    def all_evidence(self) -> List[EvidenceRecord]:
        return list(self._evidence.values())

    def evidence_for_memory(self, memory_id: str) -> List[EvidenceRecord]:
        return [e for e in self._evidence.values() if e.memory_id == memory_id]

    def evidence_for_clip(self, clip_id: str) -> List[EvidenceRecord]:
        return [e for e in self._evidence.values() if e.clip_id == clip_id]

    def evidence_for_edit_plan(self, edit_plan_id: str) -> List[EvidenceRecord]:
        return [e for e in self._evidence.values() if e.edit_plan_id == edit_plan_id]

    def put_experiment(self, x: ExperimentRecord) -> None:
        self._experiments[x.experiment_id] = x

    def all_experiments(self) -> List[ExperimentRecord]:
        return list(self._experiments.values())


# ─── CreativeMemory ───────────────────────────────────────────────────────────

class CreativeMemory:
    """
    The Brain's evidence-driven belief system.

    Responsibilities:
        - Record what the Brain decided and why
        - Record QA outcomes, separated from creative conclusions
        - Record performance data when available (never invented)
        - Retrieve relevant past memories before new editorial decisions
        - Update beliefs when contradictory evidence accumulates
        - Suggest exploration when dominant patterns need to be challenged
        - Provide full auditability: memory -> evidence chain

    Prohibited behaviours:
        - Overriding QA hard rules
        - Interpreting technical defects as creative failures
        - Contaminating memory from test fixtures (is_valid_training=False)
        - Fabricating performance data
        - Silently modifying EditPlans
    """

    def __init__(
        self,
        store_path: Path,
        exploration_ratio: float = DEFAULT_EXPLORATION_RATIO
    ):
        self.store = MemoryStore(store_path)
        self.exploration_ratio = max(0.0, min(1.0, exploration_ratio))

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 1 — Recording
    # ──────────────────────────────────────────────────────────────────────────

    def record_editorial_decision(
        self,
        edit_plan: EditPlan,
        reasoning: str,
        account_id: str = "",
        show_id: str = "",
        platform: str = "youtube_shorts",
        is_valid_training: bool = True
    ) -> List[str]:
        """
        Record that the Brain made a set of editorial decisions for a clip.

        Creates EvidenceRecords and (if is_valid_training=True) EDITORIAL memories
        for each observable pattern in the EditPlan:
            - hook type used
            - clip duration range
            - editing necessity level
            - ending strategy

        Returns list of evidence_ids created.

        If is_valid_training=False (test fixture, debug), no production memory is
        created or contaminated. The evidence record is still stored for auditability
        but tagged SOURCE_TEST.
        """
        evidence_ids: List[str] = []
        now = _now_iso()

        # Extract patterns from EditPlan
        patterns = self._extract_edit_plan_patterns(edit_plan)

        for subject, observation_text, tags in patterns:
            # Determine scope: prefer SHOW scope if show_id given, else GLOBAL
            scope = SCOPE_SHOW if show_id else SCOPE_GLOBAL
            scope_id = show_id or ""

            memory_id = _make_memory_id(MEMORY_TYPE_EDITORIAL, scope, scope_id, subject)

            ev = EvidenceRecord(
                evidence_id=_make_evidence_id(),
                memory_id=memory_id,
                source_type=SOURCE_PRODUCTION if is_valid_training else SOURCE_TEST,
                is_valid_training=is_valid_training,
                clip_id=edit_plan.candidate_id,
                episode_id=getattr(edit_plan, "source_id", ""),
                account_id=account_id,
                platform=platform,
                edit_plan_id=edit_plan.candidate_id,
                observation=observation_text,
                outcome=OUTCOME_NEUTRAL,    # Outcome unknown until QA result arrives
                magnitude=0.5,
                qa_result_summary="",
                qa_passed=None,
                performance_data={},
                has_performance_data=False,
                created_at=now,
                notes=f"Reasoning: {reasoning[:200]}"
            )
            self.store.put_evidence(ev)
            evidence_ids.append(ev.evidence_id)

            if is_valid_training:
                # Create or update the Memory for this pattern
                mem = self._get_or_create_memory(
                    memory_id=memory_id,
                    memory_type=MEMORY_TYPE_EDITORIAL,
                    scope=scope,
                    scope_id=scope_id,
                    subject=subject,
                    statement=f"{subject} used for {show_id or 'content'} on {platform}",
                    tags=tags + [platform, show_id or "global"],
                    now=now
                )
                if edit_plan.candidate_id not in mem.source_ids:
                    mem.source_ids.append(edit_plan.candidate_id)
                if ev.evidence_id not in mem.evidence_ids:
                    mem.evidence_ids.append(ev.evidence_id)
                # Recompute (outcome is NEUTRAL, so this starts weak)
                self._recompute_and_save(mem)

        self.store.save()
        return evidence_ids

    def record_qa_outcome(
        self,
        clip_id: str,
        qa_result: QAResult,
        edit_plan: EditPlan,
        is_valid_training: bool = True
    ) -> None:
        """
        Update editorial EvidenceRecords for a clip based on QA outcome.

        EDITORIAL MEMORY RULE:
            QA APPROVED   → outcome = POSITIVE (editorial decision was viable)
            QA REPAIR     → outcome = NEUTRAL   (technical issue, not editorial fault)
            QA REJECTED   → outcome = NEGATIVE  (editorial or render decision failed)

        QA_PATTERN MEMORY:
            Technical defects (black frames, clipping, resolution) are recorded
            separately as QA_PATTERN memories and NEVER influence EDITORIAL beliefs.

        Test fixture evidence (is_valid_training=False) does not update any Memory.
        """
        if not is_valid_training:
            return

        now = _now_iso()

        # Determine editorial outcome from QA action
        if qa_result.recommended_action == "approve":
            editorial_outcome = OUTCOME_POSITIVE
        elif qa_result.recommended_action == "repair":
            # Technical issue — do not penalise editorial decision
            editorial_outcome = OUTCOME_NEUTRAL
        else:
            editorial_outcome = OUTCOME_NEGATIVE

        # Update editorial evidence records for this clip
        for ev in self.store.evidence_for_edit_plan(edit_plan.candidate_id):
            mem = self.store.get_memory(ev.memory_id)
            if mem and mem.memory_type == MEMORY_TYPE_EDITORIAL:
                ev.outcome = editorial_outcome
                ev.qa_result_summary = (
                    f"{qa_result.recommended_action.upper()} "
                    f"{qa_result.score:.1f}/100 | "
                    f"hard_fails={len(qa_result.hard_fails)}"
                )
                ev.qa_passed = qa_result.passed
                ev.magnitude = qa_result.score / 100.0
                self.store.put_evidence(ev)
                self._recompute_and_save(mem)

        # Record QA_PATTERN memories for any technical defects detected
        # These are SEPARATE from editorial memory — technical ≠ creative
        for hard_fail in qa_result.hard_fails:
            self._record_qa_pattern(
                clip_id=clip_id,
                edit_plan_id=edit_plan.candidate_id,
                defect_description=hard_fail,
                platform=edit_plan.target_platform,
                now=now
            )

        self.store.save()

    def record_performance(
        self,
        clip_id: str,
        performance_data: Dict[str, Any],
        account_id: str = ""
    ) -> None:
        """
        Update evidence records with real audience performance data.

        This is called ONLY when actual platform metrics are available.
        Do NOT call this function with invented or estimated values.

        Updates quality_weight from 0.75 (QA-only) to 1.00 (has performance data),
        which increases the confidence ceiling for all memories linked to this clip.
        """
        if not performance_data:
            return

        now = _now_iso()

        # Calculate a magnitude from available performance metrics
        magnitude = self._performance_to_magnitude(performance_data)

        # Determine positive/negative from performance threshold
        # Default threshold: retention > 50% = positive
        retention = performance_data.get("average_view_duration_pct", None)
        if retention is not None:
            outcome = OUTCOME_POSITIVE if retention >= 50.0 else OUTCOME_NEGATIVE
        else:
            # No retention metric available — keep magnitude, use NEUTRAL
            outcome = OUTCOME_NEUTRAL

        for ev in self.store.evidence_for_clip(clip_id):
            if ev.memory_id and ev.is_valid_training:
                ev.performance_data = performance_data
                ev.has_performance_data = True
                ev.magnitude = magnitude
                if outcome != OUTCOME_NEUTRAL:
                    ev.outcome = outcome
                self.store.put_evidence(ev)
                mem = self.store.get_memory(ev.memory_id)
                if mem:
                    self._recompute_and_save(mem)

        # Create a PERFORMANCE memory for this account if perf data exists
        if account_id:
            self._record_performance_memory(
                clip_id=clip_id,
                account_id=account_id,
                performance_data=performance_data,
                magnitude=magnitude,
                outcome=outcome,
                now=now
            )

        self.store.save()

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 2 — Retrieval
    # ──────────────────────────────────────────────────────────────────────────

    def retrieve(self, query: MemoryQuery) -> List[MemoryRetrievalResult]:
        """
        Retrieve the most relevant memories for a query.

        Relevance score = confidence * tag_overlap * recency_weight
        Only returns top_k results.
        RETIRED and SUPERSEDED memories are excluded by default unless
        explicitly included via query.exclude_statuses override.

        This is the ONLY way the Brain should access historical memory.
        It does NOT dump the entire memory database — only top-K relevant results.
        """
        default_exclude = [STATUS_RETIRED, STATUS_SUPERSEDED]
        excluded = set(query.exclude_statuses) if query.exclude_statuses else set(default_exclude)

        results = []
        for mem in self.store.all_memories():
            if mem.status in excluded:
                continue
            if query.scope and mem.scope != query.scope:
                continue
            if query.scope_id and mem.scope_id != query.scope_id:
                continue
            if query.memory_types and mem.memory_type not in query.memory_types:
                continue
            if mem.confidence < query.min_confidence:
                continue
            if mem.sample_size < query.min_sample_size:
                continue

            # Check performance data requirement
            if query.require_performance_data:
                evs = self.store.evidence_for_memory(mem.memory_id)
                if not any(e.has_performance_data for e in evs):
                    continue

            # Compute retrieval score
            tag_overlap = self._compute_tag_overlap(query.tags, mem.tags)
            retrieval_score = mem.confidence * tag_overlap * max(mem.recency_weight, 0.1)

            # Build evidence + contradictions for this result
            evidence_records = [
                e for e in self.store.evidence_for_memory(mem.memory_id)
                if e.is_valid_training
            ]
            contradictions = [
                m for m in self.store.all_memories()
                if m.memory_id != mem.memory_id
                and m.subject == mem.subject
                and m.scope == mem.scope
                and m.status == STATUS_CONTRADICTED
            ]

            results.append(MemoryRetrievalResult(
                memory=mem,
                retrieval_score=retrieval_score,
                tag_overlap=tag_overlap,
                evidence_records=evidence_records,
                contradictions=contradictions
            ))

        results.sort(key=lambda r: r.retrieval_score, reverse=True)
        return results[:query.top_k]

    def retrieve_for_edit_plan(
        self,
        edit_plan: EditPlan,
        show_id: str = "",
        platform: str = "youtube_shorts",
        record_influence: bool = True
    ) -> List[MemoryRetrievalResult]:
        """
        Retrieve memories relevant to a specific EditPlan context.

        Automatically constructs the query from EditPlan's observable patterns.
        If record_influence=True, the edit_plan.candidate_id is written to
        memory.edit_plans_influenced for traceability.

        Returns a ranked short list — NOT the full memory database.
        """
        patterns = self._extract_edit_plan_patterns(edit_plan)
        all_tags = []
        for _, _, tags in patterns:
            all_tags.extend(tags)

        query = MemoryQuery(
            tags=list(set(all_tags + [platform, show_id or "global"])),
            scope=SCOPE_SHOW if show_id else SCOPE_GLOBAL,
            scope_id=show_id or "",
            memory_types=[MEMORY_TYPE_EDITORIAL, MEMORY_TYPE_STRATEGY],
            min_confidence=0.0,
            top_k=5,
            exclude_statuses=[STATUS_RETIRED, STATUS_SUPERSEDED],
        )

        results = self.retrieve(query)

        if record_influence:
            for r in results:
                if edit_plan.candidate_id not in r.memory.edit_plans_influenced:
                    r.memory.edit_plans_influenced.append(edit_plan.candidate_id)
                    self.store.put_memory(r.memory)
            self.store.save()

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3 — Auditability
    # ──────────────────────────────────────────────────────────────────────────

    def explain_belief(self, memory_id: str) -> Dict[str, Any]:
        """
        Return the full explanation of why the Brain holds a belief.

        "Why do you believe this?"
        Returns: memory, all evidence records, confidence components,
                 contradictions if any.
        """
        mem = self.store.get_memory(memory_id)
        if not mem:
            return {"error": f"Memory {memory_id} not found"}

        evidence = self.store.evidence_for_memory(memory_id)
        days = _days_since(mem.most_recent_evidence_at)
        components = self._confidence_components(mem, evidence)

        contradictions = [
            m for m in self.store.all_memories()
            if m.memory_id != memory_id
            and m.subject == mem.subject
            and m.scope == mem.scope
        ]

        return {
            "memory_id": memory_id,
            "statement": mem.statement,
            "status": mem.status,
            "confidence": round(mem.confidence, 4),
            "provenance": mem.provenance,
            "confidence_components": components,
            "sample_size": mem.sample_size,
            "success_count": mem.success_count,
            "failure_count": mem.failure_count,
            "days_since_last_evidence": round(days, 1),
            "evidence_count": len(evidence),
            "evidence_with_performance_data": sum(1 for e in evidence if e.has_performance_data),
            "edit_plans_influenced": mem.edit_plans_influenced,
            "contradictions": [
                {"memory_id": c.memory_id, "status": c.status, "confidence": round(c.confidence, 4)}
                for c in contradictions
            ],
            "evidence_summary": [
                {
                    "evidence_id": e.evidence_id,
                    "outcome": e.outcome,
                    "observation": e.observation,
                    "magnitude": e.magnitude,
                    "qa_result_summary": e.qa_result_summary,
                    "has_performance_data": e.has_performance_data,
                    "is_valid_training": e.is_valid_training,
                    "created_at": e.created_at,
                }
                for e in sorted(evidence, key=lambda e: e.created_at, reverse=True)
            ],
        }

    def trace_edit_plan(self, edit_plan_id: str) -> Dict[str, Any]:
        """
        Return all memories that influenced a given EditPlan.

        Enables the chain:
            EditPlan → decision → memory used → evidence behind memory

        This is the auditability path for understanding why the Brain
        made a particular set of editorial decisions.
        """
        influenced_memories = [
            m for m in self.store.all_memories()
            if edit_plan_id in m.edit_plans_influenced
        ]
        evidence_for_plan = self.store.evidence_for_edit_plan(edit_plan_id)

        return {
            "edit_plan_id": edit_plan_id,
            "memories_consulted": len(influenced_memories),
            "memories": [
                {
                    "memory_id": m.memory_id,
                    "subject": m.subject,
                    "statement": m.statement,
                    "confidence": round(m.confidence, 4),
                    "status": m.status,
                    "sample_size": m.sample_size,
                }
                for m in influenced_memories
            ],
            "evidence_produced_by_this_plan": [
                {
                    "evidence_id": e.evidence_id,
                    "memory_id": e.memory_id,
                    "outcome": e.outcome,
                    "observation": e.observation,
                }
                for e in evidence_for_plan
            ],
        }

    def get_active_memories(
        self, scope: str = "", scope_id: str = ""
    ) -> List[Memory]:
        """Return all ACTIVE memories, optionally filtered by scope."""
        mems = self.store.all_memories()
        result = [m for m in mems if m.status == STATUS_ACTIVE]
        if scope:
            result = [m for m in result if m.scope == scope]
        if scope_id:
            result = [m for m in result if m.scope_id == scope_id]
        return sorted(result, key=lambda m: m.confidence, reverse=True)

    def get_contradicted_memories(self) -> List[Memory]:
        return [m for m in self.store.all_memories() if m.status == STATUS_CONTRADICTED]

    def audit(self) -> Dict[str, Any]:
        """
        Full inspection of the entire memory store.
        Answers: "Show all active memories", "Show contradicted memories",
                 "How many total beliefs", etc.
        """
        mems = self.store.all_memories()
        evs = self.store.all_evidence()
        status_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}
        for m in mems:
            status_counts[m.status] = status_counts.get(m.status, 0) + 1
            type_counts[m.memory_type] = type_counts.get(m.memory_type, 0) + 1

        return {
            "total_memories": len(mems),
            "total_evidence_records": len(evs),
            "status_breakdown": status_counts,
            "type_breakdown": type_counts,
            "exploration_ratio": self.exploration_ratio,
            "active_memories": [
                {
                    "memory_id": m.memory_id,
                    "subject": m.subject,
                    "statement": m.statement,
                    "confidence": round(m.confidence, 4),
                    "sample_size": m.sample_size,
                    "scope": m.scope,
                    "scope_id": m.scope_id,
                }
                for m in mems if m.status == STATUS_ACTIVE
            ],
            "contradicted_memories": [
                {
                    "memory_id": m.memory_id,
                    "subject": m.subject,
                    "confidence": round(m.confidence, 4),
                    "success": m.success_count,
                    "failure": m.failure_count,
                }
                for m in mems if m.status == STATUS_CONTRADICTED
            ],
        }

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 4 — Exploration
    # ──────────────────────────────────────────────────────────────────────────

    def should_explore(self) -> bool:
        """
        Return True with probability = exploration_ratio.
        Deterministic seed not used — exploration should be stochastic.
        """
        import random
        return random.random() < self.exploration_ratio

    def suggest_exploration(
        self, current_tags: List[str]
    ) -> Optional[ExplorationSuggestion]:
        """
        Suggest a pattern the Brain has not validated recently, or
        one that intentionally steps away from the dominant active memory.

        Returns None if no sensible exploration can be identified.
        The suggestion is ADVISORY — the editorial layer decides whether to use it.
        """
        # Find the dominant ACTIVE memory matching current tags
        active = [
            m for m in self.store.all_memories()
            if m.status == STATUS_ACTIVE
            and m.memory_type == MEMORY_TYPE_EDITORIAL
            and self._compute_tag_overlap(current_tags, m.tags) > 0.3
        ]
        if not active:
            return None

        dominant = max(active, key=lambda m: m.confidence)

        # Suggest the opposite or unexplored variant
        subject = dominant.subject
        suggestion_desc = self._opposite_pattern(subject)
        if not suggestion_desc:
            return None

        return ExplorationSuggestion(
            suggestion_id="exp_" + uuid.uuid4().hex[:8],
            pattern_type=subject.split(":")[0] if ":" in subject else subject,
            description=suggestion_desc["description"],
            rationale=(
                f"Dominant belief '{dominant.statement}' has confidence {dominant.confidence:.2f} "
                f"based on {dominant.sample_size} observations. "
                f"Controlled exploration may discover whether: {suggestion_desc['hypothesis']}"
            ),
            exploration_probability=self.exploration_ratio,
            dominant_memory_id=dominant.memory_id
        )

    def record_experiment(self, experiment: ExperimentRecord) -> None:
        """Record a formal A/B experiment for later evaluation."""
        self.store.put_experiment(experiment)
        self.store.save()

    def get_all_experiments(self) -> List[ExperimentRecord]:
        return self.store.all_experiments()

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 5 — Internal confidence computation
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_confidence(self, mem: Memory, evidence: List[EvidenceRecord]) -> float:
        """
        Apply the deterministic confidence formula documented in CONFIDENCE_MODEL_DOC.

        All inputs are explicit, inspectable, and reproducible.
        """
        n = mem.sample_size
        if n == 0:
            return 0.0

        # 1. success_rate
        success_rate = mem.success_count / n

        # 2. sample_weight (Laplace smoothing)
        sample_weight = n / (n + LAPLACE_K)

        # 3. quality_weight
        has_perf = any(e.has_performance_data for e in evidence if e.is_valid_training)
        has_qa_outcome = any(
            e.outcome != OUTCOME_NEUTRAL for e in evidence if e.is_valid_training
        )
        if has_perf:
            quality_weight = 1.00
        elif has_qa_outcome:
            quality_weight = 0.75
        else:
            quality_weight = 0.50

        # 4. recency_weight
        days = _days_since(mem.most_recent_evidence_at)
        recency_weight = RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * math.pow(2.0, -days / HALF_LIFE_DAYS)

        raw = success_rate * sample_weight * quality_weight * recency_weight
        return min(1.0, max(0.0, raw))

    def _confidence_components(
        self, mem: Memory, evidence: List[EvidenceRecord]
    ) -> Dict[str, float]:
        """Return each component of the confidence formula for inspection."""
        n = mem.sample_size
        if n == 0:
            return {"success_rate": 0, "sample_weight": 0, "quality_weight": 0, "recency_weight": 0}

        success_rate = mem.success_count / n
        sample_weight = n / (n + LAPLACE_K)

        has_perf = any(e.has_performance_data for e in evidence if e.is_valid_training)
        has_qa = any(e.outcome != OUTCOME_NEUTRAL for e in evidence if e.is_valid_training)
        quality_weight = 1.00 if has_perf else (0.75 if has_qa else 0.50)

        days = _days_since(mem.most_recent_evidence_at)
        recency_weight = RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * math.pow(2.0, -days / HALF_LIFE_DAYS)

        return {
            "success_rate":   round(success_rate, 4),
            "sample_weight":  round(sample_weight, 4),
            "quality_weight": round(quality_weight, 4),
            "recency_weight": round(recency_weight, 4),
            "product":        round(success_rate * sample_weight * quality_weight * recency_weight, 4)
        }

    def _determine_status(self, mem: Memory) -> str:
        """Determine status from confidence and contradiction ratio."""
        if mem.status in (STATUS_RETIRED, STATUS_SUPERSEDED):
            return mem.status  # Manual status — never auto-overridden
        n = mem.sample_size
        if n == 0:
            return STATUS_WEAK
        contradiction_r = mem.failure_count / n
        if contradiction_r > CONTRADICTION_RATIO and n >= CONTRADICTION_MIN_N:
            return STATUS_CONTRADICTED
        if mem.confidence >= ACTIVE_THRESHOLD:
            return STATUS_ACTIVE
        return STATUS_WEAK

    def _recompute_and_save(self, mem: Memory) -> Memory:
        """
        Recompute confidence and status for a memory, then persist.
        Called after any new evidence is added.
        """
        evidence = self.store.evidence_for_memory(mem.memory_id)
        valid = [e for e in evidence if e.is_valid_training]

        # Recount from valid evidence
        mem.sample_size = len(valid)
        mem.success_count = sum(1 for e in valid if e.outcome == OUTCOME_POSITIVE)
        mem.failure_count = sum(1 for e in valid if e.outcome == OUTCOME_NEGATIVE)

        # Update recency
        timestamps = sorted([e.created_at for e in valid if e.created_at], reverse=True)
        mem.most_recent_evidence_at = timestamps[0] if timestamps else ""
        days = _days_since(mem.most_recent_evidence_at)
        mem.recency_weight = round(
            RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * math.pow(2.0, -days / HALF_LIFE_DAYS), 4
        )

        # Recompute confidence
        mem.confidence = round(self._compute_confidence(mem, valid), 4)
        mem.status = self._determine_status(mem)
        mem.updated_at = _now_iso()

        # Update provenance summary
        mem.provenance = (
            f"n={mem.sample_size}, pos={mem.success_count}, neg={mem.failure_count}, "
            f"confidence={mem.confidence:.4f}, status={mem.status}, "
            f"last_evidence={mem.most_recent_evidence_at[:10] if mem.most_recent_evidence_at else 'none'}"
        )

        self.store.put_memory(mem)
        return mem

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 6 — Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_or_create_memory(
        self,
        memory_id: str,
        memory_type: str,
        scope: str,
        scope_id: str,
        subject: str,
        statement: str,
        tags: List[str],
        now: str
    ) -> Memory:
        mem = self.store.get_memory(memory_id)
        if mem is None:
            mem = Memory(
                memory_id=memory_id,
                memory_type=memory_type,
                scope=scope,
                scope_id=scope_id,
                subject=subject,
                statement=statement,
                tags=list(set(tags)),
                created_at=now,
                updated_at=now,
            )
        return mem

    def _extract_edit_plan_patterns(
        self, edit_plan: EditPlan
    ) -> List[tuple]:
        """
        Extract observable editorial patterns from an EditPlan.
        Returns list of (subject, observation_text, tags) tuples.
        """
        patterns = []
        dur = edit_plan.target_duration_sec

        # Hook type pattern
        hook = edit_plan.hook
        if hook:
            mech = hook.mechanism.value if hasattr(hook.mechanism, "value") else str(hook.mechanism)
            subject = f"hook_type:{mech}"
            obs = f"Hook mechanism '{mech}' selected. Strength {hook.hook_strength:.1f}/10."
            tags = ["hook_type", mech, "hook"]
            patterns.append((subject, obs, tags))

        # Duration range pattern
        if dur <= 20:
            dur_label = "very_short_0_20s"
        elif dur <= 35:
            dur_label = "short_20_35s"
        elif dur <= 55:
            dur_label = "medium_35_55s"
        elif dur <= 75:
            dur_label = "standard_55_75s"
        else:
            dur_label = "long_75s_plus"
        subject = f"clip_duration:{dur_label}"
        obs = f"Clip duration {dur:.1f}s falls in range '{dur_label}'."
        tags = ["duration", dur_label, "clip_length"]
        patterns.append((subject, obs, tags))

        # Editing necessity level
        necessity = edit_plan.editing_necessity
        if necessity < 0.25:
            level = "minimal_editing"
        elif necessity < 0.55:
            level = "moderate_editing"
        else:
            level = "heavy_editing"
        subject = f"editing_necessity:{level}"
        obs = f"Editing necessity {necessity:.2f} classified as '{level}'."
        tags = ["editing", level, "pacing"]
        patterns.append((subject, obs, tags))

        # Ending strategy
        subject = f"ending_strategy:{edit_plan.ending_strategy}"
        obs = f"Ending strategy '{edit_plan.ending_strategy}' used."
        tags = ["ending", edit_plan.ending_strategy]
        patterns.append((subject, obs, tags))

        return patterns

    def _compute_tag_overlap(self, query_tags: List[str], memory_tags: List[str]) -> float:
        """Fraction of query tags that exist in memory tags. 0.0 if no query tags."""
        if not query_tags:
            return 0.5  # No filter = moderate relevance (don't exclude)
        qt = set(t.lower() for t in query_tags)
        mt = set(t.lower() for t in memory_tags)
        return len(qt & mt) / len(qt)

    def _record_qa_pattern(
        self,
        clip_id: str,
        edit_plan_id: str,
        defect_description: str,
        platform: str,
        now: str
    ) -> None:
        """
        Record a QA defect as a QA_PATTERN memory.
        NEVER linked to EDITORIAL memories.
        These describe technical render/source patterns, not creative decisions.
        """
        # Categorise the defect type
        defect_lower = defect_description.lower()
        if "black frame" in defect_lower:
            defect_type = "black_frame_occurrence"
        elif "frozen" in defect_lower:
            defect_type = "frozen_frame_occurrence"
        elif "clipping" in defect_lower or "peak" in defect_lower:
            defect_type = "audio_clipping_occurrence"
        elif "resolution" in defect_lower:
            defect_type = "resolution_mismatch"
        elif "duration" in defect_lower:
            defect_type = "duration_compliance_failure"
        else:
            defect_type = "generic_render_defect"

        memory_id = _make_memory_id(MEMORY_TYPE_QA_PATTERN, SCOPE_PLATFORM, platform, defect_type)

        ev = EvidenceRecord(
            evidence_id=_make_evidence_id(),
            memory_id=memory_id,
            source_type=SOURCE_PRODUCTION,
            is_valid_training=True,
            clip_id=clip_id,
            edit_plan_id=edit_plan_id,
            platform=platform,
            observation=f"QA defect: {defect_description}",
            outcome=OUTCOME_NEGATIVE,
            magnitude=0.2,  # Technical failure is a significant negative signal
            created_at=now,
        )
        self.store.put_evidence(ev)

        mem = self._get_or_create_memory(
            memory_id=memory_id,
            memory_type=MEMORY_TYPE_QA_PATTERN,
            scope=SCOPE_PLATFORM,
            scope_id=platform,
            subject=defect_type,
            statement=f"Technical defect '{defect_type}' has occurred on {platform}",
            tags=["qa_pattern", defect_type, platform, "technical"],
            now=now
        )
        if ev.evidence_id not in mem.evidence_ids:
            mem.evidence_ids.append(ev.evidence_id)
        self._recompute_and_save(mem)

    def _record_performance_memory(
        self,
        clip_id: str,
        account_id: str,
        performance_data: Dict[str, Any],
        magnitude: float,
        outcome: str,
        now: str
    ) -> None:
        """Record a PERFORMANCE memory scoped to an account."""
        memory_id = _make_memory_id(MEMORY_TYPE_PERFORMANCE, SCOPE_ACCOUNT, account_id, "clip_performance")
        ev = EvidenceRecord(
            evidence_id=_make_evidence_id(),
            memory_id=memory_id,
            source_type=SOURCE_PRODUCTION,
            is_valid_training=True,
            clip_id=clip_id,
            account_id=account_id,
            observation=f"Clip performance recorded: {list(performance_data.keys())}",
            outcome=outcome,
            magnitude=magnitude,
            performance_data=performance_data,
            has_performance_data=True,
            created_at=now,
        )
        self.store.put_evidence(ev)
        mem = self._get_or_create_memory(
            memory_id=memory_id,
            memory_type=MEMORY_TYPE_PERFORMANCE,
            scope=SCOPE_ACCOUNT,
            scope_id=account_id,
            subject="clip_performance",
            statement=f"Clip performance pattern for account {account_id}",
            tags=["performance", account_id, "audience"],
            now=now
        )
        if ev.evidence_id not in mem.evidence_ids:
            mem.evidence_ids.append(ev.evidence_id)
        self._recompute_and_save(mem)

    def _performance_to_magnitude(self, performance_data: Dict[str, Any]) -> float:
        """
        Convert performance metrics to a [0.0, 1.0] magnitude signal.
        Uses average_view_duration_pct as primary metric if available.
        """
        retention = performance_data.get("average_view_duration_pct")
        if retention is not None:
            return min(1.0, max(0.0, float(retention) / 100.0))
        views = performance_data.get("views", 0)
        if views:
            return min(1.0, math.log1p(views) / math.log1p(100000))
        return 0.5  # Baseline if no usable metric

    def _opposite_pattern(self, subject: str) -> Optional[Dict[str, str]]:
        """
        Return an exploration target for a given dominant subject.
        Returns None if no sensible opposite is known.
        """
        opposites = {
            "hook_type:question":              {"description": "Try outcome_first hook", "hypothesis": "Direct payoff preview may outperform question framing"},
            "hook_type:outcome_first":         {"description": "Try curiosity_gap hook", "hypothesis": "Open loop may create stronger watch-through than immediate payoff"},
            "hook_type:curiosity_gap":         {"description": "Try strong_claim hook", "hypothesis": "Confident assertion may attract higher-intent viewers"},
            "hook_type:strong_claim":          {"description": "Try question hook", "hypothesis": "Question framing invites more engagement and comments"},
            "clip_duration:short_20_35s":      {"description": "Try medium_35_55s duration", "hypothesis": "Slightly longer format may allow better context and payoff"},
            "clip_duration:medium_35_55s":     {"description": "Try short_20_35s duration", "hypothesis": "Shorter punchy clips may drive higher completion rate"},
            "clip_duration:standard_55_75s":   {"description": "Try medium_35_55s duration", "hypothesis": "Reducing length may improve retention and platform ranking"},
            "editing_necessity:minimal_editing": {"description": "Try moderate_editing approach", "hypothesis": "Light pacing edits may improve viewer engagement"},
            "editing_necessity:moderate_editing": {"description": "Try minimal_editing approach", "hypothesis": "Natural conversation flow may test better than edited pacing"},
            "ending_strategy:natural_end":     {"description": "Try question_end strategy", "hypothesis": "Ending with an open question may drive more comments"},
            "ending_strategy:question_end":    {"description": "Try natural_end strategy", "hypothesis": "Clean natural ending may feel more authentic"},
        }
        return opposites.get(subject.lower())
