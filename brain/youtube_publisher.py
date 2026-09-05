"""
Production Publishing & Delivery Layer — YouTube Publisher Provider (Phase 13)

PURPOSE:
    Implements PublisherInterface for YouTube Shorts delivery.
    Translates PublishRequest into YouTube Data API calls, enforces YouTube-specific
    metadata and visibility constraints, normalizes responses into PublishReceipts,
    and handles status reconciliation and cancellation.

INVARIANTS:
    - Conforms strictly to PublisherInterface.
    - Never leaks credentials, client secrets, or OAuth tokens into receipts/logs.
    - Verifies artifact existence and SHA-256 hash before transmission.
    - Normalizes all responses into PublishReceipt.
    - Preserves multi-account isolation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain.provider_credentials import CredentialStore, YouTubeCredentials
from brain.publishing_models import (
    PublishFailureClass,
    PublishProviderError,
    PublishReceipt,
    PublishRequest,
    PublishState,
    PublisherInterface,
)
from brain.youtube_transport import FakeYouTubeTransport, YouTubeTransport


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class YouTubePublisher(PublisherInterface):
    """
    Production-grade YouTube publisher implementing PublisherInterface.
    Communicates with YouTube Data API v3 via pluggable transport.
    """

    def __init__(
        self,
        credentials: Optional[YouTubeCredentials] = None,
        credential_store: Optional[CredentialStore] = None,
        transport: Optional[YouTubeTransport] = None,
        environment: str = "TEST",
    ) -> None:
        self._credentials = credentials
        self._credential_store = credential_store or CredentialStore()
        if credentials:
            self._credential_store.register_credentials(credentials.account_id, credentials, "youtube")

        # Default to FakeYouTubeTransport in TEST/simulation to prevent accidental live calls
        self.transport = transport or FakeYouTubeTransport()
        self.environment = environment
        self._lock = threading.Lock()
        self._published_receipts: Dict[str, PublishReceipt] = {}

    @property
    def name(self) -> str:
        return "YouTubePublisher"

    def _resolve_credentials(self, account_id: str) -> YouTubeCredentials:
        """Resolve valid credentials for the specified account or fail closed."""
        creds = self._credential_store.get_credentials(account_id, "youtube")
        if creds is None and self._credentials and self._credentials.account_id == account_id:
            creds = self._credentials

        if creds is None or not creds.is_valid():
            raise PublishProviderError(
                f"Missing or invalid credentials for YouTube account '{account_id}'. Fail closed.",
                failure_class=PublishFailureClass.AUTHENTICATION_ERROR.value,
            )
        return creds

    def _validate_youtube_metadata(self, request: PublishRequest) -> None:
        """Enforce platform-specific metadata constraints for YouTube Shorts."""
        # Title constraint: max 100 characters
        if len(request.title) > 100:
            raise PublishProviderError(
                f"YouTube title exceeds 100 characters ({len(request.title)} chars): '{request.title[:40]}...'",
                failure_class=PublishFailureClass.INVALID_METADATA.value,
            )

        # Description constraint: max 5000 characters
        if len(request.description) > 5000:
            raise PublishProviderError(
                f"YouTube description exceeds 5000 characters ({len(request.description)} chars)",
                failure_class=PublishFailureClass.INVALID_METADATA.value,
            )

        # Tags constraint: max 500 characters combined
        total_tag_len = sum(len(t) for t in request.tags)
        if total_tag_len > 500:
            raise PublishProviderError(
                f"YouTube tags combined length exceeds 500 characters ({total_tag_len} chars)",
                failure_class=PublishFailureClass.INVALID_METADATA.value,
            )

        # Visibility constraint: public, unlisted, private
        valid_vis = {"public", "unlisted", "private"}
        if request.visibility.lower() not in valid_vis:
            raise PublishProviderError(
                f"Invalid visibility '{request.visibility}'. YouTube requires one of: {valid_vis}",
                failure_class=PublishFailureClass.INVALID_METADATA.value,
            )

        # Scheduling constraint: must be a valid future ISO 8601 timestamp
        if request.scheduled_at:
            try:
                # Basic ISO parse check
                sched_dt = datetime.fromisoformat(request.scheduled_at.replace("Z", "+00:00"))
                if sched_dt <= datetime.now(timezone.utc):
                    raise PublishProviderError(
                        f"scheduled_at must be in the future: {request.scheduled_at}",
                        failure_class=PublishFailureClass.INVALID_METADATA.value,
                    )
            except ValueError as e:
                raise PublishProviderError(
                    f"Invalid scheduled_at ISO timestamp: {request.scheduled_at} ({e})",
                    failure_class=PublishFailureClass.INVALID_METADATA.value,
                )

    def publish(self, request: Any, metadata: Optional[Dict[str, Any]] = None) -> PublishReceipt:
        # Backward compatibility for legacy dictionary or path calls
        if isinstance(request, (str, Path)):
            req = PublishRequest(
                job_id=metadata.get("job_id", "legacy_job"),
                episode_id=metadata.get("episode_id", "legacy_ep"),
                clip_id=metadata.get("clip_id", "legacy_clip"),
                account_id=metadata.get("account_id", "default"),
                platform=metadata.get("platform", "youtube_shorts"),
                artifact_path=str(request),
                artifact_hash=_file_sha256(Path(request)),
                title=metadata.get("title", "Untitled Short"),
                description=metadata.get("description", ""),
                tags=metadata.get("tags", []),
                visibility=metadata.get("visibility", "public"),
            )
        else:
            req = request

        # 1. Environment & Dry-Run Quarantine Check
        if req.execution_mode != "PRODUCTION" and self.environment == "PRODUCTION":
            raise PublishProviderError(
                f"Cannot publish {req.execution_mode} job to YouTube in PRODUCTION environment.",
                failure_class=PublishFailureClass.AUTHENTICATION_ERROR.value,
            )

        # 2. Resolve credentials (fail closed if missing)
        creds = self._resolve_credentials(req.account_id)

        # 3. Validate metadata constraints
        self._validate_youtube_metadata(req)

        # 4. Verify artifact existence & immutability hash
        art_path = Path(req.artifact_path)
        if not art_path.exists():
            raise PublishProviderError(
                f"Artifact file missing: {req.artifact_path}",
                failure_class=PublishFailureClass.ARTIFACT_UNAVAILABLE.value,
            )

        current_hash = _file_sha256(art_path)
        if req.artifact_hash and current_hash != req.artifact_hash:
            raise PublishProviderError(
                f"Artifact hash mismatch: approved={req.artifact_hash[:12]}..., current={current_hash[:12]}...",
                failure_class=PublishFailureClass.ARTIFACT_INTEGRITY_ERROR.value,
            )

        # 5. Check idempotency / already uploaded
        with self._lock:
            if req.idempotency_key:
                for r in self._published_receipts.values():
                    if r.idempotency_key == req.idempotency_key and r.status == PublishState.PUBLISHED.value:
                        return copy.deepcopy(r)

        # 6. Execute upload via transport
        start_time = time.monotonic()
        raw_response = self.transport.upload_video(req, creds)
        duration = round(time.monotonic() - start_time, 3)

        # 7. Validate response payload
        video_id = raw_response.get("id")
        if not video_id or not isinstance(video_id, str):
            raise PublishProviderError(
                f"YouTube API returned malformed response without video id: {raw_response}",
                failure_class=PublishFailureClass.INVALID_REQUEST.value,
            )

        # 8. Normalize into PublishReceipt (strictly sanitizing secrets)
        receipt = PublishReceipt(
            receipt_id=f"rec_yt_{uuid.uuid4().hex[:10]}",
            job_id=req.job_id,
            clip_id=req.clip_id,
            platform="youtube_shorts",
            provider=self.name,
            external_id=video_id,
            status=PublishState.PUBLISHED.value,
            published_at=_now_iso(),
            artifact_hash=current_hash,
            idempotency_key=req.idempotency_key,
            provider_metadata={
                "video_id": video_id,
                "url": f"https://youtube.com/shorts/{video_id}",
                "visibility": req.visibility,
                "scheduled_at": req.scheduled_at,
                "account_id": req.account_id,
            },
            errors=[],
            attempt_count=1,
            duration_sec=duration,
        )

        with self._lock:
            self._published_receipts[video_id] = copy.deepcopy(receipt)

        return receipt

    def get_status(self, external_id: str) -> Optional[PublishReceipt]:
        """
        Query remote YouTube Data API status and map to normalized PublishState.
        """
        # Determine account if available from local cache
        creds = None
        account_id = "default"
        with self._lock:
            if external_id in self._published_receipts:
                cached = self._published_receipts[external_id]
                account_id = cached.provider_metadata.get("account_id", "default")

        try:
            creds = self._resolve_credentials(account_id)
        except Exception:
            # If creds missing, use fallback if configured
            if self._credentials:
                creds = self._credentials

        if creds is None:
            return None

        status_data = self.transport.get_video_status(external_id, creds)
        if not status_data:
            return None

        # Map YouTube status object
        status_info = status_data.get("status", {})
        upload_status = status_info.get("uploadStatus", "").lower()

        if upload_status in ("uploaded", "processed"):
            norm_state = PublishState.PUBLISHED.value
        elif upload_status in ("processing", "uploading"):
            norm_state = PublishState.PUBLISHING.value
        elif upload_status in ("rejected", "failed"):
            norm_state = PublishState.PUBLISH_REJECTED.value
        elif upload_status in ("deleted", "cancelled"):
            norm_state = PublishState.PUBLISH_CANCELLED.value
        else:
            norm_state = PublishState.PUBLISHED.value

        receipt = PublishReceipt(
            receipt_id=f"rec_status_{uuid.uuid4().hex[:8]}",
            job_id="",
            clip_id="",
            platform="youtube_shorts",
            provider=self.name,
            external_id=external_id,
            status=norm_state,
            published_at=_now_iso(),
            artifact_hash="",
            idempotency_key="",
            provider_metadata={"youtube_status": upload_status},
        )
        return receipt

    def cancel(self, external_id: str) -> bool:
        """Cancel or delete a video on YouTube."""
        account_id = "default"
        with self._lock:
            if external_id in self._published_receipts:
                account_id = self._published_receipts[external_id].provider_metadata.get("account_id", "default")

        try:
            creds = self._resolve_credentials(account_id)
        except Exception:
            creds = self._credentials

        if not creds:
            return False

        cancelled = self.transport.cancel_or_delete_video(external_id, creds)
        if cancelled:
            with self._lock:
                if external_id in self._published_receipts:
                    self._published_receipts[external_id].status = PublishState.PUBLISH_CANCELLED.value
        return cancelled

    def health_check(self, account_id: str = "") -> Dict[str, Any]:
        """Verify provider configuration, credential validity, and transport health."""
        acc = account_id or (self._credentials.account_id if self._credentials else "default")
        try:
            creds = self._resolve_credentials(acc)
            health = self.transport.check_health(creds)
            return {
                "healthy": health.get("healthy", False),
                "provider": self.name,
                "environment": self.environment,
                "account_id": acc,
                "details": health,
            }
        except Exception as e:
            return {
                "healthy": False,
                "provider": self.name,
                "environment": self.environment,
                "account_id": acc,
                "error": str(e),
            }
