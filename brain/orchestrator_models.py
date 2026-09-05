"""
Batch Production Orchestrator — Data Models (Phase 11)

All typed contracts for orchestration state, events, jobs, and results.
No intelligence lives here. This is pure data structure definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ─── Job States ───────────────────────────────────────────────────────────────

class JobState(str, Enum):
    """
    Explicit FSM states for a production job.
    Transitions are validated against VALID_TRANSITIONS before being applied.
    """
    QUEUED             = "QUEUED"
    INGESTING          = "INGESTING"
    INGESTED           = "INGESTED"
    ANALYZING          = "ANALYZING"
    ANALYZED           = "ANALYZED"
    DISCOVERING        = "DISCOVERING"
    DISCOVERED         = "DISCOVERED"
    PLANNING           = "PLANNING"
    PLANNED            = "PLANNED"
    RENDERING          = "RENDERING"
    RENDERED           = "RENDERED"
    QA_PENDING         = "QA_PENDING"
    QA_FAILED          = "QA_FAILED"
    REPAIRING          = "REPAIRING"
    REPAIR_ESCALATED   = "REPAIR_ESCALATED"
    FINAL_QA           = "FINAL_QA"
    APPROVED           = "APPROVED"
    REJECTED           = "REJECTED"
    OUTPUT_READY       = "OUTPUT_READY"
    MEMORY_PENDING     = "MEMORY_PENDING"
    COMPLETED          = "COMPLETED"
    FAILED             = "FAILED"
    CANCELLED          = "CANCELLED"


# Valid state transitions. Only these edges are allowed.
# The orchestrator will raise StateTransitionError for any other transition.
VALID_TRANSITIONS: Dict[JobState, List[JobState]] = {
    JobState.QUEUED:           [JobState.INGESTING, JobState.CANCELLED],
    JobState.INGESTING:        [JobState.INGESTED, JobState.FAILED, JobState.CANCELLED],
    JobState.INGESTED:         [JobState.ANALYZING, JobState.CANCELLED],
    JobState.ANALYZING:        [JobState.ANALYZED, JobState.FAILED, JobState.CANCELLED],
    JobState.ANALYZED:         [JobState.DISCOVERING, JobState.CANCELLED],
    JobState.DISCOVERING:      [JobState.DISCOVERED, JobState.FAILED, JobState.CANCELLED],
    JobState.DISCOVERED:       [JobState.PLANNING, JobState.REJECTED, JobState.CANCELLED],
    JobState.PLANNING:         [JobState.PLANNED, JobState.FAILED, JobState.CANCELLED],
    JobState.PLANNED:          [JobState.RENDERING, JobState.CANCELLED],
    JobState.RENDERING:        [JobState.RENDERED, JobState.FAILED, JobState.CANCELLED],
    JobState.RENDERED:         [JobState.QA_PENDING, JobState.FAILED],
    JobState.QA_PENDING:       [JobState.APPROVED, JobState.QA_FAILED, JobState.FAILED],
    JobState.QA_FAILED:        [JobState.REPAIRING, JobState.REJECTED],
    JobState.REPAIRING:        [JobState.FINAL_QA, JobState.REPAIR_ESCALATED, JobState.FAILED],
    JobState.REPAIR_ESCALATED: [JobState.REJECTED, JobState.FAILED],
    JobState.FINAL_QA:         [JobState.APPROVED, JobState.REJECTED, JobState.FAILED, JobState.REPAIR_ESCALATED],
    JobState.APPROVED:         [JobState.OUTPUT_READY],
    JobState.OUTPUT_READY:     [JobState.MEMORY_PENDING, JobState.COMPLETED],
    JobState.MEMORY_PENDING:   [JobState.COMPLETED, JobState.FAILED],
    # Terminal states — no outgoing transitions
    JobState.COMPLETED:        [],
    JobState.FAILED:           [],
    JobState.REJECTED:         [],
    JobState.CANCELLED:        [],
}

# States where cancellation is cooperative (interrupt, don't corrupt)
CANCELLABLE_STATES = {
    JobState.QUEUED, JobState.INGESTING, JobState.INGESTED,
    JobState.ANALYZING, JobState.ANALYZED, JobState.DISCOVERING,
    JobState.DISCOVERED, JobState.PLANNING, JobState.PLANNED,
    JobState.RENDERING, JobState.RENDERED,
}

# Terminal states (no further transitions possible)
TERMINAL_STATES = {
    JobState.COMPLETED, JobState.FAILED, JobState.REJECTED, JobState.CANCELLED
}


# ─── Failure Classification ───────────────────────────────────────────────────

class FailureClass(str, Enum):
    """
    Explicit failure classes with distinct retry semantics.
    The orchestrator selects retry policy based on failure class.
    """
    TRANSIENT              = "TRANSIENT"             # Retry with backoff (network, timeout)
    PERMANENT              = "PERMANENT"              # Do not retry
    INVALID_INPUT          = "INVALID_INPUT"          # Bad source data — do not retry
    DEPENDENCY_FAILURE     = "DEPENDENCY_FAILURE"     # Required subsystem unavailable
    RESOURCE_FAILURE       = "RESOURCE_FAILURE"       # Disk, memory — retry after delay
    QA_FAILURE             = "QA_FAILURE"             # QA hard fail — route to repair
    REPAIR_ESCALATION      = "REPAIR_ESCALATION"      # Repair emitted SOURCE_RERENDER_REQUIRED
    SOURCE_RERENDER_REQUIRED = "SOURCE_RERENDER_REQUIRED"  # Needs pipeline re-render from source
    CONFIGURATION_ERROR    = "CONFIGURATION_ERROR"   # Bad config — do not retry
    INTERNAL_ERROR         = "INTERNAL_ERROR"         # Bug in orchestrator — do not retry


# Retry policies by failure class
RETRY_POLICIES: Dict[str, Dict[str, Any]] = {
    FailureClass.TRANSIENT:            {"max_attempts": 3, "backoff_sec": 5,   "retryable": True},
    FailureClass.PERMANENT:            {"max_attempts": 1, "backoff_sec": 0,   "retryable": False},
    FailureClass.INVALID_INPUT:        {"max_attempts": 1, "backoff_sec": 0,   "retryable": False},
    FailureClass.DEPENDENCY_FAILURE:   {"max_attempts": 2, "backoff_sec": 10,  "retryable": True},
    FailureClass.RESOURCE_FAILURE:     {"max_attempts": 3, "backoff_sec": 15,  "retryable": True},
    FailureClass.QA_FAILURE:           {"max_attempts": 1, "backoff_sec": 0,   "retryable": False},
    FailureClass.REPAIR_ESCALATION:    {"max_attempts": 1, "backoff_sec": 0,   "retryable": False},
    FailureClass.SOURCE_RERENDER_REQUIRED: {"max_attempts": 1, "backoff_sec": 0, "retryable": False},
    FailureClass.CONFIGURATION_ERROR:  {"max_attempts": 1, "backoff_sec": 0,   "retryable": False},
    FailureClass.INTERNAL_ERROR:       {"max_attempts": 1, "backoff_sec": 0,   "retryable": False},
}


# ─── Job Identity ─────────────────────────────────────────────────────────────

class ExecutionMode(str, Enum):
    """Determines whether this job writes to production memory."""
    PRODUCTION = "PRODUCTION"   # Real published content — writes to memory
    TEST       = "TEST"         # Isolated test — never writes to production memory
    BENCHMARK  = "BENCHMARK"    # Controlled comparison
    SYNTHETIC  = "SYNTHETIC"    # Artificially generated
    DRY_RUN    = "DRY_RUN"      # Simulated execution, no destructive ops, no memory writes


@dataclass
class StageCheckpoint:
    """Persisted record of a completed stage. Enables crash recovery."""
    stage: str                          # Stage name, e.g. "RENDERED"
    completed_at: str                   # ISO 8601
    idempotency_key: str                # Hash of inputs for duplicate detection
    output_artifact: str = ""           # Path or key of output
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JobEvent:
    """Structured log event. Machine-readable observability record."""
    timestamp: str
    job_id: str
    episode_id: str
    clip_id: str
    stage: str
    previous_state: str
    new_state: str
    event: str
    attempt: int = 0
    duration_sec: float = 0.0
    result: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductionJob:
    """
    A single clip production job.

    One episode can spawn multiple independent ProductionJobs.
    Each job has a unique job_id and tracks its own state, checkpoints, and events.
    """
    job_id: str
    episode_id: str
    clip_id: str                        # candidate_id from ClipCandidate
    account_id: str
    platform: str
    format: str = "ambient_blur_9_16"
    execution_mode: str = ExecutionMode.PRODUCTION

    # Source inputs
    srt_path: str = ""                  # Path to SRT file (string for JSON serialisation)
    source_video_path: str = ""         # Path to source video
    title: str = ""
    source_url: str = ""
    show_id: str = ""

    # State machine
    state: str = JobState.QUEUED
    cancellation_requested: bool = False

    # Timing
    created_at: str = ""
    updated_at: str = ""
    started_at: str = ""
    completed_at: str = ""

    # Attempt tracking
    stage_attempts: Dict[str, int] = field(default_factory=dict)
    total_attempts: int = 0

    # Checkpoints (keyed by stage name)
    checkpoints: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Artifacts
    artifacts: Dict[str, str] = field(default_factory=dict)
    # Possible keys: srt_path, analysis, candidates, edit_plan,
    #                render_output, qa_report, repair_output, final_output

    # Failure info
    failure_class: str = ""
    failure_message: str = ""
    failure_stage: str = ""

    # Escalation info (for SOURCE_RERENDER_REQUIRED)
    escalation: Dict[str, Any] = field(default_factory=dict)

    # Events log
    events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BatchJob:
    """
    A batch containing multiple independent production jobs.

    One batch may span multiple episodes.
    A single clip failure does not cancel the batch.
    """
    batch_id: str
    account_id: str
    platform: str = "youtube_shorts"
    execution_mode: str = ExecutionMode.PRODUCTION
    description: str = ""

    # Job IDs in this batch
    job_ids: List[str] = field(default_factory=list)

    # Batch timing
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""

    # Progress counters (derived from job states)
    total: int = 0
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    rejected: int = 0
    escalated: int = 0
    cancelled: int = 0


# ─── Result Contracts ─────────────────────────────────────────────────────────

@dataclass
class ProductionResult:
    """
    Structured result returned when a ProductionJob reaches a terminal state.
    Never returns a bare boolean.
    """
    job_id: str
    clip_id: str
    status: str                               # Terminal JobState value
    final_artifact: str = ""                  # Path to final output video
    qa_result: Optional[Dict[str, Any]] = None  # Serialised QAResult
    repair_summary: Optional[Dict[str, Any]] = None
    escalation: Optional[Dict[str, Any]] = None  # SOURCE_RERENDER_REQUIRED detail
    duration_sec: float = 0.0
    stages_completed: List[str] = field(default_factory=list)
    memory_updates: List[str] = field(default_factory=list)  # Evidence IDs
    errors: List[str] = field(default_factory=list)
    execution_mode: str = ExecutionMode.PRODUCTION


@dataclass
class BatchResult:
    """
    Structured result for a completed or partial batch.
    All counters are independent — a mixed batch is fully valid.
    """
    batch_id: str
    total: int = 0
    completed: int = 0
    failed: int = 0
    rejected: int = 0
    escalated: int = 0
    cancelled: int = 0
    duration_sec: float = 0.0
    job_results: List[ProductionResult] = field(default_factory=list)


# ─── Exceptions ───────────────────────────────────────────────────────────────

class StateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass


class IdempotencyError(Exception):
    """Raised when a duplicate stage execution is detected."""
    pass


class OrchestratorError(Exception):
    """General orchestrator error."""
    pass
