from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import time

logger = logging.getLogger("whop_editor.profile_registry")


class ProfileAuthStatus(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    DISABLED = "DISABLED"


class ProfileRuntimeStatus(str, Enum):
    IDLE = "IDLE"
    BUSY = "BUSY"
    ERROR = "ERROR"


@dataclass
class BrowserProfile:
    profile_id: str
    user_data_dir: str
    auth_status: ProfileAuthStatus = ProfileAuthStatus.AUTH_REQUIRED
    account_email: Optional[str] = None
    flow_capable: bool = True
    gemini_capable: bool = True
    assigned_worker_id: Optional[str] = None
    enabled: bool = True
    last_successful_launch: Optional[str] = None
    last_successful_gemini_review: Optional[str] = None
    current_status: ProfileRuntimeStatus = ProfileRuntimeStatus.IDLE
    worker_role: str = "whop_production"
    assigned_project: str = "proj_whop_shortform"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "user_data_dir": self.user_data_dir,
            "auth_status": self.auth_status.value if isinstance(self.auth_status, ProfileAuthStatus) else self.auth_status,
            "account_email": self.account_email,
            "flow_capable": self.flow_capable,
            "gemini_capable": self.gemini_capable,
            "assigned_worker_id": self.assigned_worker_id,
            "enabled": self.enabled,
            "last_successful_launch": self.last_successful_launch,
            "last_successful_gemini_review": self.last_successful_gemini_review,
            "current_status": self.current_status.value if isinstance(self.current_status, ProfileRuntimeStatus) else self.current_status,
            "worker_role": self.worker_role,
            "assigned_project": self.assigned_project,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrowserProfile":
        data = data.copy()
        data["auth_status"] = ProfileAuthStatus(data.get("auth_status", "AUTH_REQUIRED"))
        data["current_status"] = ProfileRuntimeStatus(data.get("current_status", "IDLE"))
        if "worker_role" not in data:
            data["worker_role"] = "whop_production"
        if "assigned_project" not in data:
            data["assigned_project"] = "proj_whop_shortform"
        return cls(**data)


class ProfileRegistry:
    """
    Registry for managing 8 browser profiles (flow_profile_1 to flow_profile_8).
    Tracks authentication status, worker roles, active worker assignments, and capability dispatching.
    NEVER stores passwords, cookies, or access tokens.
    """

    DEFAULT_REGISTRY_FILE = Path("browser/profile_registry.json")

    def __init__(self, registry_file: Optional[Path] = None, base_browser_dir: Optional[Path] = None):
        self.registry_file = (registry_file or self.DEFAULT_REGISTRY_FILE).resolve()
        self.base_browser_dir = (base_browser_dir or Path("browser")).resolve()
        self.profiles: Dict[str, BrowserProfile] = {}
        self._load_or_initialize()

    def _load_or_initialize(self):
        default_configs = [
            ("flow_profile_1", ProfileAuthStatus.AUTHENTICATED, "mohsinoctal777@gmail.com", "whop_production", "proj_whop_shortform"),
            ("flow_profile_2", ProfileAuthStatus.AUTHENTICATED, "aoctal522@gmail.com", "whop_production", "proj_whop_shortform"),
            ("flow_profile_3", ProfileAuthStatus.AUTHENTICATED, "mohsinmughal1771@gmail.com", "whop_production", "proj_whop_shortform"),
            ("flow_profile_4", ProfileAuthStatus.AUTHENTICATED, "blazingsoul451@gmail.com", "whop_production", "proj_whop_shortform"),
            ("flow_profile_5", ProfileAuthStatus.AUTH_REQUIRED, "zestify1771@gmail.com", "whop_production", "proj_whop_shortform"),
            ("flow_profile_6", ProfileAuthStatus.AUTH_REQUIRED, None, "flexible_experiments", "proj_experiments"),
            ("flow_profile_7", ProfileAuthStatus.AUTH_REQUIRED, None, "other_projects", "proj_secondary"),
            ("flow_profile_8", ProfileAuthStatus.AUTH_REQUIRED, None, "other_projects_research", "proj_research"),
        ]

        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    for item in raw:
                        prof = BrowserProfile.from_dict(item)
                        self.profiles[prof.profile_id] = prof
                
                # Backfill any missing profiles up to 8
                modified = False
                for p_id, auth_st, email, role, proj in default_configs:
                    if p_id not in self.profiles:
                        p_dir = str((self.base_browser_dir / p_id).resolve())
                        self.profiles[p_id] = BrowserProfile(
                            profile_id=p_id,
                            user_data_dir=p_dir,
                            auth_status=auth_st,
                            account_email=email,
                            flow_capable=True,
                            gemini_capable=True,
                            enabled=True,
                            current_status=ProfileRuntimeStatus.IDLE,
                            worker_role=role,
                            assigned_project=proj,
                        )
                        modified = True
                
                if modified:
                    self.save()

                logger.info(f"Loaded {len(self.profiles)} browser profiles from {self.registry_file}")
                return
            except Exception as e:
                logger.warning(f"Failed to load registry file {self.registry_file}: {e}. Reinitializing.")

        self.profiles.clear()
        for p_id, auth_st, email, role, proj in default_configs:
            p_dir = str((self.base_browser_dir / p_id).resolve())
            self.profiles[p_id] = BrowserProfile(
                profile_id=p_id,
                user_data_dir=p_dir,
                auth_status=auth_st,
                account_email=email,
                flow_capable=True,
                gemini_capable=True,
                enabled=True,
                current_status=ProfileRuntimeStatus.IDLE,
                worker_role=role,
                assigned_project=proj,
            )

        self.save()

    def save(self):
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        data = [p.to_dict() for p in self.profiles.values()]
        with open(self.registry_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_profile(self, profile_id: str) -> Optional[BrowserProfile]:
        return self.profiles.get(profile_id)

    def get_all_profiles(self) -> List[BrowserProfile]:
        return list(self.profiles.values())

    def acquire_profile(self, capability: str = "gemini", preferred_id: Optional[str] = None) -> Optional[BrowserProfile]:
        """
        Dynamically selects an available, authenticated profile and marks it BUSY.
        If preferred_id is given and available, prioritizes it.
        """
        if preferred_id and preferred_id in self.profiles:
            p = self.profiles[preferred_id]
            if p.enabled and p.auth_status == ProfileAuthStatus.AUTHENTICATED and p.current_status != ProfileRuntimeStatus.BUSY:
                p.current_status = ProfileRuntimeStatus.BUSY
                self.save()
                return p

        for p in self.profiles.values():
            if not p.enabled:
                continue
            if p.auth_status != ProfileAuthStatus.AUTHENTICATED:
                continue
            if p.current_status == ProfileRuntimeStatus.BUSY:
                continue
            if capability == "gemini" and not p.gemini_capable:
                continue
            if capability == "flow" and not p.flow_capable:
                continue

            p.current_status = ProfileRuntimeStatus.BUSY
            self.save()
            return p

        return None

    def release_profile(self, profile_id: str, success: bool = True, is_gemini_review: bool = False):
        """
        Releases a profile back to IDLE status and updates timestamp.
        """
        if profile_id not in self.profiles:
            return

        p = self.profiles[profile_id]
        p.current_status = ProfileRuntimeStatus.IDLE
        iso_now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        p.last_successful_launch = iso_now
        if success and is_gemini_review:
            p.last_successful_gemini_review = iso_now
        self.save()

    def mark_auth_required(self, profile_id: str):
        if profile_id in self.profiles:
            self.profiles[profile_id].auth_status = ProfileAuthStatus.AUTH_REQUIRED
            self.profiles[profile_id].current_status = ProfileRuntimeStatus.IDLE
            self.save()

    def mark_authenticated(self, profile_id: str, email: Optional[str] = None):
        if profile_id in self.profiles:
            self.profiles[profile_id].auth_status = ProfileAuthStatus.AUTHENTICATED
            if email:
                self.profiles[profile_id].account_email = email
            self.profiles[profile_id].current_status = ProfileRuntimeStatus.IDLE
            self.save()
