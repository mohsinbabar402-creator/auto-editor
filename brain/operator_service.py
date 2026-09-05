"""
Unified Production Engine & Operator Management Surface (Phase 16)

PURPOSE:
    Provides the single unified service boundary connecting the complete production
    lifecycle: Orchestration -> QA -> Durable Queue -> Workers -> Real Providers ->
    Remote Webhooks -> Performance Analytics -> Creative Memory.

INVARIANTS:
    - Single point of entry for operations and automated scheduling.
    - Preserves QA authority and immutability invariants.
    - Exposes operational telemetry, health checks, and administration APIs.
    - Zero secrets in state queries or operational logs.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.analytics_models import PerformanceMetrics
from brain.analytics_service import AnalyticsService, MockAnalyticsProvider
from brain.orchestrator import BatchProductionOrchestrator, RendererInterface, RenderRequest, RenderResult
from brain.orchestrator_models import BatchJob, ExecutionMode, JobState, ProductionJob
from brain.provider_credentials import CredentialStore
from brain.publish_queue import PublishQueue, PublishQueueConfig, PublishQueueItem, QueuePriority, QueueState
from brain.publish_worker import PublishWorker, PublishWorkerPool
from brain.publishing_models import PublishReceipt, PublishRequest, PublishState
from brain.publishing_scheduler import PublishingScheduler
from brain.publishing_service import PublishingService
from brain.webhook_reconciler import WebhookReconciler


class DefaultRenderer(RendererInterface):
    @property
    def name(self) -> str:
        return "DefaultRenderer"

    def render(self, request: RenderRequest) -> RenderResult:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(b"\x00" * 4096)
        return RenderResult(success=True, output_path=request.output_path, renderer_name=self.name)


@dataclass
class SystemHealthReport:
    """Operational health snapshot of all production subsystems."""
    timestamp: str
    status: str                                  # "HEALTHY", "DEGRADED", "UNHEALTHY"
    queue_depth: int
    active_workers: int
    scheduler_running: bool
    completed_publishes: int
    failed_publishes: int
    dead_letter_count: int
    quarantine_records: int
    details: Dict[str, Any] = field(default_factory=dict)


class UnifiedProductionEngine:
    """
    Production supervisor managing the complete video creation, publishing,
    and analytics feedback lifecycle.
    """

    def __init__(
        self,
        base_dir: Path,
        orchestrator: Optional[BatchProductionOrchestrator] = None,
        renderer: Optional[RendererInterface] = None,
        publishing_service: Optional[PublishingService] = None,
        queue: Optional[PublishQueue] = None,
        scheduler: Optional[PublishingScheduler] = None,
        worker_pool: Optional[PublishWorkerPool] = None,
        analytics_service: Optional[AnalyticsService] = None,
        credential_store: Optional[CredentialStore] = None,
        worker_count: int = 2,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.credential_store = credential_store or CredentialStore()

        # Orchestration layer
        self.orchestrator = orchestrator or BatchProductionOrchestrator(
            store_dir=self.base_dir / "orchestrator_checkpoints",
            renderer=renderer or DefaultRenderer(),
        )

        # Queue & Publishing layer
        queue_dir = self.base_dir / "publish_queue"
        store_dir = self.base_dir / "publish_store"
        self.queue = queue or PublishQueue(queue_dir)
        self.publishing_service = publishing_service or PublishingService(
            store_dir=store_dir,
            queue=self.queue
        )

        # Scheduler & Workers
        self.scheduler = scheduler or PublishingScheduler(
            queue=self.queue,
            publishing_service=self.publishing_service,
            poll_interval_sec=0.1,
        )
        self.worker_pool = worker_pool or PublishWorkerPool(
            worker_count=worker_count,
            queue=self.queue,
            publishing_service=self.publishing_service,
            poll_interval_sec=0.1,
        )

        # Analytics & Webhook Reconciliation
        self.analytics_service = analytics_service or AnalyticsService(store_dir=store_dir)
        self.webhook_reconciler = WebhookReconciler(
            publishing_service=self.publishing_service,
            queue=self.queue
        )

        self._lock = threading.Lock()

    # ─── Service Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start background scheduler and worker pool."""
        self.scheduler.start()
        self.worker_pool.start()

    def stop(self, timeout_sec: float = 5.0) -> None:
        """Stop scheduler and workers gracefully."""
        self.scheduler.stop(timeout_sec=timeout_sec)
        self.worker_pool.stop(timeout_sec=timeout_sec)

    # ─── Operational APIs ─────────────────────────────────────────────────────

    def submit_job_for_publishing(
        self,
        job: ProductionJob,
        scheduled_at: Optional[str] = None,
        priority: str = QueuePriority.NORMAL.value,
        title: str = "",
        visibility: str = "public",
    ) -> PublishQueueItem:
        """
        Validate QA approval and immutability, then enqueue for immediate or scheduled delivery.
        """
        req = self.publishing_service.prepare_publish(
            job=job,
            title=title,
            visibility=visibility,
            scheduled_at=scheduled_at,
        )
        return self.queue.enqueue(
            request=req,
            scheduled_at=scheduled_at,
            priority=priority,
        )

    def cancel_job(self, queue_item_id: str, reason: str = "Operator cancelled") -> PublishQueueItem:
        """Cancel queued or in-flight publishing work."""
        return self.queue.cancel_item(queue_item_id, reason=reason)

    def requeue_dead_letter(self, queue_item_id: str) -> PublishQueueItem:
        """Requeue dead-letter work with automatic pre-reconciliation."""
        return self.queue.requeue_dead_letter(queue_item_id, publishing_service=self.publishing_service)

    def sync_analytics(self, job_id: str, external_id: str, account_id: str) -> Optional[PerformanceMetrics]:
        """Fetch remote metrics and persist snapshot."""
        return self.analytics_service.fetch_and_record_metrics(
            job_id=job_id,
            clip_id=job_id,
            external_id=external_id,
            account_id=account_id,
        )

    def handle_webhook(self, payload: Dict[str, Any], signature: Optional[str] = None) -> Dict[str, Any]:
        """Process remote provider status callback."""
        return self.webhook_reconciler.process_webhook(payload, signature=signature, skip_sig_verify=(signature is None))

    def get_full_job_trajectory(self, job_id: str) -> Dict[str, Any]:
        """Aggregate end-to-end lifecycle history for a job."""
        receipts = self.publishing_service.store.find_receipts_for_job(job_id)
        events = self.publishing_service.store.get_events_for_job(job_id)
        queue_items = [it for it in self.queue.all_items() if it.job_id == job_id]
        snapshots = self.analytics_service.get_metrics_for_job(job_id)

        return {
            "job_id": job_id,
            "receipts": [asdict(r) for r in receipts],
            "events": events,
            "queue_items": [it.to_dict() for it in queue_items],
            "analytics_snapshots": [s.to_dict() for s in snapshots],
        }

    def get_health(self) -> SystemHealthReport:
        """Expose operational telemetry and subsystem status."""
        metrics = self.queue.get_metrics()
        quarantined = len(list(self.queue.quarantine_dir.glob("corrupt_*")))

        status = "HEALTHY"
        if metrics["dead_letter_count"] > 10 or quarantined > 0:
            status = "DEGRADED"

        return SystemHealthReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=status,
            queue_depth=metrics["queue_depth"],
            active_workers=len([w for w in self.worker_pool.workers if w.is_alive]),
            scheduler_running=self.scheduler.is_alive,
            completed_publishes=metrics["completed_count"],
            failed_publishes=metrics["failed_count"],
            dead_letter_count=metrics["dead_letter_count"],
            quarantine_records=quarantined,
            details=metrics,
        )
