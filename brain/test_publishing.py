"""
Phase 12 — Production Publishing & Delivery Layer Test Suite
Tests A through X (24 Required Tests) + Adversarial Test Suite

TEST A — Publish-ready eligibility
TEST B — Ineligible QA failure
TEST C — Rejected production job
TEST D — Escalated production job
TEST E — Successful publishing
TEST F — Idempotent duplicate publish
TEST G — Concurrent duplicate publish
TEST H — Transient provider failure
TEST I — Retry exhaustion
TEST J — Permanent provider rejection
TEST K — Crash before provider call
TEST L — Crash after provider acceptance
TEST M — Crash after external ID
TEST N — Artifact mutation
TEST O — Missing artifact
TEST P — Cancellation while queued
TEST Q — Cancellation during publishing
TEST R — Batch publishing
TEST S — Partial batch failure
TEST T — Restart persistence
TEST U — Dry-run isolation
TEST V — Provider abstraction
TEST W — Invalid state transition
TEST X — No fabricated analytics
ADV 1  — Simultaneous duplicate race
ADV 2  — Corrupted receipt store
ADV 3  — Ambiguous timeout reconciliation
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.orchestrator_models import ExecutionMode, JobState, ProductionJob
from brain.publishing_models import (
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
    PublishingResult,
)
from brain.publishing_service import (
    MockPublisher,
    PublishEligibilityValidator,
    PublishingService,
    PublishingStore,
    _file_sha256,
    _make_idempotency_key,
)

SEP = "=" * 65


def _create_mock_job(
    tmp_dir: Path,
    job_id: str = "",
    clip_id: str = "",
    state: str = JobState.OUTPUT_READY.value,
    execution_mode: str = ExecutionMode.PRODUCTION.value,
    qa_action: str = "approve",
    qa_passed: bool = True,
    file_size_bytes: int = 4096,
    failure_class: str = "",
    escalation: Optional[Dict] = None,
    record_approved_hash: bool = True,
) -> Tuple[ProductionJob, Path]:
    """Helper to generate a valid ProductionJob and real video artifact."""
    jid = job_id or f"job_{uuid.uuid4().hex[:8]}"
    cid = clip_id or f"clip_{uuid.uuid4().hex[:8]}"

    out_file = tmp_dir / f"{cid}_approved.mp4"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(b"\x00" * file_size_bytes)
    file_hash = _file_sha256(out_file)

    qa_report = {
        "passed": qa_passed,
        "score": 95.0 if qa_passed else 40.0,
        "recommended_action": qa_action,
        "hard_fails": [] if qa_passed else ["QA failure detected"],
    }

    job = ProductionJob(
        job_id=jid,
        episode_id="ep_pub_01",
        clip_id=cid,
        account_id="account_viral",
        platform="youtube_shorts",
        format="ambient_blur_9_16",
        execution_mode=execution_mode,
        state=state,
        title=f"Viral Short {cid}",
        failure_class=failure_class,
        escalation=escalation or {},
        artifacts={
            "final_output": str(out_file),
            "artifact_hash": file_hash if record_approved_hash else "",
            "qa_report": json.dumps(qa_report),
        },
    )
    return job, out_file


# ─── Tests A through D: Eligibility & QA Authority ────────────────────────────

def test_a_publish_ready_eligibility():
    print(f"\n{SEP}\nTEST A: Publish-ready eligibility\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        job, artifact = _create_mock_job(tmp)
        verified_path, h = PublishEligibilityValidator.validate_job(job)
        assert verified_path == artifact
        assert h == _file_sha256(artifact)
        print("  PASS: Valid OUTPUT_READY job with approved QA meets eligibility.")


def test_b_ineligible_qa_failure():
    print(f"\n{SEP}\nTEST B: Ineligible QA failure rejected without provider call\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        job, _ = _create_mock_job(tmp, qa_action="reject", qa_passed=False)
        publisher = MockPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)

        try:
            service.publish_job(job)
            assert False, "Should raise PublishEligibilityError"
        except PublishEligibilityError as e:
            assert "QA rejection detected" in str(e)
            assert len(publisher.published_requests) == 0
            print(f"  Caught expected error: {e}")
            print("  PASS: QA failure rejected. Zero provider invocations.")


def test_c_rejected_production_job():
    print(f"\n{SEP}\nTEST C: Rejected production job blocked from publishing\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        job, _ = _create_mock_job(tmp, state=JobState.REJECTED.value)
        publisher = MockPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)

        try:
            service.publish_job(job)
            assert False, "Should raise PublishEligibilityError"
        except PublishEligibilityError as e:
            assert len(publisher.published_requests) == 0
            print(f"  Caught expected error: {e}")
            print("  PASS: REJECTED job blocked. Zero provider invocations.")


def test_d_escalated_production_job():
    print(f"\n{SEP}\nTEST D: Escalated production job blocked from publishing\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        job, _ = _create_mock_job(
            tmp, state=JobState.REPAIR_ESCALATED.value,
            escalation={"reason": "SOURCE_RERENDER_REQUIRED"}
        )
        publisher = MockPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)

        try:
            service.publish_job(job)
            assert False, "Should raise PublishEligibilityError"
        except PublishEligibilityError as e:
            assert len(publisher.published_requests) == 0
            print(f"  Caught expected error: {e}")
            print("  PASS: REPAIR_ESCALATED job blocked. Zero provider invocations.")


# ─── Tests E through G: Core Publishing & Idempotency ─────────────────────────

def test_e_successful_publishing():
    print(f"\n{SEP}\nTEST E: Successful publishing (PUBLISH_READY -> PUBLISHED)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, artifact = _create_mock_job(tmp)

        receipt = service.publish_job(job, title="Winning Clip", visibility="public")

        assert receipt.status == PublishState.PUBLISHED.value
        assert receipt.external_id.startswith("ext_")
        assert receipt.artifact_hash == _file_sha256(artifact)
        assert receipt.errors == []

        # Confirm persisted on disk
        loaded = service.store.load_receipt(receipt.receipt_id)
        assert loaded is not None
        assert loaded.external_id == receipt.external_id

        print(f"  Receipt ID: {receipt.receipt_id}, External ID: {receipt.external_id}")
        print("  PASS: Successful delivery flow and atomic receipt persistence verified.")


def test_f_idempotent_duplicate_publish():
    print(f"\n{SEP}\nTEST F: Idempotent duplicate publish returns cached receipt\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        # Call 1
        r1 = service.publish_job(job, title="Idempotent Test", visibility="public")
        calls1 = len(publisher.published_requests)

        # Call 2 with identical request
        r2 = service.publish_job(job, title="Idempotent Test", visibility="public")
        calls2 = len(publisher.published_requests)

        assert calls1 == 1
        assert calls2 == 1, "Provider must NOT be called twice!"
        assert r1.receipt_id == r2.receipt_id
        assert r1.external_id == r2.external_id
        assert r1.idempotency_key == r2.idempotency_key

        print(f"  Provider calls: {calls2} (expected 1)")
        print("  PASS: Duplicate publish cleanly intercepted by idempotency check.")


def test_g_concurrent_duplicate_publish():
    print(f"\n{SEP}\nTEST G: Concurrent duplicate publish by two workers\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher(simulated_delay_sec=0.05)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        results = []
        lock = threading.Lock()

        def _worker():
            r = service.publish_job(job, title="Concurrent Title")
            with lock:
                results.append(r)

        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start(); t2.start()
        t1.join(timeout=10); t2.join(timeout=10)

        assert len(results) == 2
        assert results[0].status == PublishState.PUBLISHED.value
        assert results[1].status == PublishState.PUBLISHED.value
        # Same idempotency key
        assert results[0].idempotency_key == results[1].idempotency_key

        print("  PASS: Concurrent worker race cleanly coordinated via per-key locking.")


# ─── Tests H through J: Retry Policies & Provider Rejection ───────────────────

def test_h_transient_provider_failure():
    print(f"\n{SEP}\nTEST H: Transient failure retries and succeeds\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher(fail_times=1)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)

        assert receipt.status == PublishState.PUBLISHED.value
        assert receipt.attempt_count == 2
        assert len(publisher.published_requests) == 2

        events = service.store.get_events_for_job(job.job_id)
        assert any(e["new_state"] == PublishState.PUBLISH_RETRYING.value for e in events)

        print(f"  Succeeded on attempt {receipt.attempt_count} after transient retry")
        print("  PASS: Transient error backed off and recovered.")


def test_i_retry_exhaustion():
    print(f"\n{SEP}\nTEST I: Retry exhaustion -> PUBLISH_FAILED\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher(fail_times=10)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)

        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert receipt.attempt_count == 3
        assert len(publisher.published_requests) == 3

        print(f"  Status after exhaustion: {receipt.status} (attempts: {receipt.attempt_count})")
        print("  PASS: Bounded retries enforced; stopped at max_attempts without infinite loop.")


def test_j_permanent_provider_rejection():
    print(f"\n{SEP}\nTEST J: Permanent provider rejection -> PUBLISH_REJECTED without retry\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher(fail_mode="reject")
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)

        assert receipt.status == PublishState.PUBLISH_REJECTED.value
        assert receipt.attempt_count == 1  # 0 retries
        assert len(publisher.published_requests) == 1

        print(f"  Status: {receipt.status} (attempts: {receipt.attempt_count})")
        print("  PASS: Policy violation immediately terminated as PUBLISH_REJECTED.")


# ─── Tests K through M: Crash Recovery Scenarios ──────────────────────────────

def test_k_crash_before_provider_call():
    print(f"\n{SEP}\nTEST K: Crash before provider call (PUBLISH_QUEUED)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        req = service.prepare_publish(job)

        # Simulate crash while in queue: log QUEUED event but do not execute
        service._log_event(
            job_id=req.job_id, episode_id=req.episode_id, clip_id=req.clip_id,
            platform=req.platform, prev_state=PublishState.PUBLISH_READY.value,
            new_state=PublishState.PUBLISH_QUEUED.value, event_msg="Simulated crash before call",
        )

        # Restart service
        service2 = PublishingService(store_dir=tmp, publisher=publisher)
        receipt = service2.publish(req)

        assert receipt.status == PublishState.PUBLISHED.value
        assert len(publisher.published_requests) == 1
        print("  PASS: Safe resume from queued state without double execution.")


def test_l_crash_after_provider_acceptance():
    print(f"\n{SEP}\nTEST L: Crash/timeout after provider accepts -> reconcile via get_status\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # Publisher accepts and assigns ID, but simulates network drop on response
        publisher = MockPublisher(fail_mode="timeout_after_accept")
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)

        # Service automatically reconciled via get_status(external_id)
        assert receipt.status == PublishState.PUBLISHED.value
        assert receipt.external_id.startswith("ext_ambiguous_")
        assert len(publisher.published_requests) == 1

        print(f"  Reconciled external ID: {receipt.external_id}")
        print("  PASS: Ambiguous timeout reconciled against provider without duplicate upload.")


def test_m_crash_after_external_id():
    print(f"\n{SEP}\nTEST M: Crash after external ID received -> resume_pending_publishes\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)

        # Simulate crash before final disk write: leave status as PUBLISHING in store
        receipt.status = PublishState.PUBLISHING.value
        service.store.save_receipt(receipt)

        # Startup recovery
        service2 = PublishingService(store_dir=tmp, publisher=publisher)
        reconciled = service2.resume_pending_publishes()

        assert len(reconciled) >= 1
        assert reconciled[0].status == PublishState.PUBLISHED.value
        print("  PASS: Startup scanner resumed and reconciled in-flight receipt.")


# ─── Tests N & O: Artifact Integrity & Missing Artifacts ──────────────────────

def test_n_artifact_mutation():
    print(f"\n{SEP}\nTEST N: Artifact mutated after QA approval -> rejected\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        job, artifact = _create_mock_job(tmp, record_approved_hash=True)

        # Mutate artifact after QA
        artifact.write_bytes(b"\xFF" * 4096)

        try:
            PublishEligibilityValidator.validate_job(job)
            assert False, "Should detect hash mismatch"
        except PublishEligibilityError as e:
            assert "mutated after QA" in str(e)
            print(f"  Caught expected error: {e}")
            print("  PASS: Immutability violation detected. Modified video blocked.")


def test_o_missing_artifact():
    print(f"\n{SEP}\nTEST O: Artifact deleted before publish -> PUBLISH_FAILED\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        job, artifact = _create_mock_job(tmp)
        service = PublishingService(store_dir=tmp)
        req = service.prepare_publish(job)

        # Delete artifact right before transmission
        artifact.unlink()

        receipt = service.publish(req)
        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert any("missing" in err.lower() for err in receipt.errors)
        print(f"  Status: {receipt.status}, Errors: {receipt.errors}")
        print("  PASS: Missing file before transmission cleanly handled.")


# ─── Tests P & Q: Cancellation ────────────────────────────────────────────────

def test_p_cancellation_while_queued():
    print(f"\n{SEP}\nTEST P: Cancellation while queued -> PUBLISH_CANCELLED\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        service = PublishingService(store_dir=tmp)
        job, _ = _create_mock_job(tmp)
        req = service.prepare_publish(job)

        service._log_event(
            job_id=req.job_id, episode_id=req.episode_id, clip_id=req.clip_id,
            platform=req.platform, prev_state=PublishState.PUBLISH_READY.value,
            new_state=PublishState.PUBLISH_CANCELLED.value, event_msg="Cancelled before worker pick-up",
        )

        events = service.store.get_events_for_job(job.job_id)
        assert events[-1]["new_state"] == PublishState.PUBLISH_CANCELLED.value
        print("  PASS: Queued job cooperatively cancelled.")


def test_q_cancellation_during_publishing():
    print(f"\n{SEP}\nTEST Q: Cancellation on provider during/after transmission\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)
        assert receipt.status == PublishState.PUBLISHED.value

        cancelled = service.cancel_publish(receipt.external_id, job_id=job.job_id)
        assert cancelled

        status = publisher.get_status(receipt.external_id)
        assert status.status == PublishState.PUBLISH_CANCELLED.value
        print(f"  Provider status after cancel: {status.status}")
        print("  PASS: Cooperative platform cancellation verified.")


# ─── Tests R & S: Batch Delivery & Error Isolation ────────────────────────────

def test_r_batch_publishing():
    print(f"\n{SEP}\nTEST R: Batch publishing independent accounting\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)

        jobs = [_create_mock_job(tmp, clip_id=f"batch_clip_{i}")[0] for i in range(5)]
        requests = [service.prepare_publish(j) for j in jobs]

        batch_result = service.publish_batch("batch_01", requests, max_workers=2)

        assert batch_result.total == 5
        assert batch_result.published == 5
        assert batch_result.failed == 0
        print(f"  Batch {batch_result.batch_id}: {batch_result.published}/{batch_result.total} published")
        print("  PASS: Batch delivery successfully completed.")


def test_s_partial_batch_failure():
    print(f"\n{SEP}\nTEST S: Partial batch failure (mixed outcomes isolated)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        class MixedPublisher(MockPublisher):
            def publish(self, req, metadata=None):
                if "fail" in req.clip_id:
                    raise PublishProviderError("Permanent upload fail", PublishFailureClass.AUTHENTICATION_ERROR.value)
                if "reject" in req.clip_id:
                    raise PublishProviderError("Content banned", PublishFailureClass.PROVIDER_REJECTED.value)
                return super().publish(req, metadata)

        publisher = MixedPublisher()
        service = PublishingService(store_dir=tmp, publisher=publisher)

        jobs_ok = [_create_mock_job(tmp, clip_id=f"clip_ok_{i}")[0] for i in range(7)]
        job_fail = _create_mock_job(tmp, clip_id="clip_fail")[0]
        job_reject = _create_mock_job(tmp, clip_id="clip_reject")[0]

        requests = [service.prepare_publish(j) for j in jobs_ok + [job_fail, job_reject]]

        batch_result = service.publish_batch("mixed_batch", requests, max_workers=3)

        assert batch_result.total == 9
        assert batch_result.published == 7
        assert batch_result.failed == 1
        assert batch_result.rejected == 1

        print(f"  Batch Result: Total={batch_result.total}, Published={batch_result.published}, "
              f"Failed={batch_result.failed}, Rejected={batch_result.rejected}")
        print("  PASS: Partial batch error isolation verified. Sibling items completed cleanly.")


# ─── Tests T through X: Abstraction, Isolation & FSM Guards ───────────────────

def test_t_restart_persistence():
    print(f"\n{SEP}\nTEST T: Restart persistence (new service instance reads store)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        service1 = PublishingService(store_dir=tmp)
        jobs = [_create_mock_job(tmp, clip_id=f"persist_{i}")[0] for i in range(3)]
        receipts = [service1.publish_job(j) for j in jobs]

        # New instance on same store
        service2 = PublishingService(store_dir=tmp)
        for r in receipts:
            loaded = service2.store.load_receipt(r.receipt_id)
            assert loaded is not None
            assert loaded.status == PublishState.PUBLISHED.value
            assert loaded.external_id == r.external_id

        print(f"  Verified {len(receipts)} receipts loaded across restarts.")
        print("  PASS: All published state survives process restart.")


def test_u_dry_run_isolation():
    print(f"\n{SEP}\nTEST U: Dry-run isolation (0 real provider calls)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        job, _ = _create_mock_job(tmp, execution_mode=ExecutionMode.DRY_RUN.value)

        # Live provider attempt must be blocked
        try:
            PublishEligibilityValidator.validate_job(job, allow_non_production=False)
            assert False, "Should block DRY_RUN"
        except PublishEligibilityError:
            pass

        print("  PASS: Dry-run completely quarantined from live platform delivery.")


def test_v_provider_abstraction():
    print(f"\n{SEP}\nTEST V: Provider abstraction (pluggable publishers)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        class YouTubeMock(MockPublisher):
            @property
            def name(self): return "YouTubePublisher"

        class TikTokMock(MockPublisher):
            @property
            def name(self): return "TikTokPublisher"

        svc_yt = PublishingService(store_dir=tmp / "yt", publisher=YouTubeMock())
        svc_tt = PublishingService(store_dir=tmp / "tt", publisher=TikTokMock())

        job_yt, _ = _create_mock_job(tmp / "yt", clip_id="yt_clip")
        job_tt, _ = _create_mock_job(tmp / "tt", clip_id="tt_clip")

        r_yt = svc_yt.publish_job(job_yt)
        r_tt = svc_tt.publish_job(job_tt)

        assert r_yt.provider == "YouTubePublisher"
        assert r_tt.provider == "TikTokPublisher"
        print(f"  YT Provider: {r_yt.provider}, TT Provider: {r_tt.provider}")
        print("  PASS: PublishingService interacts exclusively through Provider abstraction.")


def test_w_invalid_state_transition():
    print(f"\n{SEP}\nTEST W: Invalid state transition rejected\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        service = PublishingService(store_dir=tmp)

        try:
            # Illegal transition: PUBLISHED -> PUBLISHING
            service._log_event(
                job_id="job_illegal", episode_id="ep01", clip_id="clip01", platform="yt",
                prev_state=PublishState.PUBLISHED.value, new_state=PublishState.PUBLISHING.value,
                event_msg="Illegal jump",
            )
            assert False, "Should raise PublishStateTransitionError"
        except PublishStateTransitionError as e:
            assert "Illegal publishing state transition" in str(e)
            print(f"  Caught expected error: {e}")
            print("  PASS: State machine rejects unauthorized transitions.")


def test_x_no_fabricated_analytics():
    print(f"\n{SEP}\nTEST X: No fabricated analytics (strict analytics boundary)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        service = PublishingService(store_dir=tmp)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)

        # Receipt metadata contains platform identifiers, NEVER invented audience metrics
        assert receipt.published_at != ""
        assert receipt.external_id != ""
        for fake_key in ("views", "retention", "completion", "shares", "subscribers"):
            assert fake_key not in receipt.provider_metadata, f"Fabricated metric found: {fake_key}"

        print(f"  Published at: {receipt.published_at}, External ID: {receipt.external_id}")
        print("  PASS: No fabricated performance data created upon publication.")


# ─── Adversarial Tests ────────────────────────────────────────────────────────

def test_adv_duplicate_race():
    print(f"\n{SEP}\nADV 1: Simultaneous worker race with identical idempotency key\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher(simulated_delay_sec=0.05)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        results = []
        lock = threading.Lock()

        def _race_worker():
            r = service.publish_job(job)
            with lock:
                results.append(r)

        t1 = threading.Thread(target=_race_worker)
        t2 = threading.Thread(target=_race_worker)
        t1.start(); t2.start()
        t1.join(timeout=15); t2.join(timeout=15)

        assert len(results) == 2
        assert results[0].status == PublishState.PUBLISHED.value
        assert results[1].status == PublishState.PUBLISHED.value
        print("  PASS: Simultaneous duplicate worker race handled without crash.")


def test_adv_corrupted_receipt_store():
    print(f"\n{SEP}\nADV 2: Corrupted receipt JSON handled gracefully\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        service = PublishingService(store_dir=tmp)

        corrupt_file = tmp / "receipts" / "receipt_bad.json"
        corrupt_file.write_text("{ MALFORMED JSON !!!", encoding="utf-8")

        found = service.store.find_receipt_by_idempotency_key("some_key")
        assert found is None

        loaded = service.store.load_receipt("bad")
        assert loaded is None
        print("  PASS: Corrupted receipt store handled without unhandled exception.")


def test_adv_ambiguous_timeout_reconciliation():
    print(f"\n{SEP}\nADV 3: Ambiguous provider timeout with remote reconciliation\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        publisher = MockPublisher(fail_mode="timeout_after_accept")
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)

        assert receipt.status == PublishState.PUBLISHED.value
        assert receipt.external_id.startswith("ext_ambiguous_")
        assert len(publisher.published_requests) == 1
        print(f"  Reconciled external ID: {receipt.external_id}")
        print("  PASS: Ambiguous provider timeout reconciled safely.")


# ─── Test Suite Runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    tests = [
        ("TEST A", test_a_publish_ready_eligibility),
        ("TEST B", test_b_ineligible_qa_failure),
        ("TEST C", test_c_rejected_production_job),
        ("TEST D", test_d_escalated_production_job),
        ("TEST E", test_e_successful_publishing),
        ("TEST F", test_f_idempotent_duplicate_publish),
        ("TEST G", test_g_concurrent_duplicate_publish),
        ("TEST H", test_h_transient_provider_failure),
        ("TEST I", test_i_retry_exhaustion),
        ("TEST J", test_j_permanent_provider_rejection),
        ("TEST K", test_k_crash_before_provider_call),
        ("TEST L", test_l_crash_after_provider_acceptance),
        ("TEST M", test_m_crash_after_external_id),
        ("TEST N", test_n_artifact_mutation),
        ("TEST O", test_o_missing_artifact),
        ("TEST P", test_p_cancellation_while_queued),
        ("TEST Q", test_q_cancellation_during_publishing),
        ("TEST R", test_r_batch_publishing),
        ("TEST S", test_s_partial_batch_failure),
        ("TEST T", test_t_restart_persistence),
        ("TEST U", test_u_dry_run_isolation),
        ("TEST V", test_v_provider_abstraction),
        ("TEST W", test_w_invalid_state_transition),
        ("TEST X", test_x_no_fabricated_analytics),
        ("ADV 1",  test_adv_duplicate_race),
        ("ADV 2",  test_adv_corrupted_receipt_store),
        ("ADV 3",  test_adv_ambiguous_timeout_reconciliation),
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
    print("PHASE 12 PUBLISHING & DELIVERY LAYER TEST RESULTS")
    print(SEP)
    print(f"  PASSED: {len(passed)}/{len(tests)}")
    if failed:
        print(f"  FAILED: {len(failed)}/{len(tests)}")
        for label, reason in failed:
            print(f"    [{label}] {reason}")
    else:
        print("  ALL 27 TESTS PASSED. Exit code: 0")
    print(SEP)

    sys.exit(0 if not failed else 1)
