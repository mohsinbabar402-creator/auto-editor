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
    COOLDOWN = "COOLDOWN"
    ERROR = "ERROR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    DISABLED = "DISABLED"


class _FileLock:
    """Cross-process file lock using native Windows msvcrt or POSIX fcntl."""
    def __init__(self, lock_path: Path, timeout: float = 10.0):
        self.lock_path = lock_path
        self.timeout = timeout
        self.handle = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()
        while True:
            try:
                self.handle = open(self.lock_path, "a+")
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except (IOError, OSError):
                if self.handle:
                    try:
                        self.handle.close()
                    except Exception:
                        pass
                    self.handle = None
                if time.time() - start >= self.timeout:
                    logger.warning(f"Timeout waiting for lock {self.lock_path}. Proceeding carefully.")
                    return self
                time.sleep(0.05)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handle:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self.handle.close()
            except Exception:
                pass
            self.handle = None


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
    worker_role: str = "generic_production"
    assigned_project: str = "generic"
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[str] = None
    cooldown_until: Optional[str] = None

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
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "cooldown_until": self.cooldown_until,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrowserProfile":
        data = data.copy()
        data["auth_status"] = ProfileAuthStatus(data.get("auth_status", "AUTH_REQUIRED"))
        data["current_status"] = ProfileRuntimeStatus(data.get("current_status", "IDLE"))
        if "worker_role" not in data:
            data["worker_role"] = "generic_production"
        if "assigned_project" not in data:
            data["assigned_project"] = "generic"
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
        self.lock_file = self.registry_file.with_suffix(".lock")
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

    def acquire_profile(
        self,
        capability: str = "gemini",
        preferred_id: Optional[str] = None,
        lease_owner: Optional[str] = None,
        lease_timeout_sec: int = 600
    ) -> Optional[BrowserProfile]:
        """
        Cross-process safe profile acquisition using file locking.
        Dynamically selects an available, authenticated profile and marks it BUSY with lease metadata.
        """
        with _FileLock(self.lock_file):
            self._load_or_initialize()
            now_ts = time.time()
            iso_now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))

            # 1. Reclaim stale leases or expired cooldowns
            for p in self.profiles.values():
                if p.current_status == ProfileRuntimeStatus.BUSY and p.lease_expires_at:
                    try:
                        exp = time.mktime(time.strptime(p.lease_expires_at, "%Y-%m-%dT%H:%M:%SZ"))
                        if now_ts > exp:
                            logger.warning(f"Reclaiming stale lease for profile [{p.profile_id}] (owner was {p.lease_owner})")
                            p.current_status = ProfileRuntimeStatus.IDLE
                            p.lease_owner = None
                            p.lease_expires_at = None
                    except Exception:
                        pass
                elif p.current_status == ProfileRuntimeStatus.COOLDOWN and p.cooldown_until:
                    try:
                        cd = time.mktime(time.strptime(p.cooldown_until, "%Y-%m-%dT%H:%M:%SZ"))
                        if now_ts > cd:
                            p.current_status = ProfileRuntimeStatus.IDLE
                            p.cooldown_until = None
                    except Exception:
                        pass

            # 2. Check preferred ID first
            target_profile = None
            if preferred_id and preferred_id in self.profiles:
                p = self.profiles[preferred_id]
                if p.enabled and p.auth_status == ProfileAuthStatus.AUTHENTICATED and p.current_status == ProfileRuntimeStatus.IDLE:
                    target_profile = p

            # 3. Check pool if no preferred profile
            if not target_profile:
                for p in self.profiles.values():
                    if not p.enabled or p.auth_status != ProfileAuthStatus.AUTHENTICATED:
                        continue
                    if p.current_status != ProfileRuntimeStatus.IDLE:
                        continue
                    if capability == "gemini" and not p.gemini_capable:
                        continue
                    if capability == "flow" and not p.flow_capable:
                        continue
                    target_profile = p
                    break

            if target_profile:
                target_profile.current_status = ProfileRuntimeStatus.BUSY
                target_profile.lease_owner = lease_owner
                lease_exp_ts = now_ts + lease_timeout_sec
                target_profile.lease_expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(lease_exp_ts))
                self.save()
                logger.info(f"Leased profile [{target_profile.profile_id}] to [{lease_owner}] until {target_profile.lease_expires_at}")
                return target_profile

            return None

    def release_profile(
        self,
        profile_id: str,
        success: bool = True,
        is_gemini_review: bool = False,
        cooldown_sec: int = 0
    ):
        """
        Cross-process safe release of profile back to IDLE or COOLDOWN status under file lock.
        """
        with _FileLock(self.lock_file):
            self._load_or_initialize()
            if profile_id not in self.profiles:
                return

            p = self.profiles[profile_id]
            now_ts = time.time()
            iso_now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
            p.last_successful_launch = iso_now
            if success and is_gemini_review:
                p.last_successful_gemini_review = iso_now

            p.lease_owner = None
            p.lease_expires_at = None

            if cooldown_sec > 0:
                p.current_status = ProfileRuntimeStatus.COOLDOWN
                p.cooldown_until = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts + cooldown_sec))
            else:
                p.current_status = ProfileRuntimeStatus.IDLE
                p.cooldown_until = None

            self.save()
            logger.info(f"Released profile [{profile_id}] (status={p.current_status.value})")

    def mark_auth_required(self, profile_id: str):
        with _FileLock(self.lock_file):
            self._load_or_initialize()
            if profile_id in self.profiles:
                self.profiles[profile_id].auth_status = ProfileAuthStatus.AUTH_REQUIRED
                self.profiles[profile_id].current_status = ProfileRuntimeStatus.IDLE
                self.profiles[profile_id].lease_owner = None
                self.profiles[profile_id].lease_expires_at = None
                self.save()

    def mark_authenticated(self, profile_id: str, email: Optional[str] = None):
        with _FileLock(self.lock_file):
            self._load_or_initialize()
            if profile_id in self.profiles:
                self.profiles[profile_id].auth_status = ProfileAuthStatus.AUTHENTICATED
                if email:
                    self.profiles[profile_id].account_email = email
                self.profiles[profile_id].current_status = ProfileRuntimeStatus.IDLE
                self.profiles[profile_id].lease_owner = None
                self.profiles[profile_id].lease_expires_at = None
                self.save()

