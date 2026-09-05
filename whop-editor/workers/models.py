from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class WorkerStatus(str, Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"
    FAILED = "failed"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Worker:
    id: str
    provider: str  # "antigravity", "gemini", "claude"
    capabilities: List[str]  # e.g. ["EDITING", "RENDERING", "REVIEW"]
    status: str = WorkerStatus.AVAILABLE
    current_job_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now_iso)

    def is_available(self) -> bool:
        return self.status == WorkerStatus.AVAILABLE and self.current_job_id is None

    def can_handle(self, capability: str) -> bool:
        cap_clean = capability.strip().upper()
        worker_caps = {c.strip().upper() for c in self.capabilities}
        if cap_clean in worker_caps:
            return True
        # Aliases
        if "EDITING" in worker_caps and cap_clean in ("PRODUCTION_EDIT", "PUNCH_IN_EDIT", "RENDER"):
            return True
        if "RENDERING" in worker_caps and cap_clean in ("RENDER", "PRODUCTION_EDIT"):
            return True
        return False


@dataclass
class ProductionJob:
    id: str
    campaign_id: str
    job_type: str  # "PUNCH_IN_EDIT", "REVIEW", "REGENERATE"
    input_data: Dict[str, Any]
    output_data: Dict[str, Any] = field(default_factory=dict)
    status: str = JobStatus.PENDING
    assigned_worker_id: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    @classmethod
    def create(cls, campaign_id: str, job_type: str, input_data: Dict[str, Any], max_retries: int = 3) -> "ProductionJob":
        return cls(
            id=f"job_{uuid.uuid4().hex[:10]}",
            campaign_id=campaign_id,
            job_type=job_type,
            input_data=input_data,
            max_retries=max_retries
        )
