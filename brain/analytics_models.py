"""
Production Analytics & Feedback Boundary — Data Models (Phase 15)

PURPOSE:
    Typed contracts for provider-agnostic video performance metrics,
    historical snapshots, webhooks, and creative memory feedback.

INVARIANTS:
    - METRICS ARE RECORDED FACTS, NEVER FABRICATED ESTIMATES.
    - Strict analytics boundary: delivery layer records delivery receipts;
      analytics layer records remote platform performance.
    - Zero credentials in snapshot records or logs.
    - Synthetic test data is explicitly flagged (is_synthetic=True).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Performance Metrics ──────────────────────────────────────────────────────

@dataclass
class PerformanceMetrics:
    """
    Standardized, provider-agnostic performance metrics retrieved from remote platforms.
    NEVER fabricated by local heuristics or delivery receipts.
    """
    external_id: str
    platform: str
    provider: str
    account_id: str
    views: int = 0
    watch_time_sec: float = 0.0
    average_view_duration_sec: float = 0.0
    average_percentage_viewed: float = 0.0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    subscribers_gained: int = 0
    retention_curve: List[Dict[str, float]] = field(default_factory=list) # [{"time_sec": 0.0, "retention_pct": 100.0}, ...]
    recorded_at: str = field(default_factory=_now_iso)
    is_synthetic: bool = False  # Set to True ONLY in test mocks
    provider_raw_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalyticsSnapshot:
    """
    Point-in-time snapshot of metrics for an approved and published video.
    """
    snapshot_id: str
    job_id: str
    clip_id: str
    external_id: str
    metrics: PerformanceMetrics
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if isinstance(self.metrics, PerformanceMetrics):
            data["metrics"] = asdict(self.metrics)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AnalyticsSnapshot:
        d = dict(data)
        if isinstance(d.get("metrics"), dict):
            d["metrics"] = PerformanceMetrics(**d["metrics"])
        return cls(**d)


# ─── Webhook Models ───────────────────────────────────────────────────────────

class WebhookEventType(str, Enum):
    VIDEO_PROCESSED     = "VIDEO_PROCESSED"      # Platform finished HD/4K processing
    VIDEO_REJECTED      = "VIDEO_REJECTED"       # Platform policy/format rejection
    COPYRIGHT_CLAIM     = "COPYRIGHT_CLAIM"      # Content ID match or claim
    VISIBILITY_CHANGED  = "VISIBILITY_CHANGED"   # Public/Private status shift
    MONETIZATION_STATUS = "MONETIZATION_STATUS"  # Ad suitability / monetization update


@dataclass
class WebhookEvent:
    """
    Normalized remote provider callback payload.
    """
    event_id: str
    provider: str
    account_id: str
    external_id: str
    event_type: str                              # WebhookEventType value
    status: str
    payload: Dict[str, Any] = field(default_factory=dict)
    received_at: str = field(default_factory=_now_iso)
    signature: str = ""


# ─── Analytics Provider Interface ─────────────────────────────────────────────

class AnalyticsInterface(ABC):
    """
    Abstract contract for external analytics providers.
    """
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name, e.g. 'YouTubeAnalyticsProvider', 'MockAnalyticsProvider'."""
        ...

    @abstractmethod
    def get_video_metrics(self, external_id: str, account_id: str) -> Optional[PerformanceMetrics]:
        """Fetch live engagement and audience retention metrics for a video."""
        ...

    @abstractmethod
    def get_batch_metrics(self, external_ids: List[str], account_id: str) -> Dict[str, PerformanceMetrics]:
        """Fetch metrics for multiple videos in a single batch request."""
        ...
