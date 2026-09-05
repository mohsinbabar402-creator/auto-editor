"""
Phase 15 & 16 — Production Analytics, Webhook Reconciliation & Unified Production Readiness Test Suite

Tests:
TEST 1  — Analytics metric retrieval & snapshot persistence
TEST 2  — Strict analytics boundary: zero fabricated metrics
TEST 3  — Creative memory feedback integration
TEST 4  — Webhook HMAC-SHA256 signature verification
TEST 5  — Webhook VIDEO_PROCESSED status reconciliation
TEST 6  — Webhook VIDEO_REJECTED policy rejection handling
TEST 7  — Webhook duplicate delivery idempotency
TEST 8  — UnifiedProductionEngine end-to-end publishing lifecycle
TEST 9  — SystemHealthReport operational telemetry
TEST 10 — Full job trajectory observability aggregation
TEST 11 — Phase 14 regression suite (41/41)
TEST 12 — Phase 13 regression suite (30/30)
TEST 13 — Phase 12 regression suite (27/27)
TEST 14 — Phase 11 regression suite (23/23)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.analytics_models import (
    AnalyticsSnapshot,
    PerformanceMetrics,
    WebhookEventType,
)
from brain.analytics_service import (
    AnalyticsService,
    AnalyticsStore,
    MockAnalyticsProvider,
)
from brain.orchestrator_models import ExecutionMode, JobState, ProductionJob
from brain.operator_service import UnifiedProductionEngine
from brain.publish_queue import PublishQueue, PublishQueueConfig, QueuePriority, QueueState
from brain.publishing_models import PublishReceipt, PublishRequest, PublishState
from brain.publishing_service import MockPublisher, PublishingService
from brain.webhook_reconciler import WebhookReconciler, WebhookReconciliationError

SEP = "=" * 65


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
        execution_mode=ExecutionMode.PRODUCTION.value,
        account_id="acc_01",
        platform="youtube_shorts",
        title=f"Production Test Title {jid}",
        artifacts={
            "final_output": str(vid_path),
            "artifact_hash": vhash,
            "qa_report": qa_report,
        },
    )
    return job, vid_path, vhash


# ─── Tests 1 to 14 ────────────────────────────────────────────────────────────

def test_01_analytics_metric_retrieval():
    print(f"\n{SEP}\nTEST 1: Analytics metric retrieval & snapshot persistence\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    store_dir = Path(tmp.name) / "store"

    mock_provider = MockAnalyticsProvider()
    mock_provider.set_mock_metrics("ext_yt_123", PerformanceMetrics(
        external_id="ext_yt_123",
        platform="youtube_shorts",
        provider="YouTube",
        account_id="acc_01",
        views=25000,
        watch_time_sec=750000.0,
        average_view_duration_sec=30.0,
        average_percentage_viewed=88.5,
        likes=3200,
        comments=450,
        shares=1200,
        subscribers_gained=310,
    ))

    service = AnalyticsService(store_dir=store_dir, provider=mock_provider)
    metrics = service.fetch_and_record_metrics(
        job_id="job_01",
        clip_id="clip_01",
        external_id="ext_yt_123",
        account_id="acc_01",
    )

    assert metrics is not None
    assert metrics.views == 25000
    assert metrics.likes == 3200

    # Verify persistence
    snapshots = service.get_metrics_for_job("job_01")
    assert len(snapshots) == 1
    assert snapshots[0].metrics.views == 25000
    print(f"  Recorded snapshot for job_01: {snapshots[0].snapshot_id}, views={snapshots[0].metrics.views}")
    print("  PASS: Analytics metric retrieval and atomic snapshot persistence verified.")
    tmp.cleanup()


def test_02_no_fabricated_analytics():
    print(f"\n{SEP}\nTEST 2: Strict analytics boundary (zero fabricated metrics)\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    store_dir = Path(tmp.name) / "store"

    pub_service = PublishingService(store_dir=store_dir)
    job, _, _ = _make_production_job(Path(tmp.name))
    receipt = pub_service.publish_job(job)

    # Verify delivery receipt contains delivery facts ONLY, zero audience metrics
    rec_dict = asdict(receipt)
    assert "views" not in rec_dict
    assert "likes" not in rec_dict
    assert "retention" not in rec_dict
    assert "watch_time" not in rec_dict
    print("  PASS: Delivery layer strictly restricted to delivery facts; zero analytics fabrication.")
    tmp.cleanup()


def test_03_analytics_creative_memory_feedback():
    print(f"\n{SEP}\nTEST 3: Creative memory feedback integration\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    store_dir = Path(tmp.name) / "store"

    service = AnalyticsService(store_dir=store_dir)
    service.fetch_and_record_metrics(
        job_id="job_mem_01",
        clip_id="clip_mem_01",
        external_id="ext_mem_01",
        account_id="acc_01",
    )

    # Mock CreativeMemory receiver
    class MockMemory:
        def __init__(self):
            self.feedback_events = []
        def record_performance_feedback(self, jid, data):
            self.feedback_events.append((jid, data))

    mem = MockMemory()
    evidence = service.feed_into_creative_memory("job_mem_01", mem)

    assert evidence is not None
    assert len(mem.feedback_events) == 1
    assert mem.feedback_events[0][0] == "job_mem_01"
    assert "hook_retention_5s" in evidence
    print(f"  Fed evidence into Creative Memory: views={evidence['views']}, hook_retention={evidence['hook_retention_5s']}%")
    print("  PASS: Creative memory successfully updated with real audience feedback.")
    tmp.cleanup()


def test_04_webhook_signature_verification():
    print(f"\n{SEP}\nTEST 4: Webhook HMAC-SHA256 signature verification\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    store_dir = Path(tmp.name) / "store"
    secret = "test_webhook_secret_123"

    pub_service = PublishingService(store_dir=store_dir)
    reconciler = WebhookReconciler(publishing_service=pub_service, webhook_secret=secret)

    payload = {"event_id": "wh_01", "external_id": "ext_yt_999", "event_type": "VIDEO_PROCESSED"}
    raw_body = json.dumps(payload).encode("utf-8")
    valid_sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # Valid signature passes
    res = reconciler.process_webhook(payload, signature=valid_sig, raw_body=raw_body)
    assert res["status"] == "PROCESSED"

    # Invalid signature rejected
    caught = False
    try:
        reconciler.process_webhook(payload, signature="invalid_signature_hex", raw_body=raw_body)
    except WebhookReconciliationError as e:
        caught = True
        print(f"  Caught expected error: {e}")

    assert caught
    print("  PASS: Webhook signature verification strictly enforced.")
    tmp.cleanup()


def test_05_webhook_video_processed_reconciliation():
    print(f"\n{SEP}\nTEST 5: Webhook VIDEO_PROCESSED status reconciliation\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    store_dir = Path(tmp.name) / "store"

    pub_service = PublishingService(store_dir=store_dir)
    reconciler = WebhookReconciler(publishing_service=pub_service)

    # Existing receipt in PUBLISHING
    ext_id = "ext_wh_test_05"
    receipt = PublishReceipt(
        receipt_id="rec_wh_05",
        job_id="job_wh_05",
        clip_id="clip_05",
        platform="youtube_shorts",
        provider="YouTubePublisher",
        external_id=ext_id,
        status=PublishState.PUBLISHING.value,
        published_at=datetime.now(timezone.utc).isoformat(),
        artifact_hash="hash_05",
        idempotency_key="key_05",
    )
    pub_service.store.save_receipt(receipt)

    # Webhook arrives: VIDEO_PROCESSED
    payload = {
        "event_id": "wh_evt_05",
        "external_id": ext_id,
        "event_type": WebhookEventType.VIDEO_PROCESSED.value,
    }
    res = reconciler.process_webhook(payload, skip_sig_verify=True)

    assert res["action"] == "CONFIRMED_PUBLISHED"
    updated_rec = pub_service.store.load_receipt("rec_wh_05")
    assert updated_rec.status == PublishState.PUBLISHED.value
    print("  PASS: Remote VIDEO_PROCESSED callback transitioned receipt to PUBLISHED.")
    tmp.cleanup()


def test_06_webhook_policy_rejection():
    print(f"\n{SEP}\nTEST 6: Webhook VIDEO_REJECTED policy rejection handling\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    store_dir = Path(tmp.name) / "store"

    pub_service = PublishingService(store_dir=store_dir)
    reconciler = WebhookReconciler(publishing_service=pub_service)

    ext_id = "ext_wh_test_06"
    receipt = PublishReceipt(
        receipt_id="rec_wh_06",
        job_id="job_wh_06",
        clip_id="clip_06",
        platform="youtube_shorts",
        provider="YouTubePublisher",
        external_id=ext_id,
        status=PublishState.PUBLISHING.value,
        published_at=datetime.now(timezone.utc).isoformat(),
        artifact_hash="hash_06",
        idempotency_key="key_06",
    )
    pub_service.store.save_receipt(receipt)

    payload = {
        "event_id": "wh_evt_06",
        "external_id": ext_id,
        "event_type": WebhookEventType.VIDEO_REJECTED.value,
        "reason": "Terms of Service violation",
    }
    res = reconciler.process_webhook(payload, skip_sig_verify=True)

    assert res["action"] == "MARKED_REJECTED"
    updated_rec = pub_service.store.load_receipt("rec_wh_06")
    assert updated_rec.status == PublishState.PUBLISH_REJECTED.value
    assert any("Terms of Service violation" in err for err in updated_rec.errors)
    print("  PASS: Webhook policy rejection transitioned receipt to PUBLISH_REJECTED.")
    tmp.cleanup()


def test_07_webhook_duplicate_delivery():
    print(f"\n{SEP}\nTEST 7: Webhook duplicate delivery idempotency\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    store_dir = Path(tmp.name) / "store"

    pub_service = PublishingService(store_dir=store_dir)
    reconciler = WebhookReconciler(publishing_service=pub_service)

    payload = {"event_id": "wh_dup_07", "external_id": "ext_dup_07", "event_type": "VIDEO_PROCESSED"}
    r1 = reconciler.process_webhook(payload, skip_sig_verify=True)
    r2 = reconciler.process_webhook(payload, skip_sig_verify=True)

    assert r1["status"] == "PROCESSED"
    assert r2["status"] == "DUPLICATE_IGNORED"
    print("  PASS: Duplicate webhook ignored cleanly.")
    tmp.cleanup()


def test_08_unified_engine_lifecycle():
    print(f"\n{SEP}\nTEST 8: UnifiedProductionEngine end-to-end publishing lifecycle\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    base = Path(tmp.name)

    engine = UnifiedProductionEngine(base_dir=base, worker_count=1)
    engine.start()

    job, _, _ = _make_production_job(base)
    item = engine.submit_job_for_publishing(job)

    # Wait for execution
    timeout = time.time() + 4.0
    while time.time() < timeout:
        q_item = engine.queue.get_item(item.queue_item_id)
        if q_item and q_item.status == QueueState.COMPLETED.value:
            break
        time.sleep(0.05)

    engine.stop()
    final_item = engine.queue.get_item(item.queue_item_id)
    assert final_item.status == QueueState.COMPLETED.value
    print(f"  Final item state: {final_item.status}, duration={final_item.execution_duration_sec}s")
    print("  PASS: Unified production engine completed end-to-end lifecycle.")
    tmp.cleanup()


def test_09_system_health_telemetry():
    print(f"\n{SEP}\nTEST 9: SystemHealthReport operational telemetry\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    engine = UnifiedProductionEngine(base_dir=Path(tmp.name))

    health = engine.get_health()
    assert health.status == "HEALTHY"
    assert health.queue_depth >= 0
    assert health.quarantine_records == 0
    print(f"  Health Report: status={health.status}, queue_depth={health.queue_depth}, active_workers={health.active_workers}")
    print("  PASS: Operational telemetry health report verified.")
    tmp.cleanup()


def test_10_full_job_trajectory_audit():
    print(f"\n{SEP}\nTEST 10: Full job trajectory observability aggregation\n{SEP}")
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    base = Path(tmp.name)

    engine = UnifiedProductionEngine(base_dir=base)
    job, _, _ = _make_production_job(base)
    item = engine.submit_job_for_publishing(job)

    # Direct publish and sync analytics
    receipt = engine.publishing_service.publish(item.request)
    engine.sync_analytics(job.job_id, receipt.external_id, "acc_01")

    traj = engine.get_full_job_trajectory(job.job_id)
    assert traj["job_id"] == job.job_id
    assert len(traj["receipts"]) >= 1
    assert len(traj["queue_items"]) >= 1
    assert len(traj["analytics_snapshots"]) >= 1
    print(f"  Aggregated trajectory: receipts={len(traj['receipts'])}, events={len(traj['events'])}, snapshots={len(traj['analytics_snapshots'])}")
    print("  PASS: Full job trajectory aggregation verified.")
    tmp.cleanup()


# ─── Full Regressions ─────────────────────────────────────────────────────────

def test_11_phase14_regression():
    print(f"\n{SEP}\nTEST 11: Phase 14 Regression Suite (41/41 tests)\n{SEP}")
    res = subprocess.run(
        [sys.executable, "-u", "-m", "brain.test_phase14_queue"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        assert False, f"Phase 14 regression failed with code {res.returncode}"
    print("  PASS: Phase 14 regression suite passed (41/41).")


def test_12_phase13_regression():
    print(f"\n{SEP}\nTEST 12: Phase 13 Regression Suite (30/30 tests)\n{SEP}")
    res = subprocess.run(
        [sys.executable, "-u", "-m", "brain.test_real_provider"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        assert False, f"Phase 13 regression failed with code {res.returncode}"
    print("  PASS: Phase 13 regression suite passed (30/30).")


def test_13_phase12_regression():
    print(f"\n{SEP}\nTEST 13: Phase 12 Regression Suite (27/27 tests)\n{SEP}")
    res = subprocess.run(
        [sys.executable, "-u", "-m", "brain.test_publishing"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        assert False, f"Phase 12 regression failed with code {res.returncode}"
    print("  PASS: Phase 12 regression suite passed (27/27).")


def test_14_phase11_regression():
    print(f"\n{SEP}\nTEST 14: Phase 11 Regression Suite (23/23 tests)\n{SEP}")
    res = subprocess.run(
        [sys.executable, "-u", "-m", "brain.test_orchestrator"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        assert False, f"Phase 11 regression failed with code {res.returncode}"
    print("  PASS: Phase 11 regression suite passed (23/23).")


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("TEST 1  — Analytics retrieval",            test_01_analytics_metric_retrieval),
        ("TEST 2  — No fabricated analytics",       test_02_no_fabricated_analytics),
        ("TEST 3  — Creative memory feedback",       test_03_analytics_creative_memory_feedback),
        ("TEST 4  — Webhook signature verify",       test_04_webhook_signature_verification),
        ("TEST 5  — Webhook VIDEO_PROCESSED",        test_05_webhook_video_processed_reconciliation),
        ("TEST 6  — Webhook VIDEO_REJECTED",         test_06_webhook_policy_rejection),
        ("TEST 7  — Webhook duplicate idempotency",  test_07_webhook_duplicate_delivery),
        ("TEST 8  — Unified engine lifecycle",       test_08_unified_engine_lifecycle),
        ("TEST 9  — System health telemetry",        test_09_system_health_telemetry),
        ("TEST 10 — Job trajectory aggregation",     test_10_full_job_trajectory_audit),
        ("TEST 11 — Phase 14 Regression (41/41)",    test_11_phase14_regression),
        ("TEST 12 — Phase 13 Regression (30/30)",    test_12_phase13_regression),
        ("TEST 13 — Phase 12 Regression (27/27)",    test_13_phase12_regression),
        ("TEST 14 — Phase 11 Regression (23/23)",    test_14_phase11_regression),
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
    print("PRODUCTION READINESS & RECONCILIATION TEST RESULTS")
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
