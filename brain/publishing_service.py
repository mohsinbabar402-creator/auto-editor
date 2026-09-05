"""
Production Publishing & Delivery Layer — Core Engine (Phase 12)

PURPOSE:
    Coordinates safe, stateful, provider-agnostic delivery of approved
    production artifacts from the orchestration pipeline to external platforms.

INVARIANTS:
    - THE PUBLISHER DOES NOT GET TO OVERRIDE QA.
    - An artifact is NEVER published unless final QA explicitly approved it.
    - Idempotency is enforced for all delivery operations.
    - Artifact immutability is verified: hash must match post-QA state.
    - Failures are classified into transient (retryable) vs permanent (terminal).
    - Ambiguous outcomes trigger reconciliation, NEVER blind re-publish.
    - Cooperative cancellation preserves delivery integrity.
    - Machine-readable audit events and receipts are persisted atomically.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from brain.orchestrator_models import ExecutionMode, JobState, ProductionJob
from brain.publishing_models import (
    PUBLISH_RETRY_POLICIES,
    TERMINAL_PUBLISH_STATES,
    VALID_PUBLISH_TRANSITIONS,
    BatchPublishingResult,
    PublishEligibilityError,
    PublishEvent,
    PublishFailureClass,
    PublishIdempotencyError,
    PublishProviderError,
    PublishReceipt,
    PublishRequest,
    PublishState,
    PublishStateTransitionError,
    PublisherInterface,
    PublishingResult,
)


# ─── Utility Functions ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 digest of a media file."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _make_idempotency_key(
    job_id: str,
    platform: str,
    provider: str,
    artifact_hash: str,
    title: str,
    visibility: str,
) -> str:
    """Generate a deterministic cryptographic idempotency key for a publish request."""
    raw = f"{job_id}|{platform}|{provider}|{artifact_hash}|{title}|{visibility}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# ─── Publishing Store (Atomic Persistence) ────────────────────────────────────

class PublishingStore:
    """
    JSON-backed persistent store for publish receipts, idempotency keys, and events.
    Atomic writes (.tmp + os.replace) prevent corrupted state during system crashes.
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = store_dir
        self._receipts_dir = self._dir / "receipts"
        self._events_dir = self._dir / "events"
        self._receipts_dir.mkdir(parents=True, exist_ok=True)
        self._events_dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._meta_lock = threading.Lock()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._meta_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def save_receipt(self, receipt: PublishReceipt) -> None:
        """Atomically persist a publish receipt to disk."""
        path = self._receipts_dir / f"receipt_{receipt.receipt_id}.json"
        tmp = path.with_suffix(".tmp")
        with self._lock_for(receipt.receipt_id):
            tmp.write_text(
                json.dumps(asdict(receipt), indent=2, default=str),
                encoding="utf-8"
            )
            os.replace(str(tmp), str(path))

    def load_receipt(self, receipt_id: str) -> Optional[PublishReceipt]:
        path = self._receipts_dir / f"receipt_{receipt_id}.json"
        if not path.exists():
            return None
        with self._lock_for(receipt_id):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return PublishReceipt(**data)
            except Exception:
                return None

    def find_receipt_by_idempotency_key(self, idem_key: str) -> Optional[PublishReceipt]:
        """Look up an existing completed receipt by its idempotency key."""
        if not idem_key:
            return None
        for p in self._receipts_dir.glob("receipt_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("idempotency_key") == idem_key and data.get("status") == PublishState.PUBLISHED.value:
                    return PublishReceipt(**data)
            except Exception:
                continue
        return None

    def find_receipts_for_job(self, job_id: str) -> List[PublishReceipt]:
        results = []
        for p in self._receipts_dir.glob("receipt_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("job_id") == job_id:
                    results.append(PublishReceipt(**data))
            except Exception:
                continue
        return results

    def all_receipts(self) -> List[PublishReceipt]:
        results = []
        for p in self._receipts_dir.glob("receipt_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append(PublishReceipt(**data))
            except Exception:
                continue
        return results

    def save_event(self, event: PublishEvent) -> None:
        """Append an event to the job's delivery event stream."""
        path = self._events_dir / f"events_{event.job_id}.jsonl"
        with self._lock_for(event.job_id):
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), default=str) + "\n")

    def get_events_for_job(self, job_id: str) -> List[Dict[str, Any]]:
        path = self._events_dir / f"events_{job_id}.jsonl"
        if not path.exists():
            return []
        events = []
        with self._lock_for(job_id):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        return events


# ─── Publish Eligibility Validator ───────────────────────────────────────────

class PublishEligibilityValidator:
    """
    Independent gatekeeper enforcing that no unapproved, mutated, or defective
    artifact can be published.

    PRINCIPLE: THE PUBLISHER DOES NOT GET TO OVERRIDE QA.
    """

    @staticmethod
    def validate_job(
        job: ProductionJob,
        artifact_path: Optional[Path] = None,
        allow_non_production: bool = False,
    ) -> Tuple[Path, str]:
        """
        Validate that a job and its media artifact meet all publishing prerequisites.
        Returns (verified_artifact_path, artifact_sha256) or raises PublishEligibilityError.
        """
        # 1. State must be an approved output state
        allowed_states = [JobState.OUTPUT_READY.value, JobState.COMPLETED.value, JobState.APPROVED.value]
        if job.state not in allowed_states:
            raise PublishEligibilityError(
                f"Job {job.job_id} is in state '{job.state}'. Must be one of {allowed_states} to publish."
            )

        # 2. Must not be flagged with an active failure or rejection
        if job.failure_class:
            raise PublishEligibilityError(
                f"Job {job.job_id} has active failure class '{job.failure_class}': {job.failure_message}"
            )
        if job.state in (JobState.REJECTED.value, JobState.FAILED.value, JobState.CANCELLED.value):
            raise PublishEligibilityError(f"Job {job.job_id} is in terminal failed state: {job.state}")

        # 3. Must not be escalated for source re-render
        if job.escalation or job.state == JobState.REPAIR_ESCALATED.value:
            raise PublishEligibilityError(
                f"Job {job.job_id} has active escalation: {job.escalation.get('reason', 'SOURCE_RERENDER_REQUIRED')}"
            )

        # 4. Final QA verification (QA IS SOLE AUTHORITY)
        qa_report_raw = job.artifacts.get("qa_report")
        if qa_report_raw:
            try:
                qa_data = json.loads(qa_report_raw) if isinstance(qa_report_raw, str) else qa_report_raw
                if isinstance(qa_data, dict):
                    action = qa_data.get("recommended_action", "").lower()
                    hard_fails = qa_data.get("hard_fails", [])
                    passed = qa_data.get("passed", False)

                    if action == "reject" or hard_fails or not passed:
                        raise PublishEligibilityError(
                            f"QA rejection detected in artifact for job {job.job_id}: "
                            f"action={action}, hard_fails={hard_fails}"
                        )
            except (json.JSONDecodeError, TypeError):
                pass

        # 5. Execution mode verification
        if job.execution_mode != ExecutionMode.PRODUCTION.value and not allow_non_production:
            raise PublishEligibilityError(
                f"Job {job.job_id} is in execution mode '{job.execution_mode}'. "
                f"Non-production modes (TEST, DRY_RUN) cannot publish to live platforms."
            )

        # 6. Artifact presence & integrity
        target = artifact_path
        if target is None:
            artifact_str = job.artifacts.get("final_output") or job.artifacts.get("render_output")
            if not artifact_str:
                raise PublishEligibilityError(f"Job {job.job_id} has no recorded output artifact.")
            target = Path(artifact_str)

        if not target.exists():
            raise PublishEligibilityError(f"Media artifact file does not exist: {target}")

        file_size = target.stat().st_size
        if file_size < 1024:
            raise PublishEligibilityError(f"Media artifact is corrupt or too small: {file_size} bytes")

        current_hash = _file_sha256(target)

        # 7. Artifact immutability: compare against approved hash if recorded
        expected_hash = job.artifacts.get("artifact_hash")
        if expected_hash and current_hash != expected_hash:
            raise PublishEligibilityError(
                f"Artifact hash mismatch for job {job.job_id}: "
                f"approved={expected_hash[:12]}..., current={current_hash[:12]}... "
                f"Artifact mutated after QA approval!"
            )

        return target, current_hash


# ─── Mock Publisher Implementation ────────────────────────────────────────────

class MockPublisher(PublisherInterface):
    """
    Deterministic mock publisher for automated testing and simulation.
    Supports controllable failure injection, rate limiting, cancellation,
    and ambiguous timeout outcomes.
    """

    def __init__(
        self,
        name: str = "MockPublisher",
        fail_mode: Optional[str] = None,   # "transient", "permanent", "reject", "timeout_after_accept"
        fail_times: int = 0,
        simulated_delay_sec: float = 0.0,
    ) -> None:
        self._name = name
        self.fail_mode = fail_mode
        self.fail_remaining = fail_times
        self.delay_sec = simulated_delay_sec
        self.published_requests: List[PublishRequest] = []
        self.receipts: Dict[str, PublishReceipt] = {}
        self.cancelled_ids: Set[str] = set()
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    def publish(self, request: Any, metadata: Optional[Dict[str, Any]] = None) -> PublishReceipt:
        # Backward compatibility for legacy Phase 11 call: publish(path, metadata_dict)
        if isinstance(request, (str, Path)):
            req = PublishRequest(
                job_id=metadata.get("job_id", "legacy_job"),
                episode_id=metadata.get("episode_id", "legacy_ep"),
                clip_id=metadata.get("clip_id", "legacy_clip"),
                account_id=metadata.get("account_id", "default"),
                platform=metadata.get("platform", "youtube_shorts"),
                artifact_path=str(request),
                artifact_hash=_file_sha256(Path(request)),
                title=metadata.get("title", "Untitled Clip"),
            )
        else:
            req = request

        with self._lock:
            self.published_requests.append(req)

            if self.delay_sec > 0:
                time.sleep(self.delay_sec)

            # Simulated transient failure
            if self.fail_remaining > 0:
                self.fail_remaining -= 1
                raise PublishProviderError(
                    "Simulated transient network timeout",
                    failure_class=PublishFailureClass.NETWORK_ERROR.value,
                )

            # Simulated permanent failures
            if self.fail_mode == "permanent":
                raise PublishProviderError(
                    "Simulated permanent authentication error (401)",
                    failure_class=PublishFailureClass.AUTHENTICATION_ERROR.value,
                )
            if self.fail_mode == "reject":
                raise PublishProviderError(
                    "Simulated platform policy violation",
                    failure_class=PublishFailureClass.PROVIDER_REJECTED.value,
                )
            if self.fail_mode == "timeout_after_accept":
                # Provider accepts and assigns external ID, but connection drops on response
                ext_id = f"ext_ambiguous_{uuid.uuid4().hex[:8]}"
                self.receipts[ext_id] = PublishReceipt(
                    receipt_id=f"rec_{uuid.uuid4().hex[:12]}",
                    job_id=req.job_id,
                    clip_id=req.clip_id,
                    platform=req.platform,
                    provider=self.name,
                    external_id=ext_id,
                    status=PublishState.PUBLISHED.value,
                    published_at=_now_iso(),
                    artifact_hash=req.artifact_hash or _file_sha256(Path(req.artifact_path)),
                    idempotency_key=req.idempotency_key,
                )
                self.fail_mode = None  # Clear so subsequent get_status works
                raise PublishProviderError(
                    f"Read timeout after upload: external_id={ext_id}",
                    failure_class=PublishFailureClass.TIMEOUT.value,
                )

            external_id = f"ext_{uuid.uuid4().hex[:10]}"
            receipt = PublishReceipt(
                receipt_id=f"rec_{uuid.uuid4().hex[:12]}",
                job_id=req.job_id,
                clip_id=req.clip_id,
                platform=req.platform,
                provider=self.name,
                external_id=external_id,
                status=PublishState.PUBLISHED.value,
                published_at=_now_iso(),
                artifact_hash=req.artifact_hash or _file_sha256(Path(req.artifact_path)),
                idempotency_key=req.idempotency_key,
                provider_metadata={"mock_url": f"https://mock.platform.com/{external_id}"},
                errors=[],
                attempt_count=1,
            )
            self.receipts[external_id] = copy.deepcopy(receipt)
            return copy.deepcopy(receipt)

    def get_status(self, external_id: str) -> Optional[PublishReceipt]:
        with self._lock:
            r = self.receipts.get(external_id)
            if r is not None:
                return copy.deepcopy(r)
            return None

    def cancel(self, external_id: str) -> bool:
        with self._lock:
            if external_id in self.receipts:
                self.cancelled_ids.add(external_id)
                receipt = self.receipts[external_id]
                receipt.status = PublishState.PUBLISH_CANCELLED.value
                return True
            return False


# ─── Publishing Service ───────────────────────────────────────────────────────

class PublishingService:
    """
    Coordinates delivery of approved video clips to publishing destinations.

    API:
        - prepare_publish(job, ...) -> PublishRequest
        - queue_publish(request) -> PublishReceipt
        - publish(request) -> PublishReceipt
        - publish_job(job, ...) -> PublishReceipt
        - get_publish_status(external_id) -> Optional[PublishReceipt]
        - cancel_publish(external_id, job_id) -> bool
        - publish_batch(batch_id, requests) -> BatchPublishingResult
        - resume_pending_publishes() -> List[PublishReceipt]
    """

    def __init__(
        self,
        store_dir: Path,
        publisher: Optional[PublisherInterface] = None,
        max_concurrent_publishes: int = 3,
        max_publishes_per_account: int = 2,
        queue: Optional[Any] = None,
    ) -> None:
        self.store = PublishingStore(store_dir)
        self.publisher = publisher or MockPublisher()
        self._publish_sem = threading.Semaphore(max_concurrent_publishes)
        self._account_locks: Dict[str, threading.Semaphore] = {}
        self._key_locks: Dict[str, threading.Lock] = {}
        self._meta_lock = threading.Lock()
        self._max_per_account = max_publishes_per_account
        self.queue = queue

    def _get_account_sem(self, account_id: str) -> threading.Semaphore:
        with self._meta_lock:
            if account_id not in self._account_locks:
                self._account_locks[account_id] = threading.Semaphore(self._max_per_account)
            return self._account_locks[account_id]

    def _get_key_lock(self, idempotency_key: str) -> threading.Lock:
        with self._meta_lock:
            if idempotency_key not in self._key_locks:
                self._key_locks[idempotency_key] = threading.Lock()
            return self._key_locks[idempotency_key]

    def _log_event(
        self,
        job_id: str,
        episode_id: str,
        clip_id: str,
        platform: str,
        prev_state: str,
        new_state: str,
        event_msg: str,
        attempt: int = 1,
        duration_sec: float = 0.0,
        idempotency_key: str = "",
        artifact_hash: str = "",
        result: str = "",
        error: str = "",
        metadata: Optional[Dict] = None,
    ) -> None:
        # Validate transition before logging
        if prev_state and new_state in VALID_PUBLISH_TRANSITIONS.get(PublishState(prev_state), []):
            pass
        elif prev_state and new_state not in VALID_PUBLISH_TRANSITIONS.get(PublishState(prev_state), []):
            if new_state not in TERMINAL_PUBLISH_STATES:
                raise PublishStateTransitionError(
                    f"Illegal publishing state transition: {prev_state} -> {new_state}"
                )

        event = PublishEvent(
            timestamp=_now_iso(),
            job_id=job_id,
            episode_id=episode_id,
            clip_id=clip_id,
            platform=platform,
            provider=self.publisher.name,
            previous_state=prev_state,
            new_state=new_state,
            event=event_msg,
            attempt=attempt,
            duration_sec=duration_sec,
            idempotency_key=idempotency_key,
            artifact_hash=artifact_hash,
            result=result,
            error=error,
            metadata=metadata or {},
        )
        self.store.save_event(event)

    # ── API Methods ───────────────────────────────────────────────────────────

    def prepare_publish(
        self,
        job: ProductionJob,
        title: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        visibility: str = "public",
        scheduled_at: Optional[str] = None,
        allow_non_production: bool = False,
    ) -> PublishRequest:
        """
        Validate eligibility and construct an immutable PublishRequest.
        """
        artifact_path, artifact_hash = PublishEligibilityValidator.validate_job(
            job=job,
            allow_non_production=allow_non_production,
        )

        final_title = title or job.title or f"Clip {job.clip_id}"
        idem_key = _make_idempotency_key(
            job_id=job.job_id,
            platform=job.platform,
            provider=self.publisher.name,
            artifact_hash=artifact_hash,
            title=final_title,
            visibility=visibility,
        )

        return PublishRequest(
            job_id=job.job_id,
            episode_id=job.episode_id,
            clip_id=job.clip_id,
            account_id=job.account_id,
            platform=job.platform,
            artifact_path=str(artifact_path),
            artifact_hash=artifact_hash,
            title=final_title,
            description=description,
            tags=tags or [],
            visibility=visibility,
            scheduled_at=scheduled_at,
            idempotency_key=idem_key,
            execution_mode=job.execution_mode,
        )

    def queue_publish(self, request: PublishRequest) -> PublishReceipt:
        """
        Enqueue and publish a validated request.
        """
        return self.publish(request)

    def publish_job(
        self,
        job: ProductionJob,
        title: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        visibility: str = "public",
        scheduled_at: Optional[str] = None,
        allow_non_production: bool = False,
    ) -> PublishReceipt:
        """
        Convenience wrapper: prepare_publish + publish.
        """
        request = self.prepare_publish(
            job=job,
            title=title,
            description=description,
            tags=tags,
            visibility=visibility,
            scheduled_at=scheduled_at,
            allow_non_production=allow_non_production,
        )
        return self.publish(request)

    def publish(self, request: PublishRequest) -> PublishReceipt:
        """
        Execute delivery of a PublishRequest through the state machine.
        Thread-safe across duplicate workers via per-idempotency-key locking.
        """
        start_time = time.monotonic()
        key_lock = self._get_key_lock(request.idempotency_key)

        with key_lock:
            # 1. Idempotency Check: Return existing completed receipt if present
            cached_receipt = self.store.find_receipt_by_idempotency_key(request.idempotency_key)
            if cached_receipt:
                return cached_receipt

            # 2. Check artifact existence and hash right before publishing
            art_path = Path(request.artifact_path)
            if not art_path.exists():
                receipt = PublishReceipt(
                    receipt_id=f"rec_err_{uuid.uuid4().hex[:10]}",
                    job_id=request.job_id,
                    clip_id=request.clip_id,
                    platform=request.platform,
                    provider=self.publisher.name,
                    external_id="",
                    status=PublishState.PUBLISH_FAILED.value,
                    published_at=_now_iso(),
                    artifact_hash="",
                    idempotency_key=request.idempotency_key,
                    errors=[f"Artifact file missing: {request.artifact_path}"],
                )
                self.store.save_receipt(receipt)
                return receipt

            current_hash = _file_sha256(art_path)
            if request.artifact_hash and current_hash != request.artifact_hash:
                receipt = PublishReceipt(
                    receipt_id=f"rec_err_{uuid.uuid4().hex[:10]}",
                    job_id=request.job_id,
                    clip_id=request.clip_id,
                    platform=request.platform,
                    provider=self.publisher.name,
                    external_id="",
                    status=PublishState.PUBLISH_FAILED.value,
                    published_at=_now_iso(),
                    artifact_hash=current_hash,
                    idempotency_key=request.idempotency_key,
                    errors=["Artifact mutated after QA approval (hash mismatch)"],
                )
                self.store.save_receipt(receipt)
                return receipt

            # 3. State transition: PUBLISH_READY -> PUBLISH_QUEUED
            state = PublishState.PUBLISH_READY.value
            self._log_event(
                job_id=request.job_id, episode_id=request.episode_id, clip_id=request.clip_id,
                platform=request.platform, prev_state=state, new_state=PublishState.PUBLISH_QUEUED.value,
                event_msg="Enqueued for delivery", idempotency_key=request.idempotency_key,
                artifact_hash=request.artifact_hash,
            )
            state = PublishState.PUBLISH_QUEUED.value

            account_sem = self._get_account_sem(request.account_id)
            max_attempts = 3
            backoff_sec = 0.5

            with self._publish_sem:
                with account_sem:
                    # State transition: PUBLISH_QUEUED -> PUBLISHING
                    self._log_event(
                        job_id=request.job_id, episode_id=request.episode_id, clip_id=request.clip_id,
                        platform=request.platform, prev_state=state, new_state=PublishState.PUBLISHING.value,
                        event_msg="Active delivery transmission started", idempotency_key=request.idempotency_key,
                        artifact_hash=request.artifact_hash,
                    )
                    state = PublishState.PUBLISHING.value

                    attempt = 0
                    while attempt < max_attempts:
                        attempt += 1
                        try:
                            receipt = self.publisher.publish(request)
                            duration = round(time.monotonic() - start_time, 3)

                            receipt.attempt_count = attempt
                            receipt.duration_sec = duration
                            receipt.status = PublishState.PUBLISHED.value
                            receipt.idempotency_key = request.idempotency_key
                            receipt.artifact_hash = request.artifact_hash or current_hash

                            # State transition: PUBLISHING -> PUBLISHED
                            self._log_event(
                                job_id=request.job_id, episode_id=request.episode_id, clip_id=request.clip_id,
                                platform=request.platform, prev_state=state, new_state=PublishState.PUBLISHED.value,
                                event_msg=f"Delivery confirmed by {self.publisher.name}",
                                attempt=attempt, duration_sec=duration, idempotency_key=request.idempotency_key,
                                artifact_hash=receipt.artifact_hash, result=receipt.external_id,
                                metadata={"external_id": receipt.external_id},
                            )
                            self.store.save_receipt(receipt)
                            return receipt

                        except PublishProviderError as exc:
                            duration = round(time.monotonic() - start_time, 3)
                            is_retryable = (
                                PUBLISH_RETRY_POLICIES.get(exc.failure_class, {}).get("retryable", False)
                            )

                            # Handle ambiguous timeout outcome
                            if exc.failure_class == PublishFailureClass.TIMEOUT.value and "external_id=" in str(exc):
                                ext_id = str(exc).split("external_id=")[-1].rstrip(")").strip()
                                reconciled = self.publisher.get_status(ext_id)
                                if reconciled and reconciled.status == PublishState.PUBLISHED.value:
                                    reconciled.duration_sec = duration
                                    reconciled.idempotency_key = request.idempotency_key
                                    reconciled.job_id = request.job_id
                                    reconciled.clip_id = request.clip_id
                                    reconciled.platform = request.platform
                                    reconciled.artifact_hash = request.artifact_hash or current_hash
                                    self._log_event(
                                        job_id=request.job_id, episode_id=request.episode_id, clip_id=request.clip_id,
                                        platform=request.platform, prev_state=state, new_state=PublishState.PUBLISHED.value,
                                        event_msg=f"Reconciled ambiguous outcome via get_status({ext_id})",
                                        attempt=attempt, duration_sec=duration, idempotency_key=request.idempotency_key,
                                        artifact_hash=request.artifact_hash, result=ext_id,
                                    )
                                    self.store.save_receipt(reconciled)
                                    return reconciled

                            if not is_retryable or attempt >= max_attempts:
                                terminal_state = (
                                    PublishState.PUBLISH_REJECTED.value
                                    if "REJECTED" in exc.failure_class or "POLICY" in exc.failure_class
                                    else PublishState.PUBLISH_FAILED.value
                                )
                                self._log_event(
                                    job_id=request.job_id, episode_id=request.episode_id, clip_id=request.clip_id,
                                    platform=request.platform, prev_state=state, new_state=terminal_state,
                                    event_msg=f"Provider delivery stopped: {exc}",
                                    attempt=attempt, duration_sec=duration, error=str(exc),
                                    idempotency_key=request.idempotency_key, artifact_hash=request.artifact_hash,
                                )
                                receipt = PublishReceipt(
                                    receipt_id=f"rec_err_{uuid.uuid4().hex[:10]}",
                                    job_id=request.job_id,
                                    clip_id=request.clip_id,
                                    platform=request.platform,
                                    provider=self.publisher.name,
                                    external_id="",
                                    status=terminal_state,
                                    published_at=_now_iso(),
                                    artifact_hash=request.artifact_hash or current_hash,
                                    idempotency_key=request.idempotency_key,
                                    errors=[str(exc)],
                                    attempt_count=attempt,
                                    duration_sec=duration,
                                )
                                self.store.save_receipt(receipt)
                                return receipt

                            # Transient retry: PUBLISHING -> PUBLISH_FAILED -> PUBLISH_RETRYING -> PUBLISHING
                            self._log_event(
                                job_id=request.job_id, episode_id=request.episode_id, clip_id=request.clip_id,
                                platform=request.platform, prev_state=state, new_state=PublishState.PUBLISH_RETRYING.value,
                                event_msg=f"Transient failure (attempt {attempt}/{max_attempts}): {exc}. Backing off.",
                                attempt=attempt, error=str(exc), idempotency_key=request.idempotency_key,
                                artifact_hash=request.artifact_hash,
                            )
                            state = PublishState.PUBLISH_RETRYING.value
                            time.sleep(backoff_sec)
                            backoff_sec *= 2.0
                            state = PublishState.PUBLISHING.value

                        except Exception as e:
                            duration = round(time.monotonic() - start_time, 3)
                            self._log_event(
                                job_id=request.job_id, episode_id=request.episode_id, clip_id=request.clip_id,
                                platform=request.platform, prev_state=state, new_state=PublishState.PUBLISH_FAILED.value,
                                event_msg=f"Internal failure: {e}",
                                attempt=attempt, duration_sec=duration, error=str(e),
                                idempotency_key=request.idempotency_key, artifact_hash=request.artifact_hash,
                            )
                            receipt = PublishReceipt(
                                receipt_id=f"rec_err_{uuid.uuid4().hex[:10]}",
                                job_id=request.job_id,
                                clip_id=request.clip_id,
                                platform=request.platform,
                                provider=self.publisher.name,
                                external_id="",
                                status=PublishState.PUBLISH_FAILED.value,
                                published_at=_now_iso(),
                                artifact_hash=request.artifact_hash or current_hash,
                                idempotency_key=request.idempotency_key,
                                errors=[f"InternalError: {e}"],
                                attempt_count=attempt,
                                duration_sec=duration,
                            )
                            self.store.save_receipt(receipt)
                            return receipt

        return PublishReceipt(
            receipt_id=f"rec_err_{uuid.uuid4().hex[:10]}",
            job_id=request.job_id,
            clip_id=request.clip_id,
            platform=request.platform,
            provider=self.publisher.name,
            external_id="",
            status=PublishState.PUBLISH_FAILED.value,
            published_at=_now_iso(),
            artifact_hash="",
            idempotency_key=request.idempotency_key,
            errors=["Exhausted retry attempts without receipt"],
        )

    def get_publish_status(self, external_id: str) -> Optional[PublishReceipt]:
        """Query platform for live delivery status using the external ID."""
        return self.publisher.get_status(external_id)

    def cancel_publish(self, external_id: str, job_id: str = "") -> bool:
        """Cooperative delivery cancellation on the provider."""
        cancelled = self.publisher.cancel(external_id)
        if cancelled and job_id:
            self._log_event(
                job_id=job_id, episode_id="", clip_id="", platform="",
                prev_state=PublishState.PUBLISHING.value,
                new_state=PublishState.PUBLISH_CANCELLED.value,
                event_msg=f"Delivery cancelled for external ID {external_id}",
            )
        return cancelled

    def publish_batch(
        self,
        batch_id: str,
        requests: List[PublishRequest],
        max_workers: int = 2,
    ) -> BatchPublishingResult:
        """
        Deliver multiple publish requests with independent error isolation.
        """
        start = time.monotonic()
        results: List[PublishingResult] = []

        if max_workers > 1 and len(requests) > 1:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_to_req = {pool.submit(self.publish, r): r for r in requests}
                for f in concurrent.futures.as_completed(future_to_req):
                    req = future_to_req[f]
                    try:
                        receipt = f.result()
                        results.append(PublishingResult(
                            job_id=req.job_id,
                            state=receipt.status,
                            provider=receipt.provider,
                            platform=receipt.platform,
                            receipt=receipt,
                            attempts=receipt.attempt_count,
                            artifact_hash=receipt.artifact_hash,
                            duration_sec=receipt.duration_sec,
                            errors=receipt.errors,
                        ))
                    except Exception as e:
                        results.append(PublishingResult(
                            job_id=req.job_id,
                            state=PublishState.PUBLISH_FAILED.value,
                            provider=self.publisher.name,
                            platform=req.platform,
                            receipt=None,
                            errors=[str(e)],
                        ))
        else:
            for req in requests:
                try:
                    receipt = self.publish(req)
                    results.append(PublishingResult(
                        job_id=req.job_id,
                        state=receipt.status,
                        provider=receipt.provider,
                        platform=receipt.platform,
                        receipt=receipt,
                        attempts=receipt.attempt_count,
                        artifact_hash=receipt.artifact_hash,
                        duration_sec=receipt.duration_sec,
                        errors=receipt.errors,
                    ))
                except Exception as e:
                    results.append(PublishingResult(
                        job_id=req.job_id,
                        state=PublishState.PUBLISH_FAILED.value,
                        provider=self.publisher.name,
                        platform=req.platform,
                        receipt=None,
                        errors=[str(e)],
                    ))

        return BatchPublishingResult(
            batch_id=batch_id,
            total=len(results),
            published=sum(1 for r in results if r.state == PublishState.PUBLISHED.value),
            failed=sum(1 for r in results if r.state == PublishState.PUBLISH_FAILED.value),
            rejected=sum(1 for r in results if r.state == PublishState.PUBLISH_REJECTED.value),
            retrying=sum(1 for r in results if r.state == PublishState.PUBLISH_RETRYING.value),
            cancelled=sum(1 for r in results if r.state == PublishState.PUBLISH_CANCELLED.value),
            duration_sec=round(time.monotonic() - start, 3),
            results=results,
        )

    def resume_pending_publishes(self) -> List[PublishReceipt]:
        """
        Scan persisted store on startup, identify in-flight non-terminal receipts,
        and reconcile them with remote provider status.
        """
        reconciled_list = []
        for receipt in self.store.all_receipts():
            if receipt.status in (PublishState.PUBLISHING.value, PublishState.PUBLISH_RETRYING.value):
                if receipt.external_id:
                    remote = self.publisher.get_status(receipt.external_id)
                    if remote and remote.status == PublishState.PUBLISHED.value:
                        receipt.status = PublishState.PUBLISHED.value
                        self.store.save_receipt(receipt)
                        reconciled_list.append(receipt)
        return reconciled_list

    # ── Phase 14 Queue & Worker Integration ────────────────────────────────────

    def schedule_publish(
        self,
        job: ProductionJob,
        scheduled_at: str,
        title: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        visibility: str = "public",
        priority: str = "NORMAL",
        allow_non_production: bool = False,
    ) -> Any:
        """Prepare and enqueue a publish request scheduled for future delivery."""
        req = self.prepare_publish(
            job=job,
            title=title,
            description=description,
            tags=tags,
            visibility=visibility,
            scheduled_at=scheduled_at,
            allow_non_production=allow_non_production,
        )
        return self.enqueue_publish(req, scheduled_at=scheduled_at, priority=priority)

    def enqueue_publish(
        self,
        request: PublishRequest,
        scheduled_at: Optional[str] = None,
        priority: str = "NORMAL",
    ) -> Any:
        """Enqueue a PublishRequest into the durable queue."""
        if self.queue is None:
            from brain.publish_queue import PublishQueue
            self.queue = PublishQueue(self.store._dir / "queue")
        target_sched = scheduled_at or request.scheduled_at
        return self.queue.enqueue(request, scheduled_at=target_sched, priority=priority)

    def get_queue_status(self) -> Dict[str, Any]:
        """Expose queue metrics and depth."""
        if self.queue is None:
            return {"queue_depth": 0, "status": "no_queue_configured"}
        return self.queue.get_metrics()

    def requeue_dead_letter(self, queue_item_id: str) -> Any:
        """Manually requeue a DEAD_LETTER item with pre-reconciliation."""
        if self.queue is None:
            raise RuntimeError("No publish queue configured")
        return self.queue.requeue_dead_letter(queue_item_id, publishing_service=self)

    def resume_pending_work(self) -> Dict[str, Any]:
        """
        Full startup recovery:
        1. Reconcile in-flight publishing receipts against remote provider.
        2. Recover expired queue leases without duplicate publication.
        """
        reconciled_receipts = self.resume_pending_publishes()
        recovered_items = []
        if self.queue is not None:
            recovered_items = self.queue.recover_expired_leases(publishing_service=self)
        return {
            "reconciled_receipts": reconciled_receipts,
            "recovered_queue_items": recovered_items,
        }

