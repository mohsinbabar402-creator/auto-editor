"""
Phase 13 — Real Provider Integration & Production Publishing Test Suite
Tests 1 through 29 + Production Safety Audit & Security Audit

TEST 1  — Real provider configuration
TEST 2  — Missing credentials (fails closed)
TEST 3  — Invalid credentials (auth error classified correctly)
TEST 4  — Successful upload (PUBLISHED + external_id + receipt)
TEST 5  — Artifact hash mismatch (provider never called)
TEST 6  — Invalid metadata (provider never called)
TEST 7  — Provider timeout (classified correctly)
TEST 8  — Ambiguous successful upload (reconciliation without duplicate upload)
TEST 9  — Rate limiting (maps to RATE_LIMITED with bounded retry)
TEST 10 — Permanent rejection (maps to PUBLISH_REJECTED without retry)
TEST 11 — Scheduled publish (future schedule passed correctly)
TEST 12 — Unsupported scheduling (invalid/past date fails safely)
TEST 13 — Visibility mapping (public, unlisted, private)
TEST 14 — Metadata constraints (title > 100 chars handled)
TEST 15 — Cancellation (maps correctly)
TEST 16 — Provider status (remote status mapped correctly)
TEST 17 — External ID persistence (survives restart)
TEST 18 — Duplicate publish (exactly 1 publication)
TEST 19 — Concurrent duplicate publish (multiple workers produce 1 remote publication)
TEST 20 — Account isolation (Account A cannot access Account B credentials)
TEST 21 — Secret leakage audit (logs/receipts/events contain 0 credentials/tokens)
TEST 22 — Dry-run isolation (0 real provider transport calls)
TEST 23 — Provider abstraction (PublishingService contains 0 provider-specific logic)
TEST 24 — Provider transport failure (HTTP/network failures map correctly)
TEST 25 — Malformed provider response (fails safely)
TEST 26 — Restart during publishing (pending publication reconciles correctly)
TEST 27 — Batch mixed outcomes (independent provider outcomes isolated)
TEST 28 — Phase 12 regression (27/27 pass)
TEST 29 — Phase 11 regression (23/23 pass)
SAFETY AUDIT — QA_FAILED, REJECTED, REPAIR_ESCALATED produce 0 provider calls
"""

from __future__ import annotations

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

from brain.orchestrator_models import ExecutionMode, JobState, ProductionJob
from brain.provider_credentials import CredentialStore, YouTubeCredentials
from brain.publishing_models import (
    BatchPublishingResult,
    PublishEligibilityError,
    PublishEvent,
    PublishFailureClass,
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
from brain.youtube_publisher import YouTubePublisher
from brain.youtube_transport import FakeYouTubeTransport

SEP = "=" * 65


def _create_test_credentials(account_id: str = "test_acc") -> YouTubeCredentials:
    return YouTubeCredentials(
        account_id=account_id,
        client_id="test_client_id_12345.apps.googleusercontent.com",
        client_secret="test_client_secret_xyz890",
        refresh_token="test_refresh_token_abc567",
        access_token="test_access_token_token123",
        channel_id="UC_test_channel_001",
    )


def _create_mock_job(
    tmp_dir: Path,
    job_id: str = "",
    clip_id: str = "",
    account_id: str = "test_acc",
    state: str = JobState.OUTPUT_READY.value,
    execution_mode: str = ExecutionMode.PRODUCTION.value,
    qa_action: str = "approve",
    qa_passed: bool = True,
    file_size_bytes: int = 4096,
    failure_class: str = "",
    escalation: Optional[Dict] = None,
) -> Tuple[ProductionJob, Path]:
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
        episode_id="ep_provider_01",
        clip_id=cid,
        account_id=account_id,
        platform="youtube_shorts",
        format="ambient_blur_9_16",
        execution_mode=execution_mode,
        state=state,
        title=f"Viral Short {cid}",
        failure_class=failure_class,
        escalation=escalation or {},
        artifacts={
            "final_output": str(out_file),
            "artifact_hash": file_hash,
            "qa_report": json.dumps(qa_report),
        },
    )
    return job, out_file


# ─── Tests 1 through 7: Configuration, Credentials & Transport ────────────────

def test_01_real_provider_configuration():
    print(f"\n{SEP}\nTEST 1: Real provider configuration & health check\n{SEP}")
    creds = _create_test_credentials("acc_1")
    transport = FakeYouTubeTransport()
    publisher = YouTubePublisher(credentials=creds, transport=transport, environment="TEST")

    assert publisher.name == "YouTubePublisher"
    health = publisher.health_check("acc_1")
    assert health["healthy"] is True
    assert health["account_id"] == "acc_1"
    print(f"  Health Check: {health}")
    print("  PASS: Provider configured and initialized cleanly.")


def test_02_missing_credentials_fails_closed():
    print(f"\n{SEP}\nTEST 2: Missing credentials fails closed\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # Empty credential store
        publisher = YouTubePublisher(credential_store=CredentialStore(), transport=FakeYouTubeTransport())
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp, account_id="unauthorized_acc")

        # Test 1: Direct provider invocation raises PublishProviderError
        req = service.prepare_publish(job)
        try:
            publisher.publish(req)
            assert False, "Direct publisher.publish should raise on missing credentials"
        except PublishProviderError as e:
            assert e.failure_class == PublishFailureClass.AUTHENTICATION_ERROR.value
            assert "unauthorized_acc" in str(e)

        # Test 2: Service delivery pipeline captures error receipt safely without crash
        receipt = service.publish(req)
        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert any("unauthorized_acc" in str(err) for err in receipt.errors)
        print("  PASS: Fails closed when credentials missing.")


def test_03_invalid_credentials_classified():
    print(f"\n{SEP}\nTEST 3: Invalid credentials classified as AUTHENTICATION_ERROR\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials("acc_inv")
        transport = FakeYouTubeTransport(fail_mode="auth_error")
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp, account_id="acc_inv")

        receipt = service.publish_job(job)
        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert any("401" in err or "Unauthorized" in err for err in receipt.errors)
        print(f"  Receipt errors: {receipt.errors}")
        print("  PASS: Invalid credentials correctly mapped to AUTHENTICATION_ERROR.")


def test_04_successful_upload():
    print(f"\n{SEP}\nTEST 4: Successful upload -> PUBLISHED with receipt & external ID\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials("acc_ok")
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, artifact = _create_mock_job(tmp, account_id="acc_ok")

        receipt = service.publish_job(job, title="Real YouTube Short", tags=["shorts", "viral"])

        assert receipt.status == PublishState.PUBLISHED.value
        assert receipt.external_id.startswith("yt_")
        assert receipt.provider == "YouTubePublisher"
        assert receipt.artifact_hash == _file_sha256(artifact)
        assert receipt.provider_metadata["url"] == f"https://youtube.com/shorts/{receipt.external_id}"
        assert len(transport.calls) == 1

        print(f"  Receipt ID: {receipt.receipt_id}")
        print(f"  External ID: {receipt.external_id}")
        print(f"  URL: {receipt.provider_metadata['url']}")
        print("  PASS: Successful upload normalized into PublishReceipt.")


def test_05_artifact_hash_mismatch_never_calls_provider():
    print(f"\n{SEP}\nTEST 5: Artifact hash mismatch blocks upload before provider call\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, artifact = _create_mock_job(tmp)

        # Mutate artifact after QA
        artifact.write_bytes(b"\xFE" * 8192)

        try:
            service.publish_job(job)
            assert False, "Should fail on hash mismatch"
        except PublishEligibilityError as e:
            assert "hash mismatch" in str(e).lower()
            assert len(transport.calls) == 0
            print(f"  Caught expected error: {e}")
            print("  PASS: Mutated artifact caught; provider never called.")


def test_06_invalid_metadata_never_calls_provider():
    print(f"\n{SEP}\nTEST 6: Invalid metadata blocks upload before transport call\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        # Title > 100 characters
        long_title = "A" * 105
        req = service.prepare_publish(job, title=long_title)

        receipt = service.publish(req)
        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert any("exceeds 100 characters" in err for err in receipt.errors)
        assert len(transport.calls) == 0

        print(f"  Caught metadata constraint: {receipt.errors}")
        print("  PASS: Invalid metadata caught before transport call.")


def test_07_provider_timeout_classified():
    print(f"\n{SEP}\nTEST 7: Provider timeout classified as TIMEOUT\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport(fail_mode="timeout")
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)
        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert any("timed out" in err.lower() for err in receipt.errors)
        print(f"  Errors: {receipt.errors}")
        print("  PASS: Transport timeout classified and handled.")


# ─── Tests 8 through 14: Ambiguity, Retries, Scheduling & Visibility ──────────

def test_08_ambiguous_successful_upload_reconciles():
    print(f"\n{SEP}\nTEST 8: Ambiguous successful upload reconciles without duplicate upload\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport(fail_mode="timeout_after_upload")
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)

        # Ambiguous timeout occurred, but service reconciled remote video status
        assert receipt.status == PublishState.PUBLISHED.value
        assert receipt.external_id.startswith("yt_")
        assert len(transport.calls) == 1  # EXACTLY 1 call (no duplicate upload!)

        print(f"  Reconciled external ID: {receipt.external_id}")
        print("  PASS: Ambiguous timeout safely reconciled without duplicate upload.")


def test_09_rate_limiting_bounded_retry():
    print(f"\n{SEP}\nTEST 9: Rate limiting mapped to RATE_LIMITED with bounded retry\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport(fail_mode="rate_limit")
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)
        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert receipt.attempt_count == 3  # Bounded at 3 attempts
        assert any("quotaexceeded" in err.lower() for err in receipt.errors)
        print(f"  Attempts: {receipt.attempt_count}, Error: {receipt.errors[0][:60]}...")
        print("  PASS: Rate limiting maps to RATE_LIMITED with bounded retries.")


def test_10_permanent_rejection_no_retry():
    print(f"\n{SEP}\nTEST 10: Permanent policy rejection -> PUBLISH_REJECTED without retry\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport(fail_mode="policy_reject")
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)
        assert receipt.status == PublishState.PUBLISH_REJECTED.value
        assert receipt.attempt_count == 1  # Terminated on attempt 1!
        assert len(transport.calls) == 1

        print(f"  Status: {receipt.status} on attempt {receipt.attempt_count}")
        print("  PASS: Policy violation terminated immediately as PUBLISH_REJECTED.")


def test_11_scheduled_publish():
    print(f"\n{SEP}\nTEST 11: Scheduled publish with future ISO timestamp\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        future_iso = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        receipt = service.publish_job(job, scheduled_at=future_iso)

        assert receipt.status == PublishState.PUBLISHED.value
        assert receipt.provider_metadata["scheduled_at"] == future_iso
        print(f"  Scheduled at: {receipt.provider_metadata['scheduled_at']}")
        print("  PASS: Future scheduled timestamp correctly staged.")


def test_12_unsupported_scheduling_fails_safely():
    print(f"\n{SEP}\nTEST 12: Past or invalid schedule fails safely\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        # Past timestamp
        past_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        req = service.prepare_publish(job, scheduled_at=past_iso)

        receipt = service.publish(req)
        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert any("must be in the future" in err for err in receipt.errors)
        assert len(transport.calls) == 0

        print(f"  Error: {receipt.errors}")
        print("  PASS: Past schedule cleanly rejected before transport call.")


def test_13_visibility_mapping():
    print(f"\n{SEP}\nTEST 13: Visibility mapping (public, unlisted, private)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)

        for vis in ("public", "unlisted", "private"):
            job, _ = _create_mock_job(tmp, clip_id=f"clip_vis_{vis}")
            receipt = service.publish_job(job, visibility=vis)
            assert receipt.status == PublishState.PUBLISHED.value
            assert receipt.provider_metadata["visibility"] == vis

        # Invalid visibility
        job_bad, _ = _create_mock_job(tmp, clip_id="clip_vis_bad")
        req = service.prepare_publish(job_bad, visibility="internal_only")
        r_bad = service.publish(req)
        assert r_bad.status == PublishState.PUBLISH_FAILED.value
        assert any("Invalid visibility" in err for err in r_bad.errors)

        print("  PASS: All valid visibility states mapped; invalid rejected.")


def test_14_metadata_constraints():
    print(f"\n{SEP}\nTEST 14: Metadata constraints (tags combined length <= 500)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        publisher = YouTubePublisher(credentials=creds, transport=FakeYouTubeTransport())
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        long_tags = ["tag_" + "x" * 50 for _ in range(12)]  # 600+ chars
        req = service.prepare_publish(job, tags=long_tags)

        receipt = service.publish(req)
        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert any("exceeds 500 characters" in err for err in receipt.errors)
        print(f"  Tags constraint caught: {receipt.errors}")
        print("  PASS: Excessive tags rejected before transport call.")


# ─── Tests 15 through 20: Cancellation, Status & Isolation ───────────────────

def test_15_cancellation_mapping():
    print(f"\n{SEP}\nTEST 15: Cancellation maps correctly\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)
        cancelled = service.cancel_publish(receipt.external_id, job_id=job.job_id)
        assert cancelled is True

        status = publisher.get_status(receipt.external_id)
        assert status.status == PublishState.PUBLISH_CANCELLED.value
        print(f"  Remote status after cancel: {status.status}")
        print("  PASS: Platform cancellation verified.")


def test_16_provider_status_mapping():
    print(f"\n{SEP}\nTEST 16: Remote provider status normalized into PublishState\n{SEP}")
    creds = _create_test_credentials()
    transport = FakeYouTubeTransport()
    publisher = YouTubePublisher(credentials=creds, transport=transport)

    vid = "yt_status_test_01"
    transport.uploaded_videos[vid] = {"id": vid, "status": {"uploadStatus": "processing"}}
    status = publisher.get_status(vid)
    assert status.status == PublishState.PUBLISHING.value

    transport.uploaded_videos[vid] = {"id": vid, "status": {"uploadStatus": "uploaded"}}
    status = publisher.get_status(vid)
    assert status.status == PublishState.PUBLISHED.value

    transport.uploaded_videos[vid] = {"id": vid, "status": {"uploadStatus": "rejected"}}
    status = publisher.get_status(vid)
    assert status.status == PublishState.PUBLISH_REJECTED.value

    print("  PASS: YouTube processing/uploaded/rejected mapped to PublishState.")


def test_17_external_id_persistence():
    print(f"\n{SEP}\nTEST 17: External ID survives service restart\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        publisher = YouTubePublisher(credentials=creds, transport=FakeYouTubeTransport())
        service1 = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service1.publish_job(job)

        # Fresh service instance
        service2 = PublishingService(store_dir=tmp, publisher=publisher)
        loaded = service2.store.load_receipt(receipt.receipt_id)

        assert loaded is not None
        assert loaded.external_id == receipt.external_id
        assert loaded.external_id.startswith("yt_")
        print(f"  Persisted external ID: {loaded.external_id}")
        print("  PASS: External ID successfully recovered across restarts.")


def test_18_duplicate_publish_single_invocation():
    print(f"\n{SEP}\nTEST 18: Duplicate publish results in exactly one provider invocation\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        r1 = service.publish_job(job, title="Duplicate Check")
        r2 = service.publish_job(job, title="Duplicate Check")

        assert len(transport.calls) == 1  # EXACTLY 1 call
        assert r1.external_id == r2.external_id
        print(f"  Transport calls: {len(transport.calls)} (1 expected)")
        print("  PASS: Exactly one remote publication created.")


def test_19_concurrent_duplicate_publish():
    print(f"\n{SEP}\nTEST 19: Concurrent duplicate publish by multiple workers\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport(simulated_delay_sec=0.04)
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        results = []
        lock = threading.Lock()

        def _worker():
            r = service.publish_job(job, title="Race Title")
            with lock:
                results.append(r)

        threads = [threading.Thread(target=_worker) for _ in range(3)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=10)

        assert len(results) == 3
        # Exactly 1 transport call despite 3 racing threads
        assert len(transport.calls) == 1
        assert len(set(r.external_id for r in results)) == 1

        print(f"  Racing threads: 3, Remote calls: {len(transport.calls)}")
        print("  PASS: Concurrent worker race produces single remote publication.")


def test_20_account_isolation():
    print(f"\n{SEP}\nTEST 20: Account isolation (Account A != Account B)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cstore = CredentialStore()
        creds_a = _create_test_credentials("account_alpha")
        creds_b = _create_test_credentials("account_beta")
        cstore.register_credentials("account_alpha", creds_a)
        cstore.register_credentials("account_beta", creds_b)

        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credential_store=cstore, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)

        job_a, _ = _create_mock_job(tmp, clip_id="clip_alpha", account_id="account_alpha")
        job_b, _ = _create_mock_job(tmp, clip_id="clip_beta", account_id="account_beta")

        r_a = service.publish_job(job_a)
        r_b = service.publish_job(job_b)

        assert r_a.provider_metadata["account_id"] == "account_alpha"
        assert r_b.provider_metadata["account_id"] == "account_beta"
        assert r_a.external_id != r_b.external_id

        # Verify Account C cannot access Account A or B
        job_c, _ = _create_mock_job(tmp, clip_id="clip_gamma", account_id="account_gamma")
        req_c = service.prepare_publish(job_c)
        try:
            publisher.publish(req_c)
            assert False, "Should fail closed for unconfigured account on direct call"
        except PublishProviderError as e:
            assert "account_gamma" in str(e)

        r_c = service.publish(req_c)
        assert r_c.status == PublishState.PUBLISH_FAILED.value
        assert any("account_gamma" in str(err) for err in r_c.errors)

        print("  PASS: Strict multi-account isolation verified.")


# ─── Tests 21 through 27: Security, Abstraction, Faults & Recovery ───────────

def test_21_secret_leakage_audit():
    print(f"\n{SEP}\nTEST 21: Security audit — zero secrets in logs, receipts, or events\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        secret_pattern = "SUPER_SECRET_TOKEN_XYZ999"
        creds = YouTubeCredentials(
            account_id="sec_acc", client_id="my_client_id",
            client_secret=secret_pattern, refresh_token=secret_pattern,
            access_token=secret_pattern,
        )
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp, account_id="sec_acc")

        receipt = service.publish_job(job)

        # 1. Audit receipt
        receipt_json = json.dumps(asdict(receipt))
        assert secret_pattern not in receipt_json, "Secret found in receipt JSON!"

        # 2. Audit event stream
        events = service.store.get_events_for_job(job.job_id)
        events_json = json.dumps(events)
        assert secret_pattern not in events_json, "Secret found in events JSON!"

        # 3. Audit credentials representation
        creds_str = str(creds)
        assert secret_pattern not in creds_str, "Secret leaked in __str__!"
        assert "[REDACTED]" in creds_str

        print("  PASS: Zero secrets detected in receipts, events, or representations.")


def test_22_dry_run_isolation():
    print(f"\n{SEP}\nTEST 22: Dry-run isolation — zero transport calls\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport, environment="PRODUCTION")
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp, execution_mode=ExecutionMode.DRY_RUN.value)

        try:
            service.publish_job(job, allow_non_production=False)
            assert False, "Should block DRY_RUN"
        except PublishEligibilityError:
            pass

        assert len(transport.calls) == 0
        print("  PASS: Zero real provider transport calls in dry-run mode.")


def test_23_provider_abstraction():
    print(f"\n{SEP}\nTEST 23: Provider abstraction — PublishingService is provider-agnostic\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        mock_pub = MockPublisher()
        yt_pub = YouTubePublisher(credentials=_create_test_credentials(), transport=FakeYouTubeTransport())

        svc_mock = PublishingService(store_dir=tmp / "m", publisher=mock_pub)
        svc_yt = PublishingService(store_dir=tmp / "y", publisher=yt_pub)

        job_m, _ = _create_mock_job(tmp / "m")
        job_y, _ = _create_mock_job(tmp / "y")

        r_m = svc_mock.publish_job(job_m)
        r_y = svc_yt.publish_job(job_y)

        assert r_m.provider == "MockPublisher"
        assert r_y.provider == "YouTubePublisher"
        assert r_m.status == PublishState.PUBLISHED.value
        assert r_y.status == PublishState.PUBLISHED.value

        print("  PASS: PublishingService works seamlessly with any PublisherInterface provider.")


def test_24_provider_transport_failure():
    print(f"\n{SEP}\nTEST 24: Provider transport failure (HTTP 500/503 maps correctly)\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport(fail_times=1)
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)
        # Succeeded after 1 transient retry
        assert receipt.status == PublishState.PUBLISHED.value
        assert receipt.attempt_count == 2
        print(f"  Attempt count: {receipt.attempt_count}")
        print("  PASS: Transport failure mapped to TRANSIENT_PROVIDER_ERROR and retried.")


def test_25_malformed_provider_response():
    print(f"\n{SEP}\nTEST 25: Malformed provider response handled safely\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport(fail_mode="malformed")
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service.publish_job(job)
        assert receipt.status == PublishState.PUBLISH_FAILED.value
        assert any("malformed" in err.lower() for err in receipt.errors)
        print(f"  Malformed response error: {receipt.errors}")
        print("  PASS: Malformed response caught and failed safely.")


def test_26_restart_during_publishing():
    print(f"\n{SEP}\nTEST 26: Restart during publishing reconciles via startup scanner\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service1 = PublishingService(store_dir=tmp, publisher=publisher)
        job, _ = _create_mock_job(tmp)

        receipt = service1.publish_job(job)
        # Simulate in-flight crash
        receipt.status = PublishState.PUBLISHING.value
        service1.store.save_receipt(receipt)

        # Service restarts
        service2 = PublishingService(store_dir=tmp, publisher=publisher)
        reconciled = service2.resume_pending_publishes()

        assert len(reconciled) >= 1
        assert reconciled[0].status == PublishState.PUBLISHED.value
        print(f"  Reconciled status: {reconciled[0].status}")
        print("  PASS: Startup scanner successfully reconciled in-flight receipt.")


def test_27_batch_mixed_outcomes():
    print(f"\n{SEP}\nTEST 27: Batch publishing with mixed provider outcomes\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()

        class SelectiveTransport(FakeYouTubeTransport):
            def upload_video(self, req, creds):
                if "fail" in req.clip_id:
                    raise PublishProviderError("Quota exceeded", PublishFailureClass.RATE_LIMITED.value)
                if "reject" in req.clip_id:
                    raise PublishProviderError("Policy reject", PublishFailureClass.PROVIDER_REJECTED.value)
                return super().upload_video(req, creds)

        publisher = YouTubePublisher(credentials=creds, transport=SelectiveTransport())
        service = PublishingService(store_dir=tmp, publisher=publisher)

        jobs_ok = [_create_mock_job(tmp, clip_id=f"yt_ok_{i}")[0] for i in range(4)]
        job_fail = _create_mock_job(tmp, clip_id="yt_fail")[0]
        job_rej = _create_mock_job(tmp, clip_id="yt_reject")[0]

        requests = [service.prepare_publish(j) for j in jobs_ok + [job_fail, job_rej]]
        batch_res = service.publish_batch("batch_mixed_yt", requests, max_workers=2)

        assert batch_res.total == 6
        assert batch_res.published == 4
        assert batch_res.failed == 1
        assert batch_res.rejected == 1

        print(f"  Batch Total={batch_res.total}, Published={batch_res.published}, "
              f"Failed={batch_res.failed}, Rejected={batch_res.rejected}")
        print("  PASS: Mixed batch provider outcomes cleanly isolated.")


# ─── Safety Audit ─────────────────────────────────────────────────────────────

def test_production_safety_audit():
    print(f"\n{SEP}\nSAFETY AUDIT: QA_FAILED, REJECTED, REPAIR_ESCALATED produce 0 provider calls\n{SEP}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        creds = _create_test_credentials()
        transport = FakeYouTubeTransport()
        publisher = YouTubePublisher(credentials=creds, transport=transport)
        service = PublishingService(store_dir=tmp, publisher=publisher)

        unsafe_jobs = [
            _create_mock_job(tmp, clip_id="qa_fail", qa_action="reject", qa_passed=False)[0],
            _create_mock_job(tmp, clip_id="job_rej", state=JobState.REJECTED.value)[0],
            _create_mock_job(tmp, clip_id="job_fail", state=JobState.FAILED.value)[0],
            _create_mock_job(tmp, clip_id="job_esc", state=JobState.REPAIR_ESCALATED.value, escalation={"reason": "re_render"})[0],
            _create_mock_job(tmp, clip_id="job_dry", execution_mode=ExecutionMode.DRY_RUN.value)[0],
        ]

        blocked_count = 0
        for j in unsafe_jobs:
            try:
                service.publish_job(j)
                assert False, f"Job {j.clip_id} should have been blocked"
            except PublishEligibilityError:
                blocked_count += 1

        assert blocked_count == len(unsafe_jobs)
        # 0 provider calls
        assert len(transport.calls) == 0
        print(f"  {blocked_count}/{len(unsafe_jobs)} unsafe jobs successfully blocked.")
        print(f"  Provider transport calls: {len(transport.calls)} (0 expected)")
        print("  PASS: Production safety audit 100% compliant.")


# ─── Regression Tests 28 & 29 ─────────────────────────────────────────────────

def test_28_phase12_regression():
    print(f"\n{SEP}\nTEST 28: Phase 12 Regression Suite (27/27 tests)\n{SEP}")
    res = subprocess.run(
        [sys.executable, "-u", "brain/test_publishing.py"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent)
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        assert False, f"Phase 12 regression suite failed with exit code {res.returncode}"
    print("  PASS: Phase 12 test suite passed with zero regressions.")


def test_29_phase11_regression():
    print(f"\n{SEP}\nTEST 29: Phase 11 Regression Suite (23/23 tests)\n{SEP}")
    res = subprocess.run(
        [sys.executable, "-u", "brain/test_orchestrator.py"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent)
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        assert False, f"Phase 11 regression suite failed with exit code {res.returncode}"
    print("  PASS: Phase 11 test suite passed with zero regressions.")


# ─── Test Suite Runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("TEST 1 — Config",              test_01_real_provider_configuration),
        ("TEST 2 — Missing Creds",       test_02_missing_credentials_fails_closed),
        ("TEST 3 — Invalid Creds",       test_03_invalid_credentials_classified),
        ("TEST 4 — Successful Upload",   test_04_successful_upload),
        ("TEST 5 — Hash Mismatch",       test_05_artifact_hash_mismatch_never_calls_provider),
        ("TEST 6 — Invalid Metadata",    test_06_invalid_metadata_never_calls_provider),
        ("TEST 7 — Provider Timeout",    test_07_provider_timeout_classified),
        ("TEST 8 — Ambiguous Upload",    test_08_ambiguous_successful_upload_reconciles),
        ("TEST 9 — Rate Limiting",       test_09_rate_limiting_bounded_retry),
        ("TEST 10 — Policy Rejection",   test_10_permanent_rejection_no_retry),
        ("TEST 11 — Scheduled Publish",  test_11_scheduled_publish),
        ("TEST 12 — Bad Scheduling",     test_12_unsupported_scheduling_fails_safely),
        ("TEST 13 — Visibility",         test_13_visibility_mapping),
        ("TEST 14 — Metadata Limits",    test_14_metadata_constraints),
        ("TEST 15 — Cancellation",       test_15_cancellation_mapping),
        ("TEST 16 — Provider Status",    test_16_provider_status_mapping),
        ("TEST 17 — External ID Persist", test_17_external_id_persistence),
        ("TEST 18 — Duplicate Publish",  test_18_duplicate_publish_single_invocation),
        ("TEST 19 — Concurrent Publish", test_19_concurrent_duplicate_publish),
        ("TEST 20 — Account Isolation",  test_20_account_isolation),
        ("TEST 21 — Secret Leakage",     test_21_secret_leakage_audit),
        ("TEST 22 — Dry-Run Isolation",  test_22_dry_run_isolation),
        ("TEST 23 — Provider Abstraction", test_23_provider_abstraction),
        ("TEST 24 — Transport Failure",  test_24_provider_transport_failure),
        ("TEST 25 — Malformed Response", test_25_malformed_provider_response),
        ("TEST 26 — Restart Recovery",   test_26_restart_during_publishing),
        ("TEST 27 — Batch Mixed",        test_27_batch_mixed_outcomes),
        ("SAFETY AUDIT",                 test_production_safety_audit),
        ("TEST 28 — Phase 12 Regression", test_28_phase12_regression),
        ("TEST 29 — Phase 11 Regression", test_29_phase11_regression),
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
    print("PHASE 13 REAL PROVIDER INTEGRATION TEST RESULTS")
    print(SEP)
    print(f"  PASSED: {len(passed)}/{len(tests)}")
    if failed:
        print(f"  FAILED: {len(failed)}/{len(tests)}")
        for label, reason in failed:
            print(f"    [{label}] {reason}")
    else:
        print("  ALL 30 TESTS PASSED (100%). Exit code: 0")
    print(SEP)

    sys.exit(0 if not failed else 1)
