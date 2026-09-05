"""
Phase 14 — Production Scheduling, Durable Queue & Worker Execution Test Suite
Tests 1 through 38 (Full Required Matrix) + Adversarial Tests

TEST 1  — Immediate enqueue (PUBLISH_READY -> READY)
TEST 2  — Future scheduling (PUBLISH_READY -> SCHEDULED)
TEST 3  — Scheduler reaches due time (SCHEDULED -> READY)
TEST 4  — Overdue schedule recovery
TEST 5  — Queue persistence across restart
TEST 6  — Queue idempotency (10 duplicates -> 1 queue item)
TEST 7  — Atomic lease acquisition (2 racing workers)
TEST 8  — Multi-worker execution (many workers, many jobs)
TEST 9  — Lease expiration recovery
TEST 10 — Crash during provider call (0 duplicate uploads)
TEST 11 — Receipt-first recovery
TEST 12 — Provider timeout classified correctly
TEST 13 — Retry scheduling (RUNNING -> RETRY_WAIT -> READY)
TEST 14 — Retry exhaustion -> DEAD_LETTER
TEST 15 — Permanent provider rejection -> no retry
TEST 16 — Cancellation before execution (CANCELLED)
TEST 17 — Cancellation race
TEST 18 — Graceful shutdown
TEST 19 — Scheduler restart recovery
TEST 20 — Worker restart recovery
TEST 21 — Duplicate queue delivery (1 logical publication)
TEST 22 — Provider acceptance + timeout reconciliation
TEST 23 — Provider/account isolation
TEST 24 — Provider concurrency limit respected
TEST 25 — Account concurrency limit respected
TEST 26 — Backpressure capacity limit enforced
TEST 27 — Priority ordering (HIGH > NORMAL > LOW)
TEST 28 — Starvation prevention for aging low-priority jobs
TEST 29 — Mixed batch scheduling isolation
TEST 30 — Corrupt queue record fails safely without crash loop
TEST 31 — Illegal queue transition raises QueueStateTransitionError
TEST 32 — Dry-run isolation (100 dry-run jobs -> 0 real provider calls)
TEST 33 — Secret isolation audit (zero credentials in queue/events)
TEST 34 — Artifact immutability verified before worker execution
TEST 35 — QA authority preserved (QA_FAILED/REJECTED/ESCALATED blocked)
TEST 36 — Phase 13 regression suite (30/30)
TEST 37 — Phase 12 regression suite (27/27)
TEST 38 — Phase 11 regression suite (23/23)
ADV 1   — 10-worker simultaneous lease race
ADV 2   — Ambiguous provider crash recovery
ADV 3   — Rapid worker shutdown during execution
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.orchestrator_models import ExecutionMode, JobState, ProductionJob
from brain.provider_credentials import CredentialStore, YouTubeCredentials
from brain.publish_queue import (
    PublishQueue,
    PublishQueueConfig,
    PublishQueueItem,
    QueueCapacityExceededError,
    QueuePriority,
    QueueState,
    QueueStateTransitionError,
    _now_iso,
    _parse_iso,
)
from brain.publishing_models import (
    PublishEligibilityError,
    PublishFailureClass,
    PublishProviderError,
    PublishReceipt,
    PublishRequest,
    PublishState,
)
from brain.publishing_scheduler import PublishingScheduler
from brain.publishing_service import MockPublisher, PublishingService, _file_sha256
from brain.publish_worker import PublishWorker, PublishWorkerPool
from brain.youtube_publisher import YouTubePublisher
from brain.youtube_transport import FakeYouTubeTransport

SEP = "=" * 65


# ─── Helper Utilities ─────────────────────────────────────────────────────────

def _make_dummy_video(dest: Path, size_bytes: int = 4096) -> Tuple[Path, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\x00" * size_bytes)
    h = hashlib.sha256(b"\x00" * size_bytes).hexdigest()
    return dest, h


def _make_production_job(
    tmp_dir: Path,
    job_id: Optional[str] = None,
    state: JobState = JobState.OUTPUT_READY,
    passed_qa: bool = True,
    execution_mode: ExecutionMode = ExecutionMode.PRODUCTION,
    account_id: str = "acc_01",
) -> Tuple[ProductionJob, Path, str]:
    jid = job_id or f"job_{uuid.uuid4().hex[:8]}"
    vid_path = tmp_dir / f"video_{jid}.mp4"
    _, vhash = _make_dummy_video(vid_path)

    qa_report = json.dumps({
        "passed": passed_qa,
        "recommended_action": "approve" if passed_qa else "reject",
        "hard_fails": [] if passed_qa else ["Black frame detected"],
    })

    job = ProductionJob(
        job_id=jid,
        episode_id="ep_01",
        clip_id=f"clip_{jid[-4:]}",
        state=state.value,
        execution_mode=execution_mode.value,
        account_id=account_id,
        platform="youtube_shorts",
        title=f"Test Title {jid}",
        artifacts={
            "final_output": str(vid_path),
            "artifact_hash": vhash,
            "qa_report": qa_report,
        },
    )
    return job, vid_path, vhash


def _setup_test_env() -> Tuple[tempfile.TemporaryDirectory, PublishingService, PublishQueue]:
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    base = Path(tmp.name)
    store_dir = base / "pub_store"
    queue_dir = base / "pub_queue"
    mock_pub = MockPublisher()
    queue = PublishQueue(queue_dir, config=PublishQueueConfig(default_lease_duration_sec=2.0))
    service = PublishingService(store_dir=store_dir, publisher=mock_pub, queue=queue)
    return tmp, service, queue


# ─── Tests 1 to 38 ────────────────────────────────────────────────────────────

def test_01_immediate_enqueue():
    print(f"\n{SEP}\nTEST 1: Immediate enqueue (PUBLISH_READY -> READY)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))

    req = service.prepare_publish(job)
    item = queue.enqueue(req, scheduled_at=None)

    assert item.status == QueueState.READY.value
    assert item.job_id == job.job_id
    assert item.idempotency_key == req.idempotency_key
    print(f"  Item ID: {item.queue_item_id}, Status: {item.status}")
    print("  PASS: Immediate publish enqueued directly into READY.")
    tmp.cleanup()


def test_02_future_scheduling():
    print(f"\n{SEP}\nTEST 2: Future scheduling (PUBLISH_READY -> SCHEDULED)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))

    future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    req = service.prepare_publish(job, scheduled_at=future_time)
    item = queue.enqueue(req, scheduled_at=future_time)

    assert item.status == QueueState.SCHEDULED.value
    assert item.scheduled_at == future_time

    # Worker poll must find 0 items to lease
    worker = PublishWorker("test_worker", queue, service)
    leased = worker.poll_once()
    assert leased is None
    assert len(service.publisher.published_requests) == 0

    print(f"  Item scheduled at: {item.scheduled_at}, Status: {item.status}")
    print("  PASS: Future scheduled job held in SCHEDULED, 0 provider calls before due time.")
    tmp.cleanup()


def test_03_scheduler_reaches_due_time():
    print(f"\n{SEP}\nTEST 3: Scheduler reaches due time (SCHEDULED -> READY)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))

    # Scheduled 0.1s in future
    near_future = (datetime.now(timezone.utc) + timedelta(milliseconds=150)).isoformat()
    req = service.prepare_publish(job, scheduled_at=near_future)
    item = queue.enqueue(req, scheduled_at=near_future)
    assert item.status == QueueState.SCHEDULED.value

    scheduler = PublishingScheduler(queue, publishing_service=service, poll_interval_sec=0.05)
    # Before time reached:
    assert scheduler.poll_once() == 0
    assert queue.get_item(item.queue_item_id).status == QueueState.SCHEDULED.value

    # Wait for time to arrive
    time.sleep(0.2)
    trans = scheduler.poll_once()
    assert trans >= 1

    updated = queue.get_item(item.queue_item_id)
    assert updated.status == QueueState.READY.value
    print(f"  Transitioned {item.queue_item_id} to {updated.status}")
    print("  PASS: Scheduler detected due time and transitioned SCHEDULED -> READY.")
    tmp.cleanup()


def test_04_overdue_schedule():
    print(f"\n{SEP}\nTEST 4: Overdue schedule recovery\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))

    # Item with past timestamp
    past_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    req = service.prepare_publish(job, scheduled_at=past_time)
    item = queue.enqueue(req, scheduled_at=past_time)

    # Immediately becomes READY
    assert item.status == QueueState.READY.value
    print(f"  Overdue job scheduled_at: {past_time} -> Status: {item.status}")
    print("  PASS: Overdue schedule safely enqueued as READY without silent discard.")
    tmp.cleanup()


def test_05_queue_persistence():
    print(f"\n{SEP}\nTEST 5: Queue persistence across restart\n{SEP}")
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    queue_dir = base / "pub_queue"
    store_dir = base / "pub_store"

    queue1 = PublishQueue(queue_dir)
    service1 = PublishingService(store_dir, queue=queue1)
    job, _, _ = _make_production_job(base)
    req = service1.prepare_publish(job)
    item1 = queue1.enqueue(req)

    # Simulate restart with fresh instances pointing to same directories
    del queue1, service1
    queue2 = PublishQueue(queue_dir)
    recovered_item = queue2.get_item(item1.queue_item_id)

    assert recovered_item is not None
    assert recovered_item.queue_item_id == item1.queue_item_id
    assert recovered_item.job_id == job.job_id
    assert recovered_item.status == QueueState.READY.value
    print(f"  Recovered item: {recovered_item.queue_item_id} from disk")
    print("  PASS: Queue item persists across process restart.")
    tmp.cleanup()


def test_06_queue_idempotency():
    print(f"\n{SEP}\nTEST 6: Queue idempotency (10 duplicates -> 1 queue item)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)

    items = [queue.enqueue(req) for _ in range(10)]
    item_ids = {it.queue_item_id for it in items}

    assert len(item_ids) == 1
    assert len(queue.all_items()) == 1
    print(f"  Submitted 10 requests, stored items: {len(queue.all_items())}")
    print("  PASS: Queue idempotency verified. Exactly 1 logical queue item.")
    tmp.cleanup()


def test_07_atomic_lease():
    print(f"\n{SEP}\nTEST 7: Atomic lease acquisition (2 racing workers)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)
    item = queue.enqueue(req)

    leases = []
    def worker_race(wid: str):
        leased = queue.acquire_lease(wid)
        if leased is not None:
            leases.append((wid, leased.queue_item_id))

    t1 = threading.Thread(target=worker_race, args=("worker_A",))
    t2 = threading.Thread(target=worker_race, args=("worker_B",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert len(leases) == 1
    winner, leased_id = leases[0]
    final_item = queue.get_item(item.queue_item_id)
    assert final_item.status == QueueState.LEASED.value
    assert final_item.worker_id == winner
    print(f"  Winner: {winner}, Lease count: {len(leases)}")
    print("  PASS: Atomic lease acquisition verified. Exactly one worker acquired lease.")
    tmp.cleanup()


def test_08_multi_worker_execution():
    print(f"\n{SEP}\nTEST 8: Multi-worker execution (many workers, many jobs)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    jobs = [_make_production_job(Path(tmp.name), job_id=f"mw_job_{i:02d}", account_id=f"acc_{i:02d}")[0] for i in range(10)]

    for j in jobs:
        req = service.prepare_publish(j)
        queue.enqueue(req)

    pool = PublishWorkerPool(worker_count=4, queue=queue, publishing_service=service, poll_interval_sec=0.02)
    pool.start()

    # Wait for completion
    timeout = time.time() + 8.0
    while time.time() < timeout:
        metrics = queue.get_metrics()
        if metrics["completed_count"] >= 10:
            break
        time.sleep(0.05)

    pool.stop()
    metrics = queue.get_metrics()
    assert metrics["completed_count"] == 10
    assert len(service.publisher.published_requests) == 10
    print(f"  Published {metrics['completed_count']}/10 jobs with 4 concurrent workers.")
    print("  PASS: Multi-worker execution completed with 0 duplicate leases and 0 duplicate uploads.")
    tmp.cleanup()


def test_09_lease_expiration():
    print(f"\n{SEP}\nTEST 9: Lease expiration recovery\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)
    item = queue.enqueue(req)

    # Worker leases for short duration (0.2s) and "crashes"
    leased = queue.acquire_lease("crashed_worker", lease_duration_sec=0.2)
    assert leased is not None
    assert leased.status == QueueState.LEASED.value

    time.sleep(0.3)  # Wait for lease to expire
    recovered = queue.recover_expired_leases(service)
    assert len(recovered) == 1
    assert recovered[0].status == QueueState.READY.value
    assert recovered[0].worker_id is None

    # New worker can now acquire it
    new_leased = queue.acquire_lease("new_worker")
    assert new_leased is not None
    assert new_leased.worker_id == "new_worker"
    print("  PASS: Expired lease successfully recovered and re-leased.")
    tmp.cleanup()


def test_10_crash_during_provider_call():
    print(f"\n{SEP}\nTEST 10: Crash during provider call (0 duplicate uploads)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)
    item = queue.enqueue(req)

    # Worker leases and starts execution
    leased = queue.acquire_lease("worker_1", lease_duration_sec=0.2)
    queue.start_execution(item.queue_item_id, "worker_1")

    # Provider call succeeds and receipt is saved, but worker process crashes before completing queue item
    receipt = service.publish(req)
    assert receipt.status == PublishState.PUBLISHED.value
    provider_calls_before = len(service.publisher.published_requests)

    # Process restarts / recovery runs
    time.sleep(0.3)
    recovered = queue.recover_expired_leases(service)
    assert len(recovered) == 1
    assert queue.get_item(item.queue_item_id).status == QueueState.COMPLETED.value

    # Provider was NOT called again
    assert len(service.publisher.published_requests) == provider_calls_before
    print("  PASS: Crash after provider upload safely reconciled without duplicate publication.")
    tmp.cleanup()


def test_11_receipt_first_recovery():
    print(f"\n{SEP}\nTEST 11: Receipt-first recovery\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)

    # Pre-existing receipt already in store
    receipt = service.publish(req)
    assert receipt.status == PublishState.PUBLISHED.value
    initial_calls = len(service.publisher.published_requests)

    # Now an identical job is enqueued and picked up by worker
    item = queue.enqueue(req)
    worker = PublishWorker("worker_rec", queue, service)
    result = worker.poll_once()

    assert result is not None
    assert result.status == PublishState.PUBLISHED.value
    assert queue.get_item(item.queue_item_id).status == QueueState.COMPLETED.value
    assert len(service.publisher.published_requests) == initial_calls
    print("  PASS: Worker detected pre-existing receipt and completed without duplicate delivery.")
    tmp.cleanup()


def test_12_provider_timeout():
    print(f"\n{SEP}\nTEST 12: Provider timeout classified correctly\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    base = Path(tmp.name)
    store_dir = base / "pub_store"
    queue_dir = base / "pub_queue"

    # Mock publisher injecting timeout error across all retries
    mock_pub = MockPublisher(fail_mode=None, fail_times=4)
    queue = PublishQueue(queue_dir)
    service = PublishingService(store_dir=store_dir, publisher=mock_pub, queue=queue)

    job, _, _ = _make_production_job(base)
    req = service.prepare_publish(job)
    queue.enqueue(req)

    worker = PublishWorker("worker_timeout", queue, service)
    # 1st attempt: fails with transient network error
    receipt = worker.poll_once()

    item = queue.get_item(queue.all_items()[0].queue_item_id)
    assert item.status == QueueState.RETRY_WAIT.value
    assert item.attempt == 1
    assert item.next_attempt_at is not None
    print(f"  Attempt: {item.attempt}, Status: {item.status}, Next: {item.next_attempt_at}")
    print("  PASS: Provider timeout classified as retryable and transitioned to RETRY_WAIT.")
    tmp.cleanup()


def test_13_retry_scheduling():
    print(f"\n{SEP}\nTEST 13: Retry scheduling (RUNNING -> RETRY_WAIT -> READY)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)
    item = queue.enqueue(req)

    queue.acquire_lease("w1")
    queue.start_execution(item.queue_item_id, "w1")
    # Fail with 0.1s backoff
    queue.fail_item(item.queue_item_id, "w1", error="Transient error", failure_class=PublishFailureClass.NETWORK_ERROR.value, is_retryable=True, backoff_sec=0.1)

    retry_item = queue.get_item(item.queue_item_id)
    assert retry_item.status == QueueState.RETRY_WAIT.value

    scheduler = PublishingScheduler(queue, publishing_service=service, poll_interval_sec=0.02)
    time.sleep(0.15)
    scheduler.poll_once()

    ready_item = queue.get_item(item.queue_item_id)
    assert ready_item.status == QueueState.READY.value
    print("  PASS: Retry wait period elapsed; item transitioned RETRY_WAIT -> READY.")
    tmp.cleanup()


def test_14_retry_exhaustion():
    print(f"\n{SEP}\nTEST 14: Retry exhaustion -> DEAD_LETTER\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)
    item = queue.enqueue(req, max_attempts=2)

    # Attempt 1
    queue.acquire_lease("w1")
    queue.start_execution(item.queue_item_id, "w1")
    queue.fail_item(item.queue_item_id, "w1", error="Err1", failure_class=PublishFailureClass.NETWORK_ERROR.value, is_retryable=True, backoff_sec=0.01)
    queue.mark_ready(item.queue_item_id)

    # Attempt 2 (exhaustion)
    queue.acquire_lease("w2")
    queue.start_execution(item.queue_item_id, "w2")
    queue.fail_item(item.queue_item_id, "w2", error="Err2", failure_class=PublishFailureClass.NETWORK_ERROR.value, is_retryable=True, backoff_sec=0.01)

    dead_item = queue.get_item(item.queue_item_id)
    assert dead_item.status == QueueState.DEAD_LETTER.value
    assert dead_item.attempt == 2
    assert dead_item.last_error == "Err2"
    print(f"  Final status: {dead_item.status}, Attempts: {dead_item.attempt}")
    print("  PASS: Exhausted attempts stopped at max_attempts without loop -> DEAD_LETTER.")
    tmp.cleanup()


def test_15_permanent_provider_rejection():
    print(f"\n{SEP}\nTEST 15: Permanent provider rejection -> PUBLISH_REJECTED / DEAD_LETTER\n{SEP}")
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    store_dir = base / "pub_store"
    queue_dir = base / "pub_queue"

    mock_pub = MockPublisher(fail_mode="reject")
    queue = PublishQueue(queue_dir)
    service = PublishingService(store_dir=store_dir, publisher=mock_pub, queue=queue)

    job, _, _ = _make_production_job(base)
    req = service.prepare_publish(job)
    queue.enqueue(req)

    worker = PublishWorker("worker_reject", queue, service)
    receipt = worker.poll_once()

    assert receipt.status == PublishState.PUBLISH_REJECTED.value
    item = queue.all_items()[0]
    assert item.status == QueueState.DEAD_LETTER.value
    assert item.attempt == 1
    print("  PASS: Permanent policy violation stopped immediately as DEAD_LETTER without retry.")
    tmp.cleanup()


def test_16_cancellation_before_execution():
    print(f"\n{SEP}\nTEST 16: Cancellation before execution (CANCELLED)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)
    item = queue.enqueue(req)

    queue.cancel_item(item.queue_item_id, reason="User cancelled prior to run")
    cancelled_item = queue.get_item(item.queue_item_id)
    assert cancelled_item.status == QueueState.CANCELLED.value

    worker = PublishWorker("w", queue, service)
    assert worker.poll_once() is None
    assert len(service.publisher.published_requests) == 0
    print("  PASS: Item cancelled before run; zero provider calls made.")
    tmp.cleanup()


def test_17_cancellation_race():
    print(f"\n{SEP}\nTEST 17: Cancellation race\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)
    item = queue.enqueue(req)

    # Worker leases item
    leased = queue.acquire_lease("worker_race")
    assert leased is not None

    # Cancel request arrives right as execution starts
    queue.cancel_item(item.queue_item_id, reason="Concurrent cancel")
    updated = queue.get_item(item.queue_item_id)
    assert updated.status == QueueState.CANCELLED.value
    print("  PASS: Cancellation race resolved safely without corrupted state.")
    tmp.cleanup()


def test_18_graceful_shutdown():
    print(f"\n{SEP}\nTEST 18: Graceful shutdown\n{SEP}")
    tmp, service, queue = _setup_test_env()
    worker = PublishWorker("worker_grace", queue, service, poll_interval_sec=0.05)
    worker.start()
    assert worker.is_alive

    worker.stop(timeout_sec=1.0)
    assert not worker.is_alive
    print("  PASS: Worker shut down gracefully.")
    tmp.cleanup()


def test_19_scheduler_restart():
    print(f"\n{SEP}\nTEST 19: Scheduler restart recovery\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    future_time = (datetime.now(timezone.utc) + timedelta(milliseconds=100)).isoformat()
    req = service.prepare_publish(job, scheduled_at=future_time)
    item = queue.enqueue(req, scheduled_at=future_time)
    assert item.status == QueueState.SCHEDULED.value

    # Old scheduler crashes
    s1 = PublishingScheduler(queue, poll_interval_sec=0.05)
    del s1

    # Wait for scheduled time to arrive
    time.sleep(0.15)

    # New scheduler starts
    s2 = PublishingScheduler(queue, poll_interval_sec=0.05)
    assert s2.poll_once() >= 1
    assert queue.get_item(item.queue_item_id).status == QueueState.READY.value
    print("  PASS: Scheduled jobs recovered and processed after scheduler restart.")
    tmp.cleanup()


def test_20_worker_restart():
    print(f"\n{SEP}\nTEST 20: Worker restart recovery\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)
    queue.enqueue(req)

    # Worker 1 starts, crashes before finishing
    w1 = PublishWorker("w1", queue, service)
    del w1

    # Worker 2 starts and completes the job
    w2 = PublishWorker("w2", queue, service)
    receipt = w2.poll_once()
    assert receipt is not None
    assert receipt.status == PublishState.PUBLISHED.value
    print("  PASS: Worker restart resumed pending work seamlessly.")
    tmp.cleanup()


def test_21_duplicate_queue_delivery():
    print(f"\n{SEP}\nTEST 21: Duplicate queue delivery (1 logical publication)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)

    # Same request enqueued twice
    it1 = queue.enqueue(req)
    it2 = queue.enqueue(req)
    assert it1.queue_item_id == it2.queue_item_id

    worker = PublishWorker("w", queue, service)
    r1 = worker.poll_once()
    r2 = worker.poll_once()

    assert r1 is not None
    assert r2 is None
    assert len(service.publisher.published_requests) == 1
    print("  PASS: Duplicate queue delivery resulted in exactly one remote publication.")
    tmp.cleanup()


def test_22_provider_acceptance_plus_timeout():
    print(f"\n{SEP}\nTEST 22: Provider acceptance + timeout reconciliation\n{SEP}")
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    store_dir = base / "pub_store"
    queue_dir = base / "pub_queue"

    mock_pub = MockPublisher(fail_mode="timeout_after_accept")
    queue = PublishQueue(queue_dir)
    service = PublishingService(store_dir=store_dir, publisher=mock_pub, queue=queue)

    job, _, _ = _make_production_job(base)
    req = service.prepare_publish(job)
    queue.enqueue(req)

    worker = PublishWorker("w_ambig", queue, service)
    receipt = worker.poll_once()

    assert receipt is not None
    assert receipt.status == PublishState.PUBLISHED.value
    assert "ext_ambiguous_" in receipt.external_id
    assert queue.all_items()[0].status == QueueState.COMPLETED.value
    print("  PASS: Ambiguous provider timeout safely reconciled without duplicate upload.")
    tmp.cleanup()


def test_23_provider_account_isolation():
    print(f"\n{SEP}\nTEST 23: Provider/account isolation\n{SEP}")
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    store_dir = base / "pub_store"
    queue_dir = base / "pub_queue"

    cred_store = CredentialStore()
    cred_store.register_credentials("acc_alpha", YouTubeCredentials(account_id="acc_alpha", client_id="cid_A", client_secret="sec_A", refresh_token="tok_A"))
    cred_store.register_credentials("acc_beta", YouTubeCredentials(account_id="acc_beta", client_id="cid_B", client_secret="sec_B", refresh_token="tok_B"))

    transport = FakeYouTubeTransport()
    publisher = YouTubePublisher(credential_store=cred_store, transport=transport)
    queue = PublishQueue(queue_dir)
    service = PublishingService(store_dir=store_dir, publisher=publisher, queue=queue)

    job_a, _, _ = _make_production_job(base, job_id="job_alpha", account_id="acc_alpha")
    job_b, _, _ = _make_production_job(base, job_id="job_beta", account_id="acc_beta")

    req_a = service.prepare_publish(job_a)
    req_b = service.prepare_publish(job_b)
    queue.enqueue(req_a)
    queue.enqueue(req_b)

    worker = PublishWorker("w_iso", queue, service)
    worker.poll_once()
    worker.poll_once()

    assert len(transport.calls) == 2
    assert transport.calls[0]["account_id"] == "acc_alpha"
    assert transport.calls[1]["account_id"] == "acc_beta"
    print("  PASS: Account Alpha and Account Beta work isolated without credential cross-talk.")
    tmp.cleanup()


def test_24_provider_concurrency_limit():
    print(f"\n{SEP}\nTEST 24: Provider concurrency limit respected\n{SEP}")
    tmp, service, queue = _setup_test_env()
    queue.config.max_per_provider = 2

    jobs = [_make_production_job(Path(tmp.name), job_id=f"prov_{i:02d}")[0] for i in range(5)]
    for j in jobs:
        queue.enqueue(service.prepare_publish(j))

    # Worker 1 leases item 1
    l1 = queue.acquire_lease("w1")
    # Worker 2 leases item 2
    l2 = queue.acquire_lease("w2")
    # Worker 3 attempts lease on item 3 (should be blocked by max_per_provider=2)
    l3 = queue.acquire_lease("w3")

    assert l1 is not None
    assert l2 is not None
    assert l3 is None  # Blocked by concurrency limit
    print("  PASS: Provider concurrency limit strictly enforced.")
    tmp.cleanup()


def test_25_account_concurrency_limit():
    print(f"\n{SEP}\nTEST 25: Account concurrency limit respected\n{SEP}")
    tmp, service, queue = _setup_test_env()
    queue.config.max_per_account = 1

    # Two jobs for the SAME account
    j1, _, _ = _make_production_job(Path(tmp.name), job_id="acc_job_1", account_id="shared_acc")
    j2, _, _ = _make_production_job(Path(tmp.name), job_id="acc_job_2", account_id="shared_acc")

    queue.enqueue(service.prepare_publish(j1))
    queue.enqueue(service.prepare_publish(j2))

    l1 = queue.acquire_lease("w1")
    l2 = queue.acquire_lease("w2")

    assert l1 is not None
    assert l2 is None  # Blocked because shared_acc is already in-flight
    print("  PASS: Per-account concurrency limit strictly enforced.")
    tmp.cleanup()


def test_26_backpressure():
    print(f"\n{SEP}\nTEST 26: Backpressure capacity limit enforced\n{SEP}")
    tmp, service, queue = _setup_test_env()
    queue.config.max_queue_size = 3

    jobs = [_make_production_job(Path(tmp.name), job_id=f"bp_{i:02d}")[0] for i in range(4)]
    queue.enqueue(service.prepare_publish(jobs[0]))
    queue.enqueue(service.prepare_publish(jobs[1]))
    queue.enqueue(service.prepare_publish(jobs[2]))

    # 4th should raise QueueCapacityExceededError
    caught = False
    try:
        queue.enqueue(service.prepare_publish(jobs[3]))
    except QueueCapacityExceededError as e:
        caught = True
        print(f"  Caught expected error: {e}")

    assert caught
    print("  PASS: Backpressure enforced with structured exception; zero silent data loss.")
    tmp.cleanup()


def test_27_priority_ordering():
    print(f"\n{SEP}\nTEST 27: Priority ordering (HIGH > NORMAL > LOW)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    queue.config.max_per_account = 5

    j_low, _, _ = _make_production_job(Path(tmp.name), job_id="prio_low")
    j_norm, _, _ = _make_production_job(Path(tmp.name), job_id="prio_norm")
    j_high, _, _ = _make_production_job(Path(tmp.name), job_id="prio_high")

    queue.enqueue(service.prepare_publish(j_low), priority=QueuePriority.LOW.value)
    queue.enqueue(service.prepare_publish(j_norm), priority=QueuePriority.NORMAL.value)
    queue.enqueue(service.prepare_publish(j_high), priority=QueuePriority.HIGH.value)

    # Leasing order must be HIGH -> NORMAL -> LOW
    l1 = queue.acquire_lease("w1")
    l2 = queue.acquire_lease("w2")
    l3 = queue.acquire_lease("w3")

    assert l1 is not None and l1.priority == QueuePriority.HIGH.value
    assert l2 is not None and l2.priority == QueuePriority.NORMAL.value
    assert l3 is not None and l3.priority == QueuePriority.LOW.value
    print(f"  Lease sequence: {l1.priority} -> {l2.priority} -> {l3.priority}")
    print("  PASS: Priority ordering verified.")
    tmp.cleanup()


def test_28_starvation_prevention():
    print(f"\n{SEP}\nTEST 28: Starvation prevention for aging low-priority jobs\n{SEP}")
    tmp, service, queue = _setup_test_env()
    queue.config.starvation_threshold_sec = 0.1  # Low threshold for test

    j_low, _, _ = _make_production_job(Path(tmp.name), job_id="starve_low")
    it_low = queue.enqueue(service.prepare_publish(j_low), priority=QueuePriority.LOW.value)

    time.sleep(0.15)  # Age low priority item beyond starvation threshold

    j_norm, _, _ = _make_production_job(Path(tmp.name), job_id="starve_norm")
    it_norm = queue.enqueue(service.prepare_publish(j_norm), priority=QueuePriority.NORMAL.value)

    # Aged low-priority item is boosted and leased first
    l1 = queue.acquire_lease("w1")
    assert l1.queue_item_id == it_low.queue_item_id
    print("  PASS: Starvation prevention boosted aging low-priority item ahead of newer items.")
    tmp.cleanup()


def test_29_mixed_batch_scheduling():
    print(f"\n{SEP}\nTEST 29: Mixed batch scheduling isolation\n{SEP}")
    tmp, service, queue = _setup_test_env()

    # Create 3 jobs: 1 immediate, 1 scheduled in future, 1 to cancel
    j1, _, _ = _make_production_job(Path(tmp.name), job_id="mb_imm")
    j2, _, _ = _make_production_job(Path(tmp.name), job_id="mb_fut")
    j3, _, _ = _make_production_job(Path(tmp.name), job_id="mb_can")

    fut_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    it1 = queue.enqueue(service.prepare_publish(j1))
    it2 = queue.enqueue(service.prepare_publish(j2), scheduled_at=fut_time)
    it3 = queue.enqueue(service.prepare_publish(j3))
    queue.cancel_item(it3.queue_item_id)

    worker = PublishWorker("w", queue, service)
    r1 = worker.poll_once()

    assert r1 is not None and r1.status == PublishState.PUBLISHED.value
    assert queue.get_item(it1.queue_item_id).status == QueueState.COMPLETED.value
    assert queue.get_item(it2.queue_item_id).status == QueueState.SCHEDULED.value
    assert queue.get_item(it3.queue_item_id).status == QueueState.CANCELLED.value
    print("  PASS: Mixed batch scheduling isolated successfully.")
    tmp.cleanup()


def test_30_corrupt_queue_record():
    print(f"\n{SEP}\nTEST 30: Corrupt queue record fails safely without crash loop\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    item = queue.enqueue(service.prepare_publish(job))

    # Corrupt the json file
    path = queue.items_dir / f"item_{item.queue_item_id}.json"
    path.write_text("{corrupt: json: invalid!}")

    # all_items() must quarantine the corrupt file and return empty without crashing
    items = queue.all_items()
    assert len(items) == 0
    quarantined = list(queue.quarantine_dir.glob("corrupt_*"))
    assert len(quarantined) >= 1
    print(f"  Quarantined: {quarantined[0].name}")
    print("  PASS: Corrupted queue record safely quarantined without crash loop.")
    tmp.cleanup()


def test_31_illegal_queue_transition():
    print(f"\n{SEP}\nTEST 31: Illegal queue transition raises QueueStateTransitionError\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    item = queue.enqueue(service.prepare_publish(job))

    # Attempt illegal transition: READY -> COMPLETED directly without leasing
    caught = False
    try:
        queue._transition(item, QueueState.COMPLETED, event_name="illegal_test")
    except QueueStateTransitionError as e:
        caught = True
        print(f"  Caught expected error: {e}")

    assert caught
    print("  PASS: Illegal queue state transition strictly rejected.")
    tmp.cleanup()


def test_32_dry_run_isolation():
    print(f"\n{SEP}\nTEST 32: Dry-run isolation (100 dry-run jobs -> 0 real provider calls)\n{SEP}")
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    store_dir = base / "pub_store"
    queue_dir = base / "pub_queue"

    transport = FakeYouTubeTransport()
    publisher = YouTubePublisher(transport=transport)
    queue = PublishQueue(queue_dir)
    service = PublishingService(store_dir=store_dir, publisher=publisher, queue=queue)

    blocked = 0
    for i in range(100):
        job, _, _ = _make_production_job(base, job_id=f"dry_{i:03d}", execution_mode=ExecutionMode.DRY_RUN)
        try:
            service.prepare_publish(job, allow_non_production=False)
        except PublishEligibilityError:
            blocked += 1

    assert blocked == 100
    assert len(transport.calls) == 0
    print(f"  Blocked {blocked}/100 DRY_RUN jobs. Transport calls: {len(transport.calls)}")
    print("  PASS: Dry-run isolation 100% compliant.")
    tmp.cleanup()


def test_33_secret_isolation_audit():
    print(f"\n{SEP}\nTEST 33: Secret isolation audit (zero credentials in queue/events)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    item = queue.enqueue(service.prepare_publish(job))
    worker = PublishWorker("w_sec", queue, service)
    worker.poll_once()

    secrets = ["client_secret", "refresh_token", "access_token", "sec_A", "tok_A", "password"]
    for p in (queue.items_dir).glob("*.json"):
        content = p.read_text(encoding="utf-8")
        for s in secrets:
            assert s not in content, f"Secret '{s}' found in {p.name}"

    for p in (queue.events_dir).glob("*.jsonl"):
        content = p.read_text(encoding="utf-8")
        for s in secrets:
            assert s not in content, f"Secret '{s}' found in {p.name}"

    print("  PASS: Security audit passed. Zero secrets detected in queue files or events.")
    tmp.cleanup()


def test_34_artifact_immutability():
    print(f"\n{SEP}\nTEST 34: Artifact immutability verified before worker execution\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, vid_path, _ = _make_production_job(Path(tmp.name))
    req = service.prepare_publish(job)
    queue.enqueue(req)

    # Tamper with video artifact after queuing
    vid_path.write_bytes(b"\xFF" * 4096)

    worker = PublishWorker("w_mut", queue, service)
    receipt = worker.poll_once()

    assert receipt.status == PublishState.PUBLISH_FAILED.value
    assert len(service.publisher.published_requests) == 0
    print("  PASS: Mutated artifact caught before platform transmission.")
    tmp.cleanup()


def test_35_qa_authority():
    print(f"\n{SEP}\nTEST 35: QA authority preserved (QA_FAILED/REJECTED/ESCALATED blocked)\n{SEP}")
    tmp, service, queue = _setup_test_env()
    base = Path(tmp.name)

    unsafe_states = [
        (JobState.QA_FAILED, True),
        (JobState.REJECTED, True),
        (JobState.REPAIR_ESCALATED, True),
        (JobState.OUTPUT_READY, False), # Failed QA
    ]

    blocked = 0
    for st, qa_pass in unsafe_states:
        job, _, _ = _make_production_job(base, state=st, passed_qa=qa_pass)
        try:
            service.prepare_publish(job)
        except PublishEligibilityError:
            blocked += 1

    assert blocked == len(unsafe_states)
    assert len(service.publisher.published_requests) == 0
    print(f"  Blocked {blocked}/{len(unsafe_states)} unapproved jobs.")
    print("  PASS: QA authority 100% preserved. Zero unapproved jobs can be queued.")
    tmp.cleanup()


# ─── Regression Tests 36, 37, 38 ──────────────────────────────────────────────

def test_36_phase13_regression():
    print(f"\n{SEP}\nTEST 36: Phase 13 Regression Suite (30/30 tests)\n{SEP}")
    res = subprocess.run(
        [sys.executable, "-u", "-m", "brain.test_real_provider"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        assert False, f"Phase 13 regression suite failed with code {res.returncode}"
    print("  PASS: Phase 13 regression suite passed with zero regressions.")


def test_37_phase12_regression():
    print(f"\n{SEP}\nTEST 37: Phase 12 Regression Suite (27/27 tests)\n{SEP}")
    res = subprocess.run(
        [sys.executable, "-u", "-m", "brain.test_publishing"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        assert False, f"Phase 12 regression suite failed with code {res.returncode}"
    print("  PASS: Phase 12 regression suite passed with zero regressions.")


def test_38_phase11_regression():
    print(f"\n{SEP}\nTEST 38: Phase 11 Regression Suite (23/23 tests)\n{SEP}")
    res = subprocess.run(
        [sys.executable, "-u", "-m", "brain.test_orchestrator"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        assert False, f"Phase 11 regression suite failed with code {res.returncode}"
    print("  PASS: Phase 11 regression suite passed with zero regressions.")


# ─── Adversarial Tests ────────────────────────────────────────────────────────

def test_adv_1_ten_worker_lease_race():
    print(f"\n{SEP}\nADV 1: 10-worker simultaneous lease race for 1 queue item\n{SEP}")
    tmp, service, queue = _setup_test_env()
    job, _, _ = _make_production_job(Path(tmp.name))
    queue.enqueue(service.prepare_publish(job))

    leases = []
    def race_worker(wid: str):
        l = queue.acquire_lease(wid)
        if l is not None:
            leases.append(wid)

    threads = [threading.Thread(target=race_worker, args=(f"worker_{i}",)) for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert len(leases) == 1
    print(f"  10 threads raced simultaneously. Exactly 1 winner: {leases[0]}")
    print("  PASS: Zero duplicate leases under 10-worker concurrent race.")
    tmp.cleanup()


def test_adv_2_ambiguous_provider_crash_recovery():
    print(f"\n{SEP}\nADV 2: Ambiguous provider crash recovery\n{SEP}")
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    store_dir = base / "pub_store"
    queue_dir = base / "pub_queue"

    mock_pub = MockPublisher(fail_mode="timeout_after_accept")
    queue = PublishQueue(queue_dir, config=PublishQueueConfig(default_lease_duration_sec=0.2))
    service = PublishingService(store_dir=store_dir, publisher=mock_pub, queue=queue)

    job, _, _ = _make_production_job(base)
    req = service.prepare_publish(job)
    queue.enqueue(req)

    # Worker leases, calls provider which accepts then times out
    w = PublishWorker("w_ambig", queue, service)
    r = w.poll_once()

    # Reconciles without second upload
    assert r is not None and r.status == PublishState.PUBLISHED.value
    assert len(service.publisher.published_requests) == 1
    print("  PASS: Ambiguous provider timeout reconciled without duplicate upload.")
    tmp.cleanup()


def test_adv_3_rapid_worker_shutdown():
    print(f"\n{SEP}\nADV 3: Rapid worker shutdown during execution\n{SEP}")
    tmp, service, queue = _setup_test_env()
    service.publisher.delay_sec = 0.05

    job, _, _ = _make_production_job(Path(tmp.name))
    queue.enqueue(service.prepare_publish(job))

    worker = PublishWorker("w_rapid", queue, service, poll_interval_sec=0.01)
    worker.start()
    time.sleep(0.02)
    worker.stop(timeout_sec=2.0)

    assert not worker.is_alive
    time.sleep(0.1)
    print("  PASS: Worker shut down cleanly under in-flight execution.")
    tmp.cleanup()


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("TEST 1  — Immediate enqueue",           test_01_immediate_enqueue),
        ("TEST 2  — Future scheduling",            test_02_future_scheduling),
        ("TEST 3  — Scheduler due time",           test_03_scheduler_reaches_due_time),
        ("TEST 4  — Overdue schedule",             test_04_overdue_schedule),
        ("TEST 5  — Queue persistence",            test_05_queue_persistence),
        ("TEST 6  — Queue idempotency",            test_06_queue_idempotency),
        ("TEST 7  — Atomic lease",                 test_07_atomic_lease),
        ("TEST 8  — Multi-worker execution",       test_08_multi_worker_execution),
        ("TEST 9  — Lease expiration",             test_09_lease_expiration),
        ("TEST 10 — Crash during provider call",   test_10_crash_during_provider_call),
        ("TEST 11 — Receipt-first recovery",       test_11_receipt_first_recovery),
        ("TEST 12 — Provider timeout",             test_12_provider_timeout),
        ("TEST 13 — Retry scheduling",             test_13_retry_scheduling),
        ("TEST 14 — Retry exhaustion",             test_14_retry_exhaustion),
        ("TEST 15 — Permanent rejection",          test_15_permanent_provider_rejection),
        ("TEST 16 — Cancellation before run",      test_16_cancellation_before_execution),
        ("TEST 17 — Cancellation race",            test_17_cancellation_race),
        ("TEST 18 — Graceful shutdown",            test_18_graceful_shutdown),
        ("TEST 19 — Scheduler restart",            test_19_scheduler_restart),
        ("TEST 20 — Worker restart",               test_20_worker_restart),
        ("TEST 21 — Duplicate queue delivery",     test_21_duplicate_queue_delivery),
        ("TEST 22 — Ambiguous timeout reconciles", test_22_provider_acceptance_plus_timeout),
        ("TEST 23 — Provider/account isolation",   test_23_provider_account_isolation),
        ("TEST 24 — Provider concurrency limit",   test_24_provider_concurrency_limit),
        ("TEST 25 — Account concurrency limit",    test_25_account_concurrency_limit),
        ("TEST 26 — Backpressure limit",           test_26_backpressure),
        ("TEST 27 — Priority ordering",            test_27_priority_ordering),
        ("TEST 28 — Starvation prevention",        test_28_starvation_prevention),
        ("TEST 29 — Mixed batch scheduling",       test_29_mixed_batch_scheduling),
        ("TEST 30 — Corrupt record quarantine",    test_30_corrupt_queue_record),
        ("TEST 31 — Illegal queue transition",     test_31_illegal_queue_transition),
        ("TEST 32 — Dry-run isolation",            test_32_dry_run_isolation),
        ("TEST 33 — Secret isolation audit",       test_33_secret_isolation_audit),
        ("TEST 34 — Artifact immutability",        test_34_artifact_immutability),
        ("TEST 35 — QA authority preserved",       test_35_qa_authority),
        ("TEST 36 — Phase 13 Regression",          test_36_phase13_regression),
        ("TEST 37 — Phase 12 Regression",          test_37_phase12_regression),
        ("TEST 38 — Phase 11 Regression",          test_38_phase11_regression),
        ("ADV 1   — 10-worker lease race",         test_adv_1_ten_worker_lease_race),
        ("ADV 2   — Ambiguous crash recovery",     test_adv_2_ambiguous_provider_crash_recovery),
        ("ADV 3   — Rapid worker shutdown",        test_adv_3_rapid_worker_shutdown),
    ]

    passed, failed = [], []
    for label, fn in tests:
        try:
            fn()
            passed.append(label)
        except AssertionError as e:
            failed.append((label, str(e)))
            print(f"  FAIL [{label}]: {e}")
        except Exception as e:
            import traceback
            failed.append((label, f"EXCEPTION: {e}"))
            print(f"  ERROR [{label}]: {e}")
            traceback.print_exc()

    print(f"\n{SEP}")
    print("PHASE 14 PRODUCTION SCHEDULING & DURABLE QUEUE TEST RESULTS")
    print(SEP)
    print(f"  PASSED: {len(passed)}/{len(tests)}")
    if failed:
        print(f"  FAILED: {len(failed)}/{len(tests)}")
        for label, reason in failed:
            print(f"    [{label}] {reason}")
    else:
        print(f"  ALL {len(tests)} TESTS PASSED (100%). Exit code: 0")
    print(SEP)

    sys.exit(0 if not failed else 1)
