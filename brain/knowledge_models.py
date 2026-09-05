"""
Persistent Knowledge Base & Self-Improvement Layer — Domain Models (Phase 17)

PURPOSE:
    Defines model-independent, durable data contracts for creative decisions,
    model executions, learning events, versioned knowledge patterns, and experiments.

INVARIANTS:
    - THE DATABASE IS THE CANONICAL STORE; THE LLM IS A REPLACEABLE COMPONENT.
    - Zero private chain-of-thought stored; structured decision summaries only.
    - Zero credentials, tokens, or client secrets in learning records.
    - Multi-tenant isolation: Scopes enforce boundaries (GLOBAL, ACCOUNT, PROJECT, EPISODE).
    - Immutable event streams; historical evidence is append-only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Scopes & Statuses ────────────────────────────────────────────────────────

class KnowledgeScope(str, Enum):
    GLOBAL   = "GLOBAL"     # Universally applicable production principle
    ACCOUNT  = "ACCOUNT"    # Channel / account-specific audience learning
    PROJECT  = "PROJECT"    # Show / project-specific creative lore
    EPISODE  = "EPISODE"    # Single episode context


class PatternStatus(str, Enum):
    CANDIDATE   = "CANDIDATE"    # Hypothesis formed; awaiting sufficient evidence
    VALIDATED   = "VALIDATED"    # Evidence threshold reached; reliable
    ACTIVE      = "ACTIVE"       # Active in production planning context
    DEPRECATED  = "DEPRECATED"   # Superseded by newer / more specific pattern
    REJECTED    = "REJECTED"     # Disproven by contradictory evidence


class ExperimentStatus(str, Enum):
    RUNNING        = "RUNNING"
    SUPPORTED      = "SUPPORTED"
    NOT_SUPPORTED  = "NOT_SUPPORTED"
    INCONCLUSIVE   = "INCONCLUSIVE"


class LearningEventType(str, Enum):
    HOOK_SELECTED           = "HOOK_SELECTED"
    HOOK_PUBLISHED          = "HOOK_PUBLISHED"
    HOOK_PERFORMED_WELL     = "HOOK_PERFORMED_WELL"
    HOOK_PERFORMED_POORLY   = "HOOK_PERFORMED_POORLY"
    CLIP_SELECTED           = "CLIP_SELECTED"
    CLIP_REJECTED           = "CLIP_REJECTED"
    EDIT_PLAN_CREATED       = "EDIT_PLAN_CREATED"
    EDIT_PLAN_REPAIRED      = "EDIT_PLAN_REPAIRED"
    QA_FAILED               = "QA_FAILED"
    QA_REPAIRED             = "QA_REPAIRED"
    PUBLISH_SUCCESS         = "PUBLISH_SUCCESS"
    PUBLISH_REJECTED        = "PUBLISH_REJECTED"
    ANALYTICS_RECEIVED      = "ANALYTICS_RECEIVED"
    PATTERN_DISCOVERED      = "PATTERN_DISCOVERED"
    PATTERN_VALIDATED       = "PATTERN_VALIDATED"
    PATTERN_REJECTED        = "PATTERN_REJECTED"


# ─── Model Execution Registry ─────────────────────────────────────────────────

@dataclass
class ModelRun:
    """
    Durable registry tracking which AI model / version produced which decision.
    Allows historical comparison across LLM upgrades.
    """
    id: str
    model_provider: str          # e.g. "google", "anthropic", "openai", "local"
    model_name: str              # e.g. "gemini-1.5-pro", "claude-3-5-sonnet"
    model_version: str = "v1"
    prompt_version: str = "v1"
    task_type: str = "hook_selection" # "clip_discovery", "editorial_plan", "qa_analysis"
    input_reference: str = ""    # Hash or ID of input prompt/transcript
    output_reference: str = ""   # Hash or ID of output JSON
    latency_ms: int = 0
    token_usage: Dict[str, int] = field(default_factory=dict) # {"prompt_tokens": 0, "completion_tokens": 0}
    success: bool = True
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Creative Decision Record ──────────────────────────────────────────────────

@dataclass
class CreativeDecision:
    """
    Structured, model-independent record of an editorial or creative choice.
    Stores concise decision factors rather than private chain-of-thought.
    """
    id: str
    project_id: str
    episode_id: str
    clip_id: str
    decision_type: str           # "hook_selection", "layout_choice", "pacing_strategy"
    decision_payload: Dict[str, Any] # e.g. {"hook_type": "curiosity_gap", "score": 0.88}
    reasoning_summary: str       # Human & model readable justification
    model_run_id: str = ""       # Foreign key to ModelRun
    memory_context_ids: List[str] = field(default_factory=list) # Knowledge pattern IDs consulted
    version: int = 1
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Learning Event ───────────────────────────────────────────────────────────

@dataclass
class LearningEvent:
    """
    Atomic observation of production or platform performance outcome.
    Forms the immutable evidence trail for pattern induction.
    """
    id: str
    event_type: str              # LearningEventType string
    source_type: str             # "PRODUCTION", "TEST", "BENCHMARK", "SYNTHETIC"
    source_id: str               # ID of clip, job, receipt, or analytics snapshot
    project_id: str = "default"
    account_id: str = "default"
    payload: Dict[str, Any] = field(default_factory=dict)
    confidence_weight: float = 1.0
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Knowledge Pattern ────────────────────────────────────────────────────────

@dataclass
class KnowledgePattern:
    """
    A learned, versioned rule or strategic belief derived from empirical evidence.
    """
    id: str
    pattern_type: str            # e.g. "hook_retention", "pacing_rule", "qa_avoidance"
    statement: str               # Human & model readable strategic truth
    conditions: Dict[str, Any]   # Applicable context: {"format": "ambient_blur", "genre": "podcast"}
    evidence_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    confidence: float = 0.0     # Mathematically calculated: (success+1)/(evidence+2) * sample_dampener
    source_event_ids: List[str] = field(default_factory=list)
    version: int = 1
    status: str = PatternStatus.CANDIDATE.value
    scope: str = KnowledgeScope.GLOBAL.value
    account_id: str = ""
    project_id: str = ""
    counterexamples: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Experiment Record ────────────────────────────────────────────────────────

@dataclass
class ExperimentRecord:
    """
    Structured hypothesis test comparing variant production strategies.
    """
    id: str
    hypothesis: str              # e.g. "Curiosity gap hooks achieve higher 5s retention than direct exposition"
    variant_a: Dict[str, Any]    # {"hook_type": "curiosity_gap"}
    variant_b: Dict[str, Any]    # {"hook_type": "direct_exposition"}
    target_metrics: List[str]    # ["hook_retention_5s", "average_percentage_viewed"]
    sample_size_a: int = 0
    sample_size_b: int = 0
    results_a: Dict[str, float] = field(default_factory=dict)
    results_b: Dict[str, float] = field(default_factory=dict)
    status: str = ExperimentStatus.RUNNING.value
    winner: str = "INCONCLUSIVE"  # "VARIANT_A", "VARIANT_B", "INCONCLUSIVE"
    confidence: float = 0.0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Structured Knowledge Retrieval Context ───────────────────────────────────

@dataclass
class KnowledgeRetrievalContext:
    """
    Model-independent structured context delivered to any reasoning engine / LLM.
    """
    pattern_id: str
    pattern_type: str
    statement: str
    confidence: float
    evidence_count: int
    success_count: int
    failure_count: int
    conditions: Dict[str, Any]
    counterexamples: List[str]
    source_references: List[str]
    last_updated: str

    def to_prompt_context(self) -> str:
        """Render a concise markdown summary suitable for system or planning prompts."""
        return (
            f"- **[{self.pattern_type.upper()}]** {self.statement}\n"
            f"  Confidence: {self.confidence:.2f} ({self.success_count}/{self.evidence_count} successes)\n"
            f"  Conditions: {json.dumps(self.conditions)}"
        )
