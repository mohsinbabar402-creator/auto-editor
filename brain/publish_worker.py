"""
Production Scheduling, Durable Queue & Worker Execution — Publish Worker (Phase 14)

PURPOSE:
    Execution agent that polls the durable queue, acquires an atomic lease,
    and invokes the PublishingService to deliver approved media to external platforms.

INVARIANTS:
    - THE WORKER IS AN EXECUTION MECHANISM, NOT A PUBLISHING POLICY LAYER.
    - The worker NEVER calls YouTube or external APIs directly.
    - The worker delegates all publishing logic to PublishingService.
    - The worker never overrides QA or publishes unapproved artifacts.
    - Atomic leasing ensures zero duplicate executions across concurrent workers.
    - Pre-execution idempotency checks guarantee zero duplicate uploads.
    - Graceful shutdown finishes in-flight jobs or safely preserves state.
"""

from __future__ import annotations

import copy
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.publish_queue import (
    PublishQueue,
    PublishQueueItem,
    QueueLeaseError,
    QueueState,
    _now_iso,
)
from brain.publishing_models import (
    PUBLISH_RETRY_POLICIES,
    PublishFailureClass,
    PublishReceipt,
    PublishState,
)
from brain.publishing_service import PublishingService


class PublishWorker:
    """
    Worker executing publishing tasks from the durable publish queue.
    """

    def __init__(
        self,
        worker_id: str,
        queue: PublishQueue,
        publishing_service: PublishingService,
        poll_interval_sec: float = 0.1,
    ) -> None:
        self.worker_id = worker_id
        self.queue = queue
        self.publishing_service = publishing_service
        self.poll_interval_sec = poll_interval_sec

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._current_item_id: Optional[str] = None
        self._success_count = 0
        self._failure_count = 0

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_item_id(self) -> Optional[str]:
        with self._lock:
            return self._current_item_id

    def poll_once(self) -> Optional[PublishReceipt]:
        """
        Execute a single worker poll cycle:
            1. Atomically acquire lease on an eligible READY queue item.
            2. Transition to RUNNING.
            3. Perform pre-execution receipt check (Idempotency / crash recovery).
            4. Execute publication via PublishingService.
            5. Transition item based on outcome (COMPLETED, RETRY_WAIT, DEAD_LETTER).
            6. Return PublishReceipt or None if queue was empty.
        """
        if self._stop_event.is_set():
            return None

        # 1. Atomic lease acquisition
        item = self.queue.acquire_lease(self.worker_id)
        if item is None:
            return None

        with self._lock:
            self._current_item_id = item.queue_item_id

        try:
            # 2. Transition LEASED -> RUNNING
            self.queue.start_execution(item.queue_item_id, self.worker_id)

            # 3. Receipt-First Check: If already published, complete immediately!
            cached = self.publishing_service.store.find_receipt_by_idempotency_key(item.idempotency_key)
            if cached and cached.status == PublishState.PUBLISHED.value:
                self.queue.complete_item(item.queue_item_id, self.worker_id, receipt=cached)
                self._success_count += 1
                return cached

            # 4. Authority Call: PublishingService publishes the request
            receipt = self.publishing_service.publish(item.request)

            # 5. Outcome evaluation
            if receipt.status == PublishState.PUBLISHED.value:
                self.queue.complete_item(item.queue_item_id, self.worker_id, receipt=receipt)
                self._success_count += 1
                return receipt

            elif receipt.status == PublishState.PUBLISH_REJECTED.value:
                # Permanent rejection (policy, auth, bad meta) -> non-retryable DEAD_LETTER
                err_msg = "; ".join(receipt.errors) if receipt.errors else "Provider permanently rejected"
                self.queue.fail_item(
                    queue_item_id=item.queue_item_id,
                    worker_id=self.worker_id,
                    error=err_msg,
                    failure_class=PublishFailureClass.PROVIDER_REJECTED.value,
                    is_retryable=False,
                )
                self._failure_count += 1
                return receipt

            elif receipt.status == PublishState.PUBLISH_CANCELLED.value:
                self.queue.cancel_item(item.queue_item_id, reason="Delivery cancelled on platform")
                return receipt

            else:
                # PublishState.PUBLISH_FAILED or transient error
                err_msg = "; ".join(receipt.errors) if receipt.errors else "Publishing failed"
                # Determine retryability from failure class or default policy
                fail_cls = PublishFailureClass.TRANSIENT_PROVIDER_ERROR.value
                for known_cls in PublishFailureClass:
                    if known_cls.value in err_msg or (receipt.errors and any(known_cls.value in e for e in receipt.errors)):
                        fail_cls = known_cls.value
                        break

                is_retryable = PUBLISH_RETRY_POLICIES.get(fail_cls, {}).get("retryable", False)
                # If error mentions timeout or network, ensure retryable
                if any(k in err_msg.lower() for k in ["timeout", "connection", "network", "retry", "500", "503", "socket"]):
                    is_retryable = True
                    fail_cls = PublishFailureClass.NETWORK_ERROR.value

                self.queue.fail_item(
                    queue_item_id=item.queue_item_id,
                    worker_id=self.worker_id,
                    error=err_msg,
                    failure_class=fail_cls,
                    is_retryable=is_retryable,
                )
                self._failure_count += 1
                return receipt

        except Exception as exc:
            # Unexpected exception must never leave job stuck in RUNNING or crash the worker
            err_msg = f"Unexpected worker error: {exc}"
            try:
                self.queue.fail_item(
                    queue_item_id=item.queue_item_id,
                    worker_id=self.worker_id,
                    error=err_msg,
                    failure_class=PublishFailureClass.INTERNAL_ERROR.value,
                    is_retryable=False,
                )
            except Exception:
                pass
            self._failure_count += 1
            return None

        finally:
            with self._lock:
                self._current_item_id = None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                receipt = self.poll_once()
                if receipt is None:
                    # Queue was empty, sleep poll interval
                    self._stop_event.wait(self.poll_interval_sec)
            except Exception:
                self._stop_event.wait(self.poll_interval_sec)

    def start(self) -> None:
        """Start the worker loop in a background daemon thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"PublishWorkerThread_{self.worker_id}",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout_sec: float = 5.0) -> None:
        """Signal worker to finish current job and shutdown cleanly."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=timeout_sec)
            self._thread = None


# ─── Worker Pool Helper ────────────────────────────────────────────────────────

class PublishWorkerPool:
    """
    Manages a pool of concurrent PublishWorkers.
    """

    def __init__(
        self,
        worker_count: int,
        queue: PublishQueue,
        publishing_service: PublishingService,
        poll_interval_sec: float = 0.1,
    ) -> None:
        self.worker_count = worker_count
        self.queue = queue
        self.publishing_service = publishing_service
        self.poll_interval_sec = poll_interval_sec
        self.workers: List[PublishWorker] = []
        for i in range(worker_count):
            w_id = f"worker_{i + 1}_{uuid.uuid4().hex[:6]}"
            self.workers.append(PublishWorker(
                worker_id=w_id,
                queue=queue,
                publishing_service=publishing_service,
                poll_interval_sec=poll_interval_sec,
            ))

    def start(self) -> None:
        for w in self.workers:
            w.start()

    def stop(self, timeout_sec: float = 5.0) -> None:
        for w in self.workers:
            w.stop(timeout_sec=timeout_sec)

    def poll_all_once(self) -> List[PublishReceipt]:
        """Synchronously poll once on each worker in the pool."""
        receipts = []
        for w in self.workers:
            r = w.poll_once()
            if r is not None:
                receipts.append(r)
        return receipts
