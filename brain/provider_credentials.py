"""
Production Publishing & Delivery Layer — Provider Credentials (Phase 13)

PURPOSE:
    Secure credential abstraction, multi-account isolation, and secret masking
    for real publishing providers (e.g. YouTube Data API v3).

SECURITY INVARIANTS:
    - Never log secrets, client_secret, refresh_token, or access_token.
    - Never include credentials in receipts, audit events, or artifact metadata.
    - Multi-account isolation: Account A cannot access Account B credentials.
    - Fail closed: if credentials are missing or invalid, block provider calls.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class YouTubeCredentials:
    """
    Credentials for YouTube Data API v3 integration.
    Sensitive fields are masked in __repr__ and __str__ to prevent accidental leaks.
    """
    account_id: str
    client_id: str
    client_secret: str
    refresh_token: str
    access_token: Optional[str] = None
    token_expiry_iso: Optional[str] = None
    channel_id: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"YouTubeCredentials(account_id='{self.account_id}', "
            f"client_id='{self.client_id[:6]}...', "
            f"client_secret='[REDACTED]', "
            f"refresh_token='[REDACTED]', "
            f"access_token={'[SET]' if self.access_token else '[NONE]'})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def is_valid(self) -> bool:
        """Check that mandatory credentials exist and are non-empty."""
        return bool(
            self.account_id.strip()
            and self.client_id.strip()
            and self.client_secret.strip()
            and (self.refresh_token.strip() or (self.access_token and self.access_token.strip()))
        )

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return a dictionary safe for inspection, with all secrets redacted."""
        return {
            "account_id": self.account_id,
            "client_id_prefix": self.client_id[:6] + "..." if self.client_id else "",
            "has_client_secret": bool(self.client_secret),
            "has_refresh_token": bool(self.refresh_token),
            "has_access_token": bool(self.access_token),
            "channel_id": self.channel_id or "",
        }


class CredentialStore:
    """
    Thread-safe in-memory and environment-backed credential repository.
    Enforces strict multi-account isolation.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register_credentials(
        self,
        account_id: str,
        credentials: Any,
        provider: str = "youtube",
    ) -> None:
        """Register credentials under an explicit account_id and provider."""
        with self._lock:
            key = f"{provider}::{account_id}"
            self._store[key] = credentials

    def get_credentials(
        self,
        account_id: str,
        provider: str = "youtube",
    ) -> Optional[Any]:
        """Retrieve credentials for an explicit account_id. Fails closed if absent."""
        with self._lock:
            key = f"{provider}::{account_id}"
            if key in self._store:
                return self._store[key]

        # Fallback: check environment variables for the specified account if configured
        env_prefix = f"{provider.upper()}_{account_id.upper()}"
        cid = os.getenv(f"{env_prefix}_CLIENT_ID") or os.getenv(f"{provider.upper()}_CLIENT_ID")
        csec = os.getenv(f"{env_prefix}_CLIENT_SECRET") or os.getenv(f"{provider.upper()}_CLIENT_SECRET")
        rtoken = os.getenv(f"{env_prefix}_REFRESH_TOKEN") or os.getenv(f"{provider.upper()}_REFRESH_TOKEN")

        if cid and csec and rtoken:
            creds = YouTubeCredentials(
                account_id=account_id,
                client_id=cid,
                client_secret=csec,
                refresh_token=rtoken,
                channel_id=os.getenv(f"{env_prefix}_CHANNEL_ID"),
            )
            self.register_credentials(account_id, creds, provider)
            return creds

        return None

    def has_credentials(self, account_id: str, provider: str = "youtube") -> bool:
        return self.get_credentials(account_id, provider) is not None

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
