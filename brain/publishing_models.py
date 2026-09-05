"""
Production Publishing & Delivery Layer — Data Models (Phase 12)

PURPOSE:
    Typed contracts for the publishing state machine, requests, receipts,
    failure classifications, results, and provider interfaces.

INVARIANTS:
    - THE PUBLISHER DOES NOT GET TO OVERRIDE QA.
    - An artifact is NEVER published unless final QA explicitly approved it.
    - All state transitions are strictly validated.
    - Idempotency is mandatory for every delivery operation.
    - Artifact immutability is verified before delivery.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── Publishing States ────────────────────────────────────────────────────────

class PublishState(str, Enum):
    """
    Explicit finite state machine states for the delivery layer.
    Transitions are validated against VALID_PUBLISH_TRANSITIONS before being applied.
    """
    PUBLISH_READY     = "PUBLISH_READY"       # Passed eligibility, integrity & QA checks
    PUBLISH_QUEUED    = "PUBLISH_QUEUED"      # Enqueued, awaiting publisher slot/semaphore
    PUBLISHING        = "PUBLISHING"          # Transmitting to provider
    PUBLISHED         = "PUBLISHED"           # Provider confirmed acceptance (terminal success)
    PUBLISH_FAILED    = "PUBLISH_FAILED"      # Delivery failed (terminal or awaiting retry)
    PUBLISH_RETRYING  = "PUBLISH_RETRYING"    # Transient error, backing off for retry
    PUBLISH_REJECTED  = "PUBLISH_REJECTED"    # Provider permanently rejected (policy, auth, bad meta)
    PUBLISH_CANCELLED = "PUBLISH_CANCELLED"   # Cooperatively aborted before completion


# Strict transition graph for publishing
VALID_PUBLISH_TRANSITIONS: Dict[PublishState, List[PublishState]] = {
    PublishState.PUBLISH_READY:     [PublishState.PUBLISH_QUEUED, PublishState.PUBLISH_CANCELLED],
    PublishState.PUBLISH_QUEUED:    [PublishState.PUBLISHING, PublishState.PUBLISH_CANCELLED],
    PublishState.PUBLISHING:        [
        PublishState.PUBLISHED,
        PublishState.PUBLISH_FAILED,
        PublishState.PUBLISH_RETRYING,
        PublishState.PUBLISH_REJECTED,
        PublishState.PUBLISH_CANCELLED,
    ],
    PublishState.PUBLISH_FAILED:    [PublishState.PUBLISH_RETRYING],
    PublishState.PUBLISH_RETRYING:  [PublishState.PUBLISHING, PublishState.PUBLISH_CANCELLED],
    # Terminal states
    PublishState.PUBLISHED:         [],
    PublishState.PUBLISH_REJECTED:  [],
    PublishState.PUBLISH_CANCELLED: [],
}

TERMINAL_PUBLISH_STATES = {
    PublishState.PUBLISHED,
    PublishState.PUBLISH_REJECTED,
    PublishState.PUBLISH_CANCELLED,
}


# ─── Failure Classification ───────────────────────────────────────────────────

class PublishFailureClass(str, Enum):
    """
    Comprehensive publishing failure classification per Phase 12 specification.
    """
    TRANSIENT_PROVIDER_ERROR = "TRANSIENT_PROVIDER_ERROR" # 5xx server error, temporary glitch
    RATE_LIMITED             = "RATE_LIMITED"             # 429 Too Many Requests, quota pause
    NETWORK_ERROR            = "NETWORK_ERROR"            # Connection reset, socket error
    TIMEOUT                  = "TIMEOUT"                  # Ambiguous or connection timeout
    AUTHENTICATION_ERROR     = "AUTHENTICATION_ERROR"     # 401 Unauthorized, invalid token
    AUTHORIZATION_ERROR      = "AUTHORIZATION_ERROR"      # 403 Forbidden, missing permissions
    INVALID_REQUEST          = "INVALID_REQUEST"          # Malformed payload
    INVALID_METADATA         = "INVALID_METADATA"         # Bad tags, title too long
    ARTIFACT_UNAVAILABLE     = "ARTIFACT_UNAVAILABLE"     # File missing on disk
    ARTIFACT_INTEGRITY_ERROR = "ARTIFACT_INTEGRITY_ERROR" # Hash mismatch or mutation after QA
    PROVIDER_REJECTED        = "PROVIDER_REJECTED"        # Policy violation, banned terms
    PROVIDER_UNKNOWN         = "PROVIDER_UNKNOWN"         # Ambiguous response requiring reconciliation
    CONFIGURATION_ERROR      = "CONFIGURATION_ERROR"      # Missing account or provider setup
    INTERNAL_ERROR           = "INTERNAL_ERROR"           # Local logic or OS error
    CANCELLED                = "CANCELLED"                # Cooperatively aborted


PUBLISH_RETRY_POLICIES: Dict[str, Dict[str, Any]] = {
    PublishFailureClass.TRANSIENT_PROVIDER_ERROR: {"max_attempts": 3, "backoff_sec": 2.0, "retryable": True},
    PublishFailureClass.RATE_LIMITED:             {"max_attempts": 3, "backoff_sec": 5.0, "retryable": True},
    PublishFailureClass.NETWORK_ERROR:            {"max_attempts": 3, "backoff_sec": 2.0, "retryable": True},
    PublishFailureClass.TIMEOUT:                  {"max_attempts": 3, "backoff_sec": 3.0, "retryable": True},
    PublishFailureClass.AUTHENTICATION_ERROR:     {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.AUTHORIZATION_ERROR:      {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.INVALID_REQUEST:          {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.INVALID_METADATA:         {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.ARTIFACT_UNAVAILABLE:     {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.ARTIFACT_INTEGRITY_ERROR: {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.PROVIDER_REJECTED:        {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.PROVIDER_UNKNOWN:         {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.CONFIGURATION_ERROR:      {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.INTERNAL_ERROR:           {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
    PublishFailureClass.CANCELLED:                {"max_attempts": 1, "backoff_sec": 0.0, "retryable": False},
}


# ─── Contracts: Request & Receipt ──────────────────────────────────────────────

@dataclass
class PublishRequest:
    """
    Structured request representing an approved, immutable artifact for delivery.
    References the exact approved artifact hash.
    """
    job_id: str
    episode_id: str
    clip_id: str
    account_id: str
    platform: str                         # e.g., "youtube_shorts", "tiktok"
    artifact_path: str                    # Local path to approved video
    artifact_hash: str                    # SHA-256 digest of approved video
    title: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    visibility: str = "public"            # "public", "unlisted", "private"
    scheduled_at: Optional[str] = None    # ISO 8601 string if scheduling
    metadata: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""             # Deterministic cryptographic key
    execution_mode: str = "PRODUCTION"    # PRODUCTION, TEST, BENCHMARK, SYNTHETIC, DRY_RUN


@dataclass
class PublishReceipt:
    """
    Immutable proof of delivery attempt/completion returned by a publisher.
    Never a bare boolean.
    """
    receipt_id: str
    job_id: str
    clip_id: str
    platform: str
    provider: str                         # Name of the publisher implementation
    external_id: str                      # Platform's content ID (e.g. YouTube video ID)
    status: str                           # PublishState string
    published_at: str                     # ISO 8601
    artifact_hash: str                    # SHA-256 of the delivered video
    idempotency_key: str
    provider_metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    attempt_count: int = 1
    duration_sec: float = 0.0


@dataclass
class PublishEvent:
    """Structured machine-readable event log for delivery observability."""
    timestamp: str
    job_id: str
    episode_id: str
    clip_id: str
    platform: str
    provider: str
    previous_state: str
    new_state: str
    event: str
    attempt: int = 1
    duration_sec: float = 0.0
    idempotency_key: str = ""
    artifact_hash: str = ""
    result: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishingResult:
    """Structured single-job publishing result."""
    job_id: str
    state: str
    provider: str
    platform: str
    receipt: Optional[PublishReceipt]
    attempts: int = 1
    artifact_hash: str = ""
    duration_sec: float = 0.0
    errors: List[str] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BatchPublishingResult:
    """Aggregated result for a batch publishing operation."""
    batch_id: str
    total: int = 0
    published: int = 0
    failed: int = 0
    rejected: int = 0
    retrying: int = 0
    cancelled: int = 0
    duration_sec: float = 0.0
    results: List[PublishingResult] = field(default_factory=list)


# ─── Publisher Interface ───────────────────────────────────────────────────────

class PublisherInterface(ABC):
    """
    Abstract delivery provider contract.
    The publishing layer interacts ONLY through this interface.
    """
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name, e.g. 'YouTubePublisher', 'MockPublisher'."""
        ...

    @abstractmethod
    def publish(self, request: Any, metadata: Optional[Dict[str, Any]] = None) -> PublishReceipt:
        """Deliver the approved artifact to the platform. Returns a PublishReceipt."""
        ...

    @abstractmethod
    def get_status(self, external_id: str) -> Optional[PublishReceipt]:
        """Query platform for live delivery status using the external ID."""
        ...

    @abstractmethod
    def cancel(self, external_id: str) -> bool:
        """Request cooperative platform cancellation if still in queue/processing."""
        ...


# ─── Exceptions ───────────────────────────────────────────────────────────────

class PublishEligibilityError(Exception):
    """Raised when a job fails eligibility criteria (e.g. QA fail, missing artifact, hash mismatch)."""
    pass


class PublishStateTransitionError(Exception):
    """Raised when an illegal transition is attempted in the publishing state machine."""
    pass


class PublishIdempotencyError(Exception):
    """Raised on idempotency collision or state conflict."""
    pass


class PublishProviderError(Exception):
    """Raised when a provider rejects or fails a publish request."""
    def __init__(self, message: str, failure_class: str = PublishFailureClass.TRANSIENT_PROVIDER_ERROR.value):
        super().__init__(message)
        self.failure_class = failure_class
