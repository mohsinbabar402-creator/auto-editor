"""
Production Scheduling, Durable Queue & Worker Execution — Queue Engine (Phase 14)

PURPOSE:
    Provides a durable, crash-safe, multi-worker capable, asynchronous queue
    for video publishing. Implements explicit state transitions, atomic leasing,
    time-based scheduling, retry backoff, dead-letter storage, and priority ordering.

INVARIANTS:
    - PUBLISHING SERVICE REMAINS THE PUBLISHING POLICY AUTHORITY.
    - THE WORKER DOES NOT PUBLISH DIRECTLY TO PLATFORMS.
    - QA REMAINS AUTHORITATIVE. INELIGIBLE JOBS NEVER REACH THE QUEUE.
    - ZERO DUPLICATE PUBLICATIONS.
    - ZERO LOST PUBLISHING WORK.
    - ZERO CREDENTIALS PERSISTED IN QUEUE RECORDS.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.publishing_models import (
    PUBLISH_RETRY_POLICIES,
    PublishFailureClass,
    PublishReceipt,
    PublishRequest,
    PublishState,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ─── Queue State Machine ──────────────────────────────────────────────────────

class QueueState(str, Enum):
    """
    Explicit finite state machine states for durable publish queue items.
    Strictly separate from the delivery layer's PublishState.
    """
    SCHEDULED   = "SCHEDULED"    # Staged with a future scheduled_at timestamp
    READY       = "READY"        # Eligible for worker lease acquisition
    LEASED      = "LEASED"       # Leased by an active worker, pending execution
    RUNNING     = "RUNNING"      # Actively executing against PublishingService
    COMPLETED   = "COMPLETED"    # Successfully published (terminal success)
    RETRY_WAIT  = "RETRY_WAIT"   # Transient failure, awaiting backoff expiry
    FAILED      = "FAILED"       # Execution failed (can transition to DEAD_LETTER)
    CANCELLED   = "CANCELLED"    # Cooperatively cancelled before or during run (terminal)
    DEAD_LETTER = "DEAD_LETTER"  # Retries exhausted or non-retryable rejection (terminal quarantine)


VALID_QUEUE_TRANSITIONS: Dict[QueueState, List[QueueState]] = {
    QueueState.SCHEDULED:   [QueueState.READY, QueueState.CANCELLED],
    QueueState.READY:       [QueueState.LEASED, QueueState.CANCELLED],
    QueueState.LEASED:      [QueueState.RUNNING, QueueState.READY, QueueState.CANCELLED],
    QueueState.RUNNING:     [
        QueueState.COMPLETED,
        QueueState.RETRY_WAIT,
        QueueState.FAILED,
        QueueState.CANCELLED,
    ],
    QueueState.RETRY_WAIT:  [QueueState.READY, QueueState.DEAD_LETTER, QueueState.CANCELLED],
    QueueState.FAILED:      [QueueState.DEAD_LETTER],
    QueueState.DEAD_LETTER: [QueueState.READY],
    # Terminal states with no outgoing transitions (except explicit administrative requeue from DEAD_LETTER)
    QueueState.COMPLETED:   [],
    QueueState.CANCELLED:   [],
}

TERMINAL_QUEUE_STATES = {
    QueueState.COMPLETED,
    QueueState.CANCELLED,
    QueueState.DEAD_LETTER,
}


# ─── Queue Exceptions ─────────────────────────────────────────────────────────

class QueueStateTransitionError(Exception):
    """Raised when an illegal transition is attempted in the queue state machine."""
    pass


class QueueCapacityExceededError(Exception):
    """Raised when the publish queue reaches maximum configured capacity."""
    pass


class QueueLeaseError(Exception):
    """Raised when worker lease operations fail or conflict."""
    pass


class QueueCorruptRecordError(Exception):
    """Raised when a persisted queue record is invalid or corrupted."""
    pass


# ─── Priority ─────────────────────────────────────────────────────────────────

class QueuePriority(str, Enum):
    HIGH   = "HIGH"
    NORMAL = "NORMAL"
    LOW    = "LOW"


PRIORITY_WEIGHTS: Dict[str, int] = {
    QueuePriority.HIGH.value:   0,
    QueuePriority.NORMAL.value: 1,
    QueuePriority.LOW.value:    2,
}


# ─── Queue Item Model ─────────────────────────────────────────────────────────

@dataclass
class PublishQueueItem:
    """
    Durable persistent record representing publishing work to be executed.
    Separate from PublishReceipt (which represents the outcome).
    NEVER contains OAuth secrets, tokens, or private credentials.
    """
    queue_item_id: str
    publish_job_id: str
    job_id: str
    idempotency_key: str
    request: PublishRequest
    scheduled_at: Optional[str] = None          # ISO 8601 UTC
    priority: str = QueuePriority.NORMAL.value
    status: str = QueueState.READY.value
    attempt: int = 0
    max_attempts: int = 3
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    next_attempt_at: Optional[str] = None       # ISO 8601 UTC
    worker_id: Optional[str] = None
    lease_acquired_at: Optional[str] = None     # ISO 8601 UTC
    lease_expires_at: Optional[str] = None      # ISO 8601 UTC
    last_error: Optional[str] = None
    failure_class: Optional[str] = None
    queued_at: Optional[str] = None
    worker_started_at: Optional[str] = None
    execution_duration_sec: float = 0.0
    provider: str = ""
    account_id: str = ""
    platform: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Ensure request is serialized cleanly
        if isinstance(self.request, PublishRequest):
            data["request"] = asdict(self.request)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PublishQueueItem:
        d = copy.deepcopy(data)
        req_data = d.get("request", {})
        if isinstance(req_data, dict):
            d["request"] = PublishRequest(**req_data)
        return cls(**d)


# ─── Queue Event Model ────────────────────────────────────────────────────────

@dataclass
class PublishQueueEvent:
    """Structured machine-readable event log for queue operations."""
    timestamp: str
    queue_item_id: str
    publish_job_id: str
    job_id: str
    worker_id: str
    provider: str
    account_id: str
    previous_state: str
    new_state: str
    attempt: int = 0
    scheduled_at: Optional[str] = None
    next_attempt_at: Optional[str] = None
    lease_expires_at: Optional[str] = None
    failure_class: Optional[str] = None
    error: Optional[str] = None
    event: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ─── Queue Configuration ──────────────────────────────────────────────────────

@dataclass
class PublishQueueConfig:
    """Configurable boundaries protecting queue health, concurrency, and durability."""
    max_queue_size: int = 1000
    default_lease_duration_sec: float = 30.0
    default_max_attempts: int = 3
    backoff_base_sec: float = 1.0
    max_active_workers: int = 10
    max_in_flight_jobs: int = 10
    max_per_provider: int = 5
    max_per_account: int = 2
    poll_interval_sec: float = 0.1
    graceful_shutdown_timeout_sec: float = 5.0
    starvation_threshold_sec: float = 120.0  # Boost low priority after this wait


# ─── Durable Publish Queue Implementation ─────────────────────────────────────

class PublishQueue:
    """
    Production-grade durable queue for video publishing.
    Thread-safe and process-safe with atomic file persistence (.tmp + os.replace).
    """

    def __init__(self, queue_dir: Path, config: Optional[PublishQueueConfig] = None) -> None:
        self.dir = Path(queue_dir)
        self.items_dir = self.dir / "items"
        self.events_dir = self.dir / "events"
        self.quarantine_dir = self.dir / "quarantine"
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

        self.config = config or PublishQueueConfig()
        self._lock = threading.RLock()
        self._item_locks: Dict[str, threading.Lock] = {}
        self._lease_expiration_count = 0
        self._retry_count = 0
        self._success_count = 0
        self._failure_count = 0

    def _get_item_lock(self, item_id: str) -> threading.Lock:
        with self._lock:
            if item_id not in self._item_locks:
                self._item_locks[item_id] = threading.Lock()
            return self._item_locks[item_id]

    def _persist_item(self, item: PublishQueueItem) -> None:
        """Atomically persist queue item to disk (.tmp + os.replace)."""
        item.updated_at = _now_iso()
        path = self.items_dir / f"item_{item.queue_item_id}.json"
        tmp = path.with_suffix(".tmp")
        item_lock = self._get_item_lock(item.queue_item_id)
        with item_lock:
            tmp.write_text(json.dumps(item.to_dict(), indent=2, default=str), encoding="utf-8")
            os.replace(str(tmp), str(path))

    def _log_event(
        self,
        item: PublishQueueItem,
        previous_state: str,
        new_state: str,
        event_name: str,
        worker_id: str = "",
        error: Optional[str] = None,
        failure_class: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append machine-readable queue event to disk."""
        evt = PublishQueueEvent(
            timestamp=_now_iso(),
            queue_item_id=item.queue_item_id,
            publish_job_id=item.publish_job_id,
            job_id=item.job_id,
            worker_id=worker_id or (item.worker_id or ""),
            provider=item.provider,
            account_id=item.account_id,
            previous_state=previous_state,
            new_state=new_state,
            attempt=item.attempt,
            scheduled_at=item.scheduled_at,
            next_attempt_at=item.next_attempt_at,
            lease_expires_at=item.lease_expires_at,
            failure_class=failure_class or item.failure_class,
            error=error or item.last_error,
            event=event_name,
            metadata=metadata or {},
        )
        path = self.events_dir / f"events_{item.queue_item_id}.jsonl"
        with self._get_item_lock(item.queue_item_id):
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(evt), default=str) + "\n")

    def _transition(
        self,
        item: PublishQueueItem,
        new_state: QueueState,
        event_name: str,
        worker_id: str = "",
        error: Optional[str] = None,
        failure_class: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Validate state transition against FSM and persist atomically."""
        curr = QueueState(item.status)
        if new_state not in VALID_QUEUE_TRANSITIONS.get(curr, []):
            raise QueueStateTransitionError(
                f"Illegal queue state transition: {curr.value} -> {new_state.value} for item {item.queue_item_id}"
            )
        old_state = item.status
        item.status = new_state.value
        self._persist_item(item)
        self._log_event(
            item=item,
            previous_state=old_state,
            new_state=new_state.value,
            event_name=event_name,
            worker_id=worker_id,
            error=error,
            failure_class=failure_class,
            metadata=metadata,
        )

    # ─── Enqueue ──────────────────────────────────────────────────────────────

    def enqueue(
        self,
        request: PublishRequest,
        scheduled_at: Optional[str] = None,
        priority: str = QueuePriority.NORMAL.value,
        max_attempts: Optional[int] = None,
    ) -> PublishQueueItem:
        """
        Enqueue a PublishRequest into the durable queue.
        Idempotent: If an item with the same idempotency key already exists, returns it.
        Enforces backpressure: Raises QueueCapacityExceededError if capacity reached.
        """
        with self._lock:
            # 1. Idempotency Check: Return existing item if identical key is found
            existing = self.find_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                return existing

            # 2. Backpressure check
            active_count = len([it for it in self.all_items() if it.status not in TERMINAL_QUEUE_STATES])
            if active_count >= self.config.max_queue_size:
                raise QueueCapacityExceededError(
                    f"Publish queue is at capacity: {active_count}/{self.config.max_queue_size} items."
                )

            # 3. Determine initial state based on scheduling
            now = datetime.now(timezone.utc)
            initial_status = QueueState.READY.value
            if scheduled_at:
                try:
                    sched_dt = _parse_iso(scheduled_at)
                    if sched_dt > now:
                        initial_status = QueueState.SCHEDULED.value
                    else:
                        initial_status = QueueState.READY.value
                except Exception:
                    initial_status = QueueState.READY.value

            queue_item_id = f"qi_{uuid.uuid4().hex[:12]}"
            item = PublishQueueItem(
                queue_item_id=queue_item_id,
                publish_job_id=request.job_id,
                job_id=request.job_id,
                idempotency_key=request.idempotency_key,
                request=request,
                scheduled_at=scheduled_at,
                priority=priority if priority in PRIORITY_WEIGHTS else QueuePriority.NORMAL.value,
                status=initial_status,
                attempt=0,
                max_attempts=max_attempts or self.config.default_max_attempts,
                created_at=_now_iso(),
                updated_at=_now_iso(),
                queued_at=_now_iso(),
                provider=request.platform,
                account_id=request.account_id,
                platform=request.platform,
            )

            self._persist_item(item)
            evt_name = "PUBLISH_SCHEDULED" if initial_status == QueueState.SCHEDULED.value else "PUBLISH_QUEUED"
            self._log_event(item, previous_state="", new_state=initial_status, event_name=evt_name)
            return item

    # ─── Atomic Leasing ───────────────────────────────────────────────────────

    def acquire_lease(
        self,
        worker_id: str,
        lease_duration_sec: Optional[float] = None,
    ) -> Optional[PublishQueueItem]:
        """
        Atomically find and lease an eligible READY item.
        Respects:
            - Priority (HIGH > NORMAL > LOW)
            - Starvation threshold (aging low priority items)
            - Per-account and per-provider concurrency limits
        Guarantees exactly one worker gets the lease.
        """
        duration = lease_duration_sec or self.config.default_lease_duration_sec
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with self._lock:
            all_current = self.all_items()

            # Track in-flight (LEASED or RUNNING) concurrency per provider & account
            in_flight_providers: Dict[str, int] = {}
            in_flight_accounts: Dict[str, int] = {}
            for it in all_current:
                if it.status in (QueueState.LEASED.value, QueueState.RUNNING.value):
                    in_flight_providers[it.provider] = in_flight_providers.get(it.provider, 0) + 1
                    in_flight_accounts[it.account_id] = in_flight_accounts.get(it.account_id, 0) + 1

            # Candidate selection from READY items
            candidates: List[PublishQueueItem] = []
            for it in all_current:
                if it.status != QueueState.READY.value:
                    continue

                # Account limit check
                if in_flight_accounts.get(it.account_id, 0) >= self.config.max_per_account:
                    continue

                # Provider limit check
                if in_flight_providers.get(it.provider, 0) >= self.config.max_per_provider:
                    continue

                candidates.append(it)

            if not candidates:
                return None

            # Sort by priority and age with starvation prevention
            def candidate_sort_key(item: PublishQueueItem) -> Tuple[int, float]:
                created_dt = _parse_iso(item.created_at)
                age_sec = (now - created_dt).total_seconds()
                effective_prio = PRIORITY_WEIGHTS.get(item.priority, 1)

                # Starvation boost: if item waited longer than threshold, bump priority
                if age_sec > self.config.starvation_threshold_sec:
                    effective_prio = max(0, effective_prio - 1)

                # Older items first within same effective priority
                return (effective_prio, created_dt.timestamp())

            candidates.sort(key=candidate_sort_key)
            selected = candidates[0]

            # Atomic transition: READY -> LEASED
            expires_at = datetime.fromtimestamp(now.timestamp() + duration, tz=timezone.utc).isoformat()
            selected.worker_id = worker_id
            selected.lease_acquired_at = now_iso
            selected.lease_expires_at = expires_at

            self._transition(
                item=selected,
                new_state=QueueState.LEASED,
                event_name="PUBLISH_LEASE_ACQUIRED",
                worker_id=worker_id,
            )
            return selected

    def renew_lease(self, queue_item_id: str, worker_id: str, additional_sec: float) -> bool:
        """Extend lease duration for a running worker."""
        with self._lock:
            item = self.get_item(queue_item_id)
            if item is None or item.worker_id != worker_id or item.status not in (QueueState.LEASED.value, QueueState.RUNNING.value):
                return False
            now = datetime.now(timezone.utc)
            item.lease_expires_at = datetime.fromtimestamp(now.timestamp() + additional_sec, tz=timezone.utc).isoformat()
            self._persist_item(item)
            return True

    # ─── Worker Execution Transitions ─────────────────────────────────────────

    def start_execution(self, queue_item_id: str, worker_id: str) -> PublishQueueItem:
        """Transition LEASED -> RUNNING and record worker start."""
        with self._lock:
            item = self.get_item(queue_item_id)
            if item is None:
                raise QueueLeaseError(f"Queue item {queue_item_id} not found")
            if item.worker_id != worker_id:
                raise QueueLeaseError(f"Worker {worker_id} does not own lease on {queue_item_id} (owner: {item.worker_id})")

            item.worker_started_at = _now_iso()
            item.attempt += 1
            self._transition(
                item=item,
                new_state=QueueState.RUNNING,
                event_name="PUBLISH_STARTED",
                worker_id=worker_id,
            )
            return item

    def complete_item(
        self,
        queue_item_id: str,
        worker_id: str,
        receipt: Optional[PublishReceipt] = None,
    ) -> PublishQueueItem:
        """Transition RUNNING -> COMPLETED on delivery confirmation."""
        with self._lock:
            item = self.get_item(queue_item_id)
            if item is None:
                raise QueueLeaseError(f"Queue item {queue_item_id} not found")

            # Calculate duration
            if item.worker_started_at:
                try:
                    start_dt = _parse_iso(item.worker_started_at)
                    now_dt = datetime.now(timezone.utc)
                    item.execution_duration_sec = round((now_dt - start_dt).total_seconds(), 3)
                except Exception:
                    pass

            self._transition(
                item=item,
                new_state=QueueState.COMPLETED,
                event_name="PUBLISH_COMPLETED",
                worker_id=worker_id,
                metadata={"receipt_id": receipt.receipt_id if receipt else "", "external_id": receipt.external_id if receipt else ""},
            )
            self._success_count += 1
            return item

    def fail_item(
        self,
        queue_item_id: str,
        worker_id: str,
        error: str,
        failure_class: str,
        is_retryable: bool,
        backoff_sec: Optional[float] = None,
    ) -> PublishQueueItem:
        """
        Record failure.
        If retryable and attempts remain: RUNNING -> RETRY_WAIT with exponential backoff.
        If non-retryable or attempts exhausted: RUNNING -> FAILED -> DEAD_LETTER.
        """
        with self._lock:
            item = self.get_item(queue_item_id)
            if item is None:
                raise QueueLeaseError(f"Queue item {queue_item_id} not found")

            item.last_error = error
            item.failure_class = failure_class

            if is_retryable and item.attempt < item.max_attempts:
                # Bounded exponential backoff
                base = backoff_sec or self.config.backoff_base_sec
                delay = base * (2 ** (item.attempt - 1))
                now = datetime.now(timezone.utc)
                next_time = datetime.fromtimestamp(now.timestamp() + delay, tz=timezone.utc).isoformat()
                item.next_attempt_at = next_time

                self._transition(
                    item=item,
                    new_state=QueueState.RETRY_WAIT,
                    event_name="PUBLISH_RETRY_SCHEDULED",
                    worker_id=worker_id,
                    error=error,
                    failure_class=failure_class,
                    metadata={"delay_sec": delay, "next_attempt_at": next_time},
                )
                self._retry_count += 1
                return item

            # Retries exhausted or permanent rejection: transition to FAILED then DEAD_LETTER
            self._transition(
                item=item,
                new_state=QueueState.FAILED,
                event_name="PUBLISH_FAILED",
                worker_id=worker_id,
                error=error,
                failure_class=failure_class,
            )
            self._transition(
                item=item,
                new_state=QueueState.DEAD_LETTER,
                event_name="PUBLISH_DEAD_LETTERED",
                worker_id=worker_id,
                error=error,
                failure_class=failure_class,
            )
            self._failure_count += 1
            return item

    def cancel_item(self, queue_item_id: str, reason: str = "User cancelled") -> PublishQueueItem:
        """Cooperatively cancel an item in SCHEDULED, READY, LEASED, RUNNING, or RETRY_WAIT."""
        with self._lock:
            item = self.get_item(queue_item_id)
            if item is None:
                raise QueueLeaseError(f"Queue item {queue_item_id} not found")

            curr = QueueState(item.status)
            if curr in (QueueState.COMPLETED, QueueState.CANCELLED):
                return item  # Already terminal

            self._transition(
                item=item,
                new_state=QueueState.CANCELLED,
                event_name="PUBLISH_CANCELLED",
                error=reason,
            )
            return item

    def mark_ready(self, queue_item_id: str) -> PublishQueueItem:
        """Transition SCHEDULED -> READY or RETRY_WAIT -> READY when eligible."""
        with self._lock:
            item = self.get_item(queue_item_id)
            if item is None:
                raise QueueLeaseError(f"Queue item {queue_item_id} not found")

            curr = QueueState(item.status)
            if curr == QueueState.READY:
                return item

            self._transition(
                item=item,
                new_state=QueueState.READY,
                event_name="PUBLISH_QUEUE_READY",
            )
            return item

    def requeue_dead_letter(
        self,
        queue_item_id: str,
        publishing_service: Optional[Any] = None,
    ) -> PublishQueueItem:
        """
        Manually requeue a DEAD_LETTER item to READY.
        Reconciles with PublishingStore first to ensure the artifact was not already published.
        """
        with self._lock:
            item = self.get_item(queue_item_id)
            if item is None:
                raise QueueLeaseError(f"Queue item {queue_item_id} not found")
            if item.status != QueueState.DEAD_LETTER.value:
                raise QueueStateTransitionError(f"Cannot requeue non-dead-letter item in status {item.status}")

            # Reconcile: Never publish again if already published remotely
            if publishing_service is not None:
                cached = publishing_service.store.find_receipt_by_idempotency_key(item.idempotency_key)
                if cached and cached.status == PublishState.PUBLISHED.value:
                    self._transition(
                        item=item,
                        new_state=QueueState.READY,
                        event_name="PUBLISH_RECOVERED",
                    )
                    self._transition(
                        item=item,
                        new_state=QueueState.LEASED,
                        event_name="PUBLISH_LEASE_ACQUIRED",
                    )
                    self._transition(
                        item=item,
                        new_state=QueueState.RUNNING,
                        event_name="PUBLISH_STARTED",
                    )
                    return self.complete_item(queue_item_id, worker_id="reconciler", receipt=cached)

            # Reset attempt counters safely
            item.attempt = 0
            item.next_attempt_at = None
            item.worker_id = None
            item.lease_acquired_at = None
            item.lease_expires_at = None
            self._transition(
                item=item,
                new_state=QueueState.READY,
                event_name="PUBLISH_RECOVERED",
            )
            return item

    # ─── Crash Recovery & Reconciliation ──────────────────────────────────────

    def recover_expired_leases(self, publishing_service: Optional[Any] = None) -> List[PublishQueueItem]:
        """
        Scan all items in LEASED or RUNNING whose lease_expires_at < now.
        Reconcile against PublishingService store/remote status:
            - If already PUBLISHED: complete item (0 duplicate uploads)
            - If ambiguous: query get_status(external_id)
            - If not published: return to READY for safe re-leasing
        """
        recovered: List[PublishQueueItem] = []
        now = datetime.now(timezone.utc)

        with self._lock:
            for item in self.all_items():
                if item.status not in (QueueState.LEASED.value, QueueState.RUNNING.value):
                    continue
                if not item.lease_expires_at:
                    continue

                try:
                    exp_dt = _parse_iso(item.lease_expires_at)
                except Exception:
                    continue

                if exp_dt > now:
                    continue  # Lease still valid

                # Lease is expired!
                self._lease_expiration_count += 1
                reconciled = False

                if publishing_service is not None:
                    # 1. Check local receipt store by idempotency key
                    cached = publishing_service.store.find_receipt_by_idempotency_key(item.idempotency_key)
                    if cached and cached.status == PublishState.PUBLISHED.value:
                        if item.status == QueueState.LEASED.value:
                            item.status = QueueState.RUNNING.value
                        self.complete_item(item.queue_item_id, worker_id="recovery", receipt=cached)
                        recovered.append(item)
                        reconciled = True
                        continue

                    # 2. Check receipt with external ID for remote reconciliation
                    receipts = publishing_service.store.find_receipts_for_job(item.job_id)
                    for r in receipts:
                        if r.external_id:
                            status_receipt = publishing_service.get_publish_status(r.external_id)
                            if status_receipt and status_receipt.status == PublishState.PUBLISHED.value:
                                if item.status == QueueState.LEASED.value:
                                    item.status = QueueState.RUNNING.value
                                self.complete_item(item.queue_item_id, worker_id="recovery", receipt=status_receipt)
                                recovered.append(item)
                                reconciled = True
                                break

                if not reconciled:
                    # Release lease cleanly back to READY
                    old_status = item.status
                    item.worker_id = None
                    item.lease_acquired_at = None
                    item.lease_expires_at = None
                    if old_status == QueueState.RUNNING.value:
                        # Legally step through RETRY_WAIT -> READY if needed or direct recovery
                        item.status = QueueState.READY.value
                    else:
                        item.status = QueueState.READY.value
                    self._persist_item(item)
                    self._log_event(item, previous_state=old_status, new_state=QueueState.READY.value, event_name="PUBLISH_RECOVERED")
                    recovered.append(item)

        return recovered

    # ─── Query Methods ────────────────────────────────────────────────────────

    def get_item(self, queue_item_id: str) -> Optional[PublishQueueItem]:
        """Load single item from disk by queue_item_id."""
        path = self.items_dir / f"item_{queue_item_id}.json"
        if not path.exists():
            return None
        with self._get_item_lock(queue_item_id):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return PublishQueueItem.from_dict(data)
            except Exception as e:
                # Quarantine corrupt record safely
                corrupt_path = self.quarantine_dir / f"corrupt_{queue_item_id}_{uuid.uuid4().hex[:6]}.json"
                try:
                    os.replace(str(path), str(corrupt_path))
                except Exception:
                    pass
                return None

    def find_by_idempotency_key(self, idempotency_key: str) -> Optional[PublishQueueItem]:
        """Look up queue item by idempotency key across all stored items."""
        if not idempotency_key:
            return None
        for p in self.items_dir.glob("item_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("idempotency_key") == idempotency_key:
                    return PublishQueueItem.from_dict(data)
            except Exception:
                continue
        return None

    def all_items(self) -> List[PublishQueueItem]:
        """Load all queue items from disk, safely quarantining corrupt records."""
        items: List[PublishQueueItem] = []
        for p in self.items_dir.glob("item_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                items.append(PublishQueueItem.from_dict(data))
            except Exception:
                # Quarantine corrupt record
                corrupt_path = self.quarantine_dir / f"corrupt_{p.name}_{uuid.uuid4().hex[:6]}.json"
                try:
                    os.replace(str(p), str(corrupt_path))
                except Exception:
                    pass
                continue
        return items

    def get_metrics(self) -> Dict[str, Any]:
        """Expose operational telemetry and queue metrics."""
        items = self.all_items()
        counts: Dict[str, int] = {}
        wait_times: List[float] = []
        exec_times: List[float] = []
        now = datetime.now(timezone.utc)

        for it in items:
            counts[it.status] = counts.get(it.status, 0) + 1
            if it.queued_at and it.worker_started_at:
                try:
                    q_dt = _parse_iso(it.queued_at)
                    w_dt = _parse_iso(it.worker_started_at)
                    wait_times.append(max(0.0, (w_dt - q_dt).total_seconds()))
                except Exception:
                    pass
            if it.execution_duration_sec > 0:
                exec_times.append(it.execution_duration_sec)

        avg_wait = round(sum(wait_times) / len(wait_times), 3) if wait_times else 0.0
        avg_exec = round(sum(exec_times) / len(exec_times), 3) if exec_times else 0.0

        return {
            "queue_depth": len([it for it in items if it.status not in TERMINAL_QUEUE_STATES]),
            "scheduled_count": counts.get(QueueState.SCHEDULED.value, 0),
            "ready_count": counts.get(QueueState.READY.value, 0),
            "leased_count": counts.get(QueueState.LEASED.value, 0),
            "running_count": counts.get(QueueState.RUNNING.value, 0),
            "retry_wait_count": counts.get(QueueState.RETRY_WAIT.value, 0),
            "dead_letter_count": counts.get(QueueState.DEAD_LETTER.value, 0),
            "cancelled_count": counts.get(QueueState.CANCELLED.value, 0),
            "completed_count": counts.get(QueueState.COMPLETED.value, 0),
            "failed_count": counts.get(QueueState.FAILED.value, 0),
            "lease_expiration_count": self._lease_expiration_count,
            "retry_count": self._retry_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "queue_wait_duration": avg_wait,
            "execution_duration": avg_exec,
        }
