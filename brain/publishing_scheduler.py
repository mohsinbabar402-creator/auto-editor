"""
Production Scheduling, Durable Queue & Worker Execution — Publishing Scheduler (Phase 14)

PURPOSE:
    Coordinates WHEN queued publishing work becomes executable.
    Monitors SCHEDULED and RETRY_WAIT queue items, transitioning them to READY
    when their target timestamp has arrived. Periodically triggers expired lease
    recovery to reconcile stranded work.

INVARIANTS:
    - The scheduler controls ONLY timing (WHEN).
    - The scheduler NEVER uploads videos or communicates directly with YouTube.
    - The scheduler NEVER bypasses PublishingService or QA.
    - Time is strictly evaluated using timezone-aware UTC.
    - Process and scheduler restarts preserve all schedules without losing work.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.publish_queue import (
    PublishQueue,
    PublishQueueItem,
    QueueState,
    _now_iso,
    _parse_iso,
)


class PublishingScheduler:
    """
    Background scheduler for the durable publish queue.
    Identifies due SCHEDULED items and due RETRY_WAIT items,
    and atomically transitions them to READY.
    """

    def __init__(
        self,
        queue: PublishQueue,
        publishing_service: Optional[Any] = None,
        poll_interval_sec: float = 0.2,
    ) -> None:
        self.queue = queue
        self.publishing_service = publishing_service
        self.poll_interval_sec = poll_interval_sec

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._total_scheduled_ready = 0
        self._total_retry_ready = 0
        self._total_recovered = 0

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def poll_once(self) -> int:
        """
        Execute a single scheduler check cycle.
        Returns total number of items transitioned to READY or recovered.
        """
        now = datetime.now(timezone.utc)
        transitioned = 0

        # 1. Check SCHEDULED items
        all_items = self.queue.all_items()
        for item in all_items:
            if item.status == QueueState.SCHEDULED.value:
                if not item.scheduled_at:
                    self.queue.mark_ready(item.queue_item_id)
                    transitioned += 1
                    self._total_scheduled_ready += 1
                    continue

                try:
                    sched_dt = _parse_iso(item.scheduled_at)
                    if sched_dt <= now:
                        self.queue.mark_ready(item.queue_item_id)
                        transitioned += 1
                        self._total_scheduled_ready += 1
                except Exception:
                    # Malformed scheduled_at timestamp — fail safe to READY so it can be handled
                    self.queue.mark_ready(item.queue_item_id)
                    transitioned += 1
                    self._total_scheduled_ready += 1

            elif item.status == QueueState.RETRY_WAIT.value:
                if not item.next_attempt_at:
                    self.queue.mark_ready(item.queue_item_id)
                    transitioned += 1
                    self._total_retry_ready += 1
                    continue

                try:
                    retry_dt = _parse_iso(item.next_attempt_at)
                    if retry_dt <= now:
                        self.queue.mark_ready(item.queue_item_id)
                        transitioned += 1
                        self._total_retry_ready += 1
                except Exception:
                    self.queue.mark_ready(item.queue_item_id)
                    transitioned += 1
                    self._total_retry_ready += 1

        # 2. Check expired leases & reconcile
        recovered = self.queue.recover_expired_leases(self.publishing_service)
        if recovered:
            transitioned += len(recovered)
            self._total_recovered += len(recovered)

        return transitioned

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as e:
                # Scheduler loop must never crash
                pass
            self._stop_event.wait(self.poll_interval_sec)

    def start(self) -> None:
        """Start the scheduler background loop."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="PublishingSchedulerThread",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout_sec: float = 5.0) -> None:
        """Stop the scheduler background loop cleanly."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=timeout_sec)
            self._thread = None

    def get_stats(self) -> Dict[str, Any]:
        return {
            "is_running": self._running,
            "total_scheduled_ready": self._total_scheduled_ready,
            "total_retry_ready": self._total_retry_ready,
            "total_recovered": self._total_recovered,
        }
