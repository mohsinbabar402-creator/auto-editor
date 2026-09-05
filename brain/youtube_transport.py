"""
Production Publishing & Delivery Layer — YouTube Transport Abstraction (Phase 13)

PURPOSE:
    Decouples YouTube Data API communication from provider logic.
    Provides:
        - YouTubeTransport (abstract base contract)
        - FakeYouTubeTransport (deterministic simulation for automated tests)
        - HttpYouTubeTransport (real HTTP transport for live production calls)
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain.provider_credentials import YouTubeCredentials
from brain.publishing_models import (
    PublishFailureClass,
    PublishProviderError,
    PublishRequest,
)


class YouTubeTransport(ABC):
    """Abstract interface for YouTube network transport operations."""

    @abstractmethod
    def upload_video(
        self,
        request: PublishRequest,
        credentials: YouTubeCredentials,
    ) -> Dict[str, Any]:
        """Upload media artifact and return raw platform response dict."""
        ...

    @abstractmethod
    def get_video_status(
        self,
        video_id: str,
        credentials: YouTubeCredentials,
    ) -> Optional[Dict[str, Any]]:
        """Query YouTube Data API for video status."""
        ...

    @abstractmethod
    def cancel_or_delete_video(
        self,
        video_id: str,
        credentials: YouTubeCredentials,
    ) -> bool:
        """Attempt to delete or cancel an in-flight video."""
        ...

    @abstractmethod
    def check_health(self, credentials: YouTubeCredentials) -> Dict[str, Any]:
        """Verify API availability and credential authorization."""
        ...


class FakeYouTubeTransport(YouTubeTransport):
    """
    Deterministic transport for automated testing.
    Supports controllable failure simulation (timeouts, rate limits, 401s, 403s,
    malformed payloads, ambiguous timeouts) without making any network calls.
    """

    def __init__(
        self,
        fail_mode: Optional[str] = None,
        fail_times: int = 0,
        simulated_delay_sec: float = 0.0,
    ) -> None:
        self.fail_mode = fail_mode
        self.fail_remaining = fail_times
        self.delay_sec = simulated_delay_sec
        self.uploaded_videos: Dict[str, Dict[str, Any]] = {}
        self.calls: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def upload_video(
        self,
        request: PublishRequest,
        credentials: YouTubeCredentials,
    ) -> Dict[str, Any]:
        with self._lock:
            # Record call telemetry (strictly sanitizing credentials)
            self.calls.append({
                "account_id": credentials.account_id,
                "job_id": request.job_id,
                "clip_id": request.clip_id,
                "title": request.title,
                "artifact_hash": request.artifact_hash,
                "timestamp": time.time(),
            })

            if self.delay_sec > 0:
                time.sleep(self.delay_sec)

            # 1. Transient failure simulation
            if self.fail_remaining > 0:
                self.fail_remaining -= 1
                raise PublishProviderError(
                    "YouTube API connection reset by peer (503 Service Unavailable)",
                    failure_class=PublishFailureClass.TRANSIENT_PROVIDER_ERROR.value,
                )

            # 2. Specific failure modes
            if self.fail_mode == "timeout":
                raise PublishProviderError(
                    "YouTube API socket connection timed out after 30000ms",
                    failure_class=PublishFailureClass.TIMEOUT.value,
                )
            if self.fail_mode == "rate_limit":
                raise PublishProviderError(
                    "YouTube Data API quotaExceeded: The request cannot be completed because quota was exceeded",
                    failure_class=PublishFailureClass.RATE_LIMITED.value,
                )
            if self.fail_mode == "auth_error":
                raise PublishProviderError(
                    "YouTube API HTTP 401 Unauthorized: Invalid or expired OAuth token",
                    failure_class=PublishFailureClass.AUTHENTICATION_ERROR.value,
                )
            if self.fail_mode == "policy_reject":
                raise PublishProviderError(
                    "YouTube ContentID / Community Guidelines rejection: Video contains blocked content",
                    failure_class=PublishFailureClass.PROVIDER_REJECTED.value,
                )
            if self.fail_mode == "malformed":
                # Return invalid payload missing required 'id' key
                return {"kind": "youtube#video", "status": "unknown"}

            if self.fail_mode == "timeout_after_upload":
                # Provider accepts and stores video, but client socket drops on response
                vid = f"yt_{uuid.uuid4().hex[:11]}"
                self.uploaded_videos[vid] = {
                    "id": vid,
                    "status": {"uploadStatus": "uploaded", "privacyStatus": request.visibility},
                    "snippet": {"title": request.title, "tags": request.tags},
                }
                self.fail_mode = None  # Clear so get_video_status succeeds
                raise PublishProviderError(
                    f"Read timeout after chunk transmission (external_id={vid})",
                    failure_class=PublishFailureClass.TIMEOUT.value,
                )

            # Standard successful response
            vid = f"yt_{uuid.uuid4().hex[:11]}"
            response = {
                "id": vid,
                "kind": "youtube#video",
                "etag": f"etag_{uuid.uuid4().hex[:8]}",
                "snippet": {
                    "title": request.title,
                    "description": request.description,
                    "tags": request.tags,
                    "categoryId": "22",
                },
                "status": {
                    "uploadStatus": "uploaded",
                    "privacyStatus": request.visibility,
                    "publishAt": request.scheduled_at,
                },
            }
            self.uploaded_videos[vid] = copy.deepcopy(response)
            return response

    def get_video_status(
        self,
        video_id: str,
        credentials: YouTubeCredentials,
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            if video_id in self.uploaded_videos:
                return copy.deepcopy(self.uploaded_videos[video_id])
            return None

    def cancel_or_delete_video(
        self,
        video_id: str,
        credentials: YouTubeCredentials,
    ) -> bool:
        with self._lock:
            if video_id in self.uploaded_videos:
                self.uploaded_videos[video_id]["status"]["uploadStatus"] = "deleted"
                return True
            return False

    def check_health(self, credentials: YouTubeCredentials) -> Dict[str, Any]:
        with self._lock:
            if not credentials.is_valid():
                return {"healthy": False, "error": "Invalid credentials"}
            if self.fail_mode == "auth_error":
                return {"healthy": False, "error": "Authentication failed"}
            return {"healthy": True, "account_id": credentials.account_id, "transport": "FakeYouTubeTransport"}


class HttpYouTubeTransport(YouTubeTransport):
    """
    Production HTTP transport using YouTube Data API v3 Resumable Upload protocol.
    Only executed when credentials are explicitly configured.
    """

    def __init__(self, upload_url: str = "https://www.googleapis.com/upload/youtube/v3/videos") -> None:
        self.upload_url = upload_url

    def upload_video(
        self,
        request: PublishRequest,
        credentials: YouTubeCredentials,
    ) -> Dict[str, Any]:
        if not credentials.is_valid():
            raise PublishProviderError(
                "Missing or invalid YouTube credentials",
                failure_class=PublishFailureClass.AUTHENTICATION_ERROR.value,
            )

        import urllib.error
        import urllib.request

        # YouTube Data API Resumable Upload initial request
        metadata_payload = {
            "snippet": {
                "title": request.title[:100],
                "description": request.description[:5000],
                "tags": request.tags,
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": request.visibility,
            }
        }
        if request.scheduled_at:
            metadata_payload["status"]["publishAt"] = request.scheduled_at
            metadata_payload["status"]["privacyStatus"] = "private"

        init_url = f"{self.upload_url}?uploadType=resumable&part=snippet,status"
        headers = {
            "Authorization": f"Bearer {credentials.access_token or credentials.refresh_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
        }

        try:
            req = urllib.request.Request(
                init_url,
                data=json.dumps(metadata_payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                upload_location = resp.headers.get("Location")
                if not upload_location:
                    raise PublishProviderError(
                        "YouTube API failed to return resumable upload Location header",
                        failure_class=PublishFailureClass.TRANSIENT_PROVIDER_ERROR.value,
                    )

            # Upload video binary in stream
            artifact_file = Path(request.artifact_path)
            with open(artifact_file, "rb") as vf:
                media_bytes = vf.read()

            media_headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(len(media_bytes)),
            }
            media_req = urllib.request.Request(
                upload_location,
                data=media_bytes,
                headers=media_headers,
                method="PUT"
            )
            with urllib.request.urlopen(media_req, timeout=120) as final_resp:
                raw_body = final_resp.read().decode("utf-8")
                return json.loads(raw_body)

        except urllib.error.HTTPError as he:
            code = he.code
            if code in (401, 403):
                raise PublishProviderError(
                    f"YouTube API Authentication Error ({code}): {he.reason}",
                    failure_class=PublishFailureClass.AUTHENTICATION_ERROR.value,
                )
            elif code == 429:
                raise PublishProviderError(
                    "YouTube API Rate Limit Exceeded (429)",
                    failure_class=PublishFailureClass.RATE_LIMITED.value,
                )
            elif code >= 500:
                raise PublishProviderError(
                    f"YouTube API Server Error ({code}): {he.reason}",
                    failure_class=PublishFailureClass.TRANSIENT_PROVIDER_ERROR.value,
                )
            else:
                raise PublishProviderError(
                    f"YouTube API Client Error ({code}): {he.reason}",
                    failure_class=PublishFailureClass.INVALID_REQUEST.value,
                )
        except urllib.error.URLError as ue:
            raise PublishProviderError(
                f"YouTube API Network Error: {ue.reason}",
                failure_class=PublishFailureClass.NETWORK_ERROR.value,
            )

    def get_video_status(
        self,
        video_id: str,
        credentials: YouTubeCredentials,
    ) -> Optional[Dict[str, Any]]:
        import urllib.error
        import urllib.request

        url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,status&id={video_id}"
        headers = {
            "Authorization": f"Bearer {credentials.access_token or credentials.refresh_token}",
        }
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                return items[0] if items else None
        except Exception:
            return None

    def cancel_or_delete_video(
        self,
        video_id: str,
        credentials: YouTubeCredentials,
    ) -> bool:
        import urllib.error
        import urllib.request

        url = f"https://www.googleapis.com/youtube/v3/videos?id={video_id}"
        headers = {
            "Authorization": f"Bearer {credentials.access_token or credentials.refresh_token}",
        }
        try:
            req = urllib.request.Request(url, headers=headers, method="DELETE")
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status in (200, 204)
        except Exception:
            return False

    def check_health(self, credentials: YouTubeCredentials) -> Dict[str, Any]:
        if not credentials.is_valid():
            return {"healthy": False, "error": "Invalid credentials"}
        return {"healthy": True, "account_id": credentials.account_id, "transport": "HttpYouTubeTransport"}
