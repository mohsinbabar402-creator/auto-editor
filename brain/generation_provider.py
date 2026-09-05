from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


class GenerationJobState(str, Enum):
    """Lifecycle states for a generation job."""
    PLANNED = "PLANNED"
    QUEUED = "QUEUED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    VERIFYING = "VERIFYING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RETRY_WAIT = "RETRY_WAIT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Dictionary mapping each state to a list of valid subsequent states.
VALID_TRANSITIONS: Dict[str, List[str]] = {
    GenerationJobState.PLANNED: [GenerationJobState.QUEUED, GenerationJobState.CANCELLED],
    GenerationJobState.QUEUED: [GenerationJobState.SUBMITTING, GenerationJobState.CANCELLED],
    GenerationJobState.SUBMITTING: [GenerationJobState.SUBMITTED, GenerationJobState.FAILED, GenerationJobState.RETRY_WAIT, GenerationJobState.CANCELLED],
    GenerationJobState.SUBMITTED: [GenerationJobState.GENERATING, GenerationJobState.FAILED, GenerationJobState.CANCELLED],
    GenerationJobState.GENERATING: [GenerationJobState.GENERATED, GenerationJobState.FAILED, GenerationJobState.CANCELLED],
    GenerationJobState.GENERATED: [GenerationJobState.DOWNLOADING, GenerationJobState.FAILED, GenerationJobState.CANCELLED],
    GenerationJobState.DOWNLOADING: [GenerationJobState.DOWNLOADED, GenerationJobState.FAILED, GenerationJobState.RETRY_WAIT, GenerationJobState.CANCELLED],
    GenerationJobState.DOWNLOADED: [GenerationJobState.VERIFYING, GenerationJobState.FAILED],
    GenerationJobState.VERIFYING: [GenerationJobState.ACCEPTED, GenerationJobState.REJECTED, GenerationJobState.FAILED],
    GenerationJobState.ACCEPTED: [],
    GenerationJobState.REJECTED: [GenerationJobState.RETRY_WAIT, GenerationJobState.FAILED],
    GenerationJobState.RETRY_WAIT: [GenerationJobState.QUEUED, GenerationJobState.CANCELLED],
    GenerationJobState.FAILED: [],
    GenerationJobState.CANCELLED: [],
}


def validate_transition(current: str, target: str) -> bool:
    """Check if the state transition is valid."""
    return target in VALID_TRANSITIONS.get(current, [])


class GenerationFailureClass(str, Enum):
    """Standardized failure categories for tracking account health and retries."""
    AUTH_FAILURE = "AUTH_FAILURE"
    RATE_LIMIT = "RATE_LIMIT"
    CREDIT_EXHAUSTED = "CREDIT_EXHAUSTED"
    INVALID_PROMPT = "INVALID_PROMPT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    BAD_ARTIFACT = "BAD_ARTIFACT"
    QUALITY_FAILURE = "QUALITY_FAILURE"
    CONTINUITY_FAILURE = "CONTINUITY_FAILURE"
    UNKNOWN = "UNKNOWN"


class AccountHealthStatus(str, Enum):
    """Health status for a provider account."""
    ACTIVE = "ACTIVE"
    HEALTHY = "HEALTHY"
    COOLDOWN = "COOLDOWN"
    EXHAUSTED = "EXHAUSTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    DISABLED = "DISABLED"
    ERROR = "ERROR"


@dataclass
class GenerationJob:
    """Durable job record for generation tasks."""
    job_id: str
    account_id: str
    project_id: str
    episode_id: str
    scene_id: str
    prompt_text: str
    prompt_version: str
    character_bible_version: str
    state: str = GenerationJobState.PLANNED.value
    attempt: int = 1
    max_attempts: int = 3
    created_at: str = field(default_factory=_now_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failure_reason: Optional[str] = None
    failure_class: Optional[str] = None
    artifact_path: Optional[str] = None
    artifact_hash: Optional[str] = None
    provider_name: str = ""
    provider_job_reference: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def transition_job(job: GenerationJob, new_state: str, **kwargs: Any) -> GenerationJob:
    """
    Validate and apply a state transition to a GenerationJob.
    Updates timestamp fields based on the new state.
    """
    if not validate_transition(job.state, new_state):
        raise ValueError(f"Invalid transition from {job.state} to {new_state}")
    
    job.state = new_state
    
    if new_state == GenerationJobState.SUBMITTING.value:
        if not job.started_at:
            job.started_at = _now_iso()
    elif new_state in (GenerationJobState.ACCEPTED.value, GenerationJobState.FAILED.value, GenerationJobState.CANCELLED.value):
        job.completed_at = _now_iso()
        
    for k, v in kwargs.items():
        if hasattr(job, k):
            setattr(job, k, v)
            
    return job


@dataclass
class GenerationAccount:
    """Account abstraction for a specific generation provider."""
    account_id: str
    provider: str
    profile_id: int
    display_name: str
    email: str
    priority: int
    enabled: bool = True
    daily_budget: int = 0
    remaining_budget: int = 0
    cooldown_until: Optional[str] = None
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    health_status: str = AccountHealthStatus.HEALTHY.value
    failure_count: int = 0
    total_generations: int = 0
    total_successes: int = 0


@dataclass
class GenerationArtifact:
    """Downloaded file metadata from a successful generation."""
    artifact_id: str
    job_id: str
    file_path: str
    file_size: int
    sha256_hash: str
    duration_sec: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    codec: Optional[str] = None
    verified: bool = False
    verification_errors: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)


@dataclass
class CreditCheck:
    """Pre-generation credit validation."""
    account_id: str
    credits_before: int
    estimated_cost: int
    credits_after: int
    approved: bool
    reason: str


class GenerationProvider(ABC):
    """Abstract base class for generation providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g. 'runway', 'luma')."""
        pass

    @property
    @abstractmethod
    def supports_dry_run(self) -> bool:
        """Whether this provider supports dry run / estimation without billing."""
        pass

    @abstractmethod
    def submit_job(self, job: GenerationJob) -> GenerationJob:
        """Submit a new job to the provider API."""
        pass

    @abstractmethod
    def check_status(self, job: GenerationJob) -> GenerationJob:
        """Poll the provider API for job status and update the job record."""
        pass

    @abstractmethod
    def download_artifact(self, job: GenerationJob, output_dir: Path) -> GenerationArtifact:
        """Download the generated media artifact to the target directory."""
        pass

    @abstractmethod
    def get_account_health(self, account: GenerationAccount) -> GenerationAccount:
        """Sync account status, remaining credits, and health directly from provider."""
        pass
