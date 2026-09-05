"""
Creative Intelligence Engine — Memory Models (Phase 10)

Defines all data structures for the Creative Memory system.
These are kept separate from brain/models.py to isolate the memory
subsystem from the core production pipeline models.

Design principles:
    - All fields are basic Python types so JSON round-trip is safe
    - No nested dataclasses (flat structure, linked by ID strings)
    - EvidenceRecord is the atomic unit; Memory is derived from Evidence
    - memory_id is deterministic (same subject + scope = same memory)
    - evidence_id is a random UUID (each observation is unique)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ─── Memory Type Constants ────────────────────────────────────────────────────
# What KIND of knowledge this memory represents.
# Critically: QA_PATTERN memories never influence EDITORIAL decisions.

MEMORY_TYPE_CONTENT     = "CONTENT"      # Facts about processed content/episodes
MEMORY_TYPE_EDITORIAL   = "EDITORIAL"    # What was decided editorially and why
MEMORY_TYPE_QA_PATTERN  = "QA_PATTERN"  # Technical QA failure patterns (NOT creative)
MEMORY_TYPE_PERFORMANCE = "PERFORMANCE"  # Platform audience metrics
MEMORY_TYPE_STRATEGY    = "STRATEGY"     # Higher-level derived patterns

# ─── Scope Constants ─────────────────────────────────────────────────────────
# What CONTEXT this memory applies to.
# Account-specific learning does not automatically become global truth.

SCOPE_GLOBAL   = "GLOBAL"    # Applies everywhere
SCOPE_ACCOUNT  = "ACCOUNT"   # Applies to one social media account
SCOPE_SHOW     = "SHOW"      # Applies to one podcast/show
SCOPE_SERIES   = "SERIES"    # Applies to a set of episodes
SCOPE_PLATFORM = "PLATFORM"  # Applies to one publishing platform (tiktok, yt_shorts)
SCOPE_FORMAT   = "FORMAT"    # Applies to one content format (tutorial, reaction, etc.)

# ─── Status Constants ─────────────────────────────────────────────────────────
# A memory's status reflects the quality of its evidence, not the Brain's opinion.
# Historical evidence is NEVER deleted when a memory changes status.

STATUS_ACTIVE       = "ACTIVE"        # confidence >= 0.60 — reliable enough to inform decisions
STATUS_WEAK         = "WEAK"          # 0.30 <= confidence < 0.60 — use with caution
STATUS_CONTRADICTED = "CONTRADICTED"  # failure_count > success_count AND sample_size >= 3
STATUS_SUPERSEDED   = "SUPERSEDED"    # Replaced by a more specific or recent memory
STATUS_RETIRED      = "RETIRED"       # Explicitly removed from active use

# ─── Evidence Source Types ────────────────────────────────────────────────────
# Prevents test fixture contamination of production creative memory.

SOURCE_PRODUCTION  = "PRODUCTION"    # Real published content
SOURCE_TEST        = "TEST"          # Dev/QA test fixtures — never contaminates memory
SOURCE_BENCHMARK   = "BENCHMARK"     # Controlled comparison experiment
SOURCE_SYNTHETIC   = "SYNTHETIC"     # Artificially generated content

# ─── Outcome Constants ────────────────────────────────────────────────────────

OUTCOME_POSITIVE = "POSITIVE"  # Evidence supports the belief
OUTCOME_NEGATIVE = "NEGATIVE"  # Evidence contradicts the belief
OUTCOME_NEUTRAL  = "NEUTRAL"   # Observation recorded but outcome not yet determined


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class EvidenceRecord:
    """
    A single, atomic observation that is used to build or update a Memory.

    EvidenceRecord is the ground truth.
    It is NEVER deleted, even if the Memory it supports is contradicted.

    Every field is explicit. No vague "evidence_summary" strings.
    If performance data does not exist, has_performance_data = False.
    Do NOT fabricate performance data.
    """
    evidence_id: str = ""
    memory_id: str = ""

    # Source classification — determines whether this record is valid for training
    source_type: str = SOURCE_PRODUCTION
    is_valid_training: bool = True     # False = test fixture / debug run / synthetic

    # What clip/episode this evidence came from
    clip_id: str = ""
    episode_id: str = ""
    account_id: str = ""
    platform: str = ""
    edit_plan_id: str = ""             # Links back to the EditPlan that produced this clip

    # The observation itself
    observation: str = ""              # Precise description of what was observed
    outcome: str = OUTCOME_NEUTRAL     # POSITIVE / NEGATIVE / NEUTRAL
    magnitude: float = 0.5            # Strength of effect: 0.0=null, 0.5=baseline, 1.0=maximal

    # Technical QA context
    # Stored for auditability ONLY. Not used to form creative memory.
    qa_result_summary: str = ""        # e.g. "APPROVED 97.5/100" or "REJECTED: black_frame"
    qa_passed: Optional[bool] = None   # True / False / None (if QA not yet run)

    # Performance data (absent until real platform metrics are collected)
    # DO NOT fill these fields with invented numbers.
    performance_data: Dict[str, Any] = field(default_factory=dict)
    has_performance_data: bool = False  # True only when real audience data exists

    # Metadata
    created_at: str = ""
    notes: str = ""


@dataclass
class Memory:
    """
    A learned belief backed by one or more EvidenceRecords.

    Memory is evidence, not truth.
    The Brain may hold this belief while new evidence accumulates.
    When evidence contradicts the belief consistently, confidence drops
    and the status transitions to CONTRADICTED.

    memory_id is deterministic (hash of scope + subject + type),
    so the same kind of belief from the same context always updates
    the same memory rather than creating a duplicate.

    Evidence is never erased. Retracted or contradicted memories remain
    in the store with their full evidence trail for auditability.
    """
    memory_id: str = ""
    memory_type: str = MEMORY_TYPE_EDITORIAL

    # Scope — what context this belief applies to
    scope: str = SCOPE_GLOBAL
    scope_id: str = ""                 # e.g. "cap_table_podcast", "youtube_shorts", "acc_xyz"

    # The belief
    subject: str = ""                  # Compact key, e.g. "hook_type:QUESTION"
    statement: str = ""                # Full natural language statement of the belief

    # Evidence links (IDs only — full records are in EvidenceRecord store)
    evidence_ids: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)    # clip/episode IDs referenced

    # Computed statistics — recalculated whenever new evidence is added
    sample_size: int = 0
    success_count: int = 0
    failure_count: int = 0
    confidence: float = 0.0           # [0.0, 1.0] — see CONFIDENCE_MODEL_DOC
    recency_weight: float = 0.0       # Most recent evidence recency decay value

    # Status
    status: str = STATUS_WEAK
    provenance: str = ""               # Human-readable explanation of why this belief formed

    # Timestamps
    created_at: str = ""
    updated_at: str = ""
    most_recent_evidence_at: str = ""  # Timestamp of the most recent EvidenceRecord

    # Retrieval tags (used for relevance scoring, not full-text search)
    tags: List[str] = field(default_factory=list)

    # Traceability: which EditPlan IDs retrieved and used this memory
    # Enables: trace_edit_plan(id) → all memories that influenced it
    edit_plans_influenced: List[str] = field(default_factory=list)

    # Experiment context (if this memory was part of a formal A/B test)
    experiment_id: str = ""


@dataclass
class MemoryQuery:
    """
    Structured query used to retrieve relevant memories before a decision.

    The Brain constructs a MemoryQuery from the current EditPlan/content context
    and passes it to CreativeMemory.retrieve().
    The result is a ranked short list — not the entire memory database.
    """
    tags: List[str] = field(default_factory=list)
    scope: str = ""                             # Filter to this scope level
    scope_id: str = ""                          # Filter to this scope ID
    memory_types: List[str] = field(default_factory=list)  # e.g. [EDITORIAL, STRATEGY]
    min_confidence: float = 0.0
    min_sample_size: int = 0
    top_k: int = 5
    exclude_statuses: List[str] = field(default_factory=list)  # e.g. [RETIRED, SUPERSEDED]
    require_performance_data: bool = False       # If True, only return memories with perf evidence


@dataclass
class MemoryRetrievalResult:
    """Structured result of a single memory returned by a query."""
    memory: Memory = field(default_factory=Memory)
    retrieval_score: float = 0.0    # Combined relevance rank score
    tag_overlap: float = 0.0        # Fraction of query tags matched
    evidence_records: List[EvidenceRecord] = field(default_factory=list)
    contradictions: List[Memory] = field(default_factory=list)   # Contradicted siblings


@dataclass
class ExplorationSuggestion:
    """
    Suggestion to try a pattern the Brain has not validated recently.
    Generated when exploration_ratio (configurable, default 20%) triggers.

    Exploration prevents the Brain from permanently locking into one format.
    The suggestion is returned to the editorial layer as advisory — it does
    not force the decision.
    """
    suggestion_id: str = ""
    pattern_type: str = ""            # "hook_style", "clip_duration", "pacing", etc.
    description: str = ""             # What to try
    rationale: str = ""               # Why this is worth exploring
    exploration_probability: float = 0.20
    dominant_memory_id: str = ""      # The dominant belief this intentionally steps away from


@dataclass
class ExperimentRecord:
    """
    Formal experiment comparing two or more editorial variants.
    Allows the Brain to learn from controlled comparisons rather than
    treating every clip as an isolated event.
    """
    experiment_id: str = ""
    hypothesis: str = ""
    variant_a_description: str = ""
    variant_b_description: str = ""
    controlled_variables: List[str] = field(default_factory=list)
    outcome: str = ""                  # VARIANT_A_WINS / VARIANT_B_WINS / INCONCLUSIVE
    evidence_quality: str = ""         # HIGH / MEDIUM / LOW
    conclusion: str = ""
    created_at: str = ""
    closed_at: str = ""
    evidence_ids: List[str] = field(default_factory=list)
