import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from browser.profile_registry import ProfileRegistry, ProfileAuthStatus, ProfileRuntimeStatus
from db.repository import DatabaseRepository, EntityNotFoundError, RepositoryError
from workers.models import Worker, WorkerStatus, utc_now_iso

logger = logging.getLogger("whop_editor.worker_registry")

# Standard worker mapping for the 8 profiles
DEFAULT_WORKER_PROFILES = [
    {
        "worker_id": "worker_w1",
        "profile_id": "flow_profile_1",
        "provider": "flow_gemini",
        "capabilities": ["EDITING", "RENDERING", "AUDIO_EXTRACTION", "REVIEW", "FLOW_GENERATE"],
        "role": "whop_production",
        "assigned_project": "proj_whop_shortform",
        "priority": 1,
    },
    {
        "worker_id": "worker_w2",
        "profile_id": "flow_profile_2",
        "provider": "flow_gemini",
        "capabilities": ["EDITING", "RENDERING", "AUDIO_EXTRACTION", "REVIEW", "FLOW_GENERATE"],
        "role": "whop_production",
        "assigned_project": "proj_whop_shortform",
        "priority": 1,
    },
    {
        "worker_id": "worker_w3",
        "profile_id": "flow_profile_3",
        "provider": "flow_gemini",
        "capabilities": ["EDITING", "RENDERING", "AUDIO_EXTRACTION", "REVIEW", "FLOW_GENERATE"],
        "role": "whop_production",
        "assigned_project": "proj_whop_shortform",
        "priority": 1,
    },
    {
        "worker_id": "worker_w4",
        "profile_id": "flow_profile_4",
        "provider": "flow_gemini",
        "capabilities": ["EDITING", "RENDERING", "AUDIO_EXTRACTION", "REVIEW", "FLOW_GENERATE"],
        "role": "whop_production",
        "assigned_project": "proj_whop_shortform",
        "priority": 1,
    },
    {
        "worker_id": "worker_w5",
        "profile_id": "flow_profile_5",
        "provider": "flow_gemini",
        "capabilities": ["EDITING", "RENDERING", "AUDIO_EXTRACTION", "REVIEW", "FLOW_GENERATE"],
        "role": "whop_production",
        "assigned_project": "proj_whop_shortform",
        "priority": 1,
    },
    {
        "worker_id": "worker_w6",
        "profile_id": "flow_profile_6",
        "provider": "flow_gemini",
        "capabilities": ["EDITING", "RENDERING", "AUDIO_EXTRACTION", "REVIEW", "FLOW_GENERATE", "EXPERIMENT"],
        "role": "flexible_experiments",
        "assigned_project": "proj_experiments",
        "priority": 2,
    },
    {
        "worker_id": "worker_w7",
        "profile_id": "flow_profile_7",
        "provider": "flow_gemini",
        "capabilities": ["EDITING", "RENDERING", "AUDIO_EXTRACTION", "REVIEW", "FLOW_GENERATE"],
        "role": "other_projects",
        "assigned_project": "proj_secondary",
        "priority": 3,
    },
    {
        "worker_id": "worker_w8",
        "profile_id": "flow_profile_8",
        "provider": "flow_gemini",
        "capabilities": ["EDITING", "RENDERING", "AUDIO_EXTRACTION", "REVIEW", "FLOW_GENERATE", "RESEARCH"],
        "role": "other_projects_research",
        "assigned_project": "proj_research",
        "priority": 3,
    },
]


class WorkerRegistry:
    """
    Unified Worker Registry backed by PostgreSQL.
    Manages W1-W8 worker allocations, role affinities, capability matching,
    and profile authentication state synchronization.
    """

    def __init__(
        self,
        repo: Optional[DatabaseRepository] = None,
        profile_registry: Optional[ProfileRegistry] = None,
    ):
        self.repo = repo or DatabaseRepository()
        self.profile_registry = profile_registry or ProfileRegistry()

    def sync_all_workers_to_db(self) -> List[Dict[str, Any]]:
        """
        Synchronizes all 8 workers into PostgreSQL `workers` table based on
        current profile authentication status in `ProfileRegistry`.
        """
        results = []
        profiles = {p.profile_id: p for p in self.profile_registry.get_all_profiles()}

        for spec in DEFAULT_WORKER_PROFILES:
            wid = spec["worker_id"]
            pid = spec["profile_id"]
            prof = profiles.get(pid)

            auth_status = prof.auth_status.value if prof else "AUTH_REQUIRED"
            email = prof.account_email if prof else None
            enabled = prof.enabled if prof else True

            # Determine initial DB status
            if not enabled:
                db_status = WorkerStatus.OFFLINE
            elif auth_status == "AUTHENTICATED":
                db_status = WorkerStatus.AVAILABLE
            else:
                # Browser-based capabilities require auth, but internal rendering can still be available if needed
                db_status = WorkerStatus.OFFLINE

            metadata = {
                "profile_id": pid,
                "role": spec["role"],
                "assigned_project": spec["assigned_project"],
                "priority": spec["priority"],
                "auth_status": auth_status,
                "account_email": email,
                "user_data_dir": prof.user_data_dir if prof else None,
                "flow_capable": prof.flow_capable if prof else True,
                "gemini_capable": prof.gemini_capable if prof else True,
            }

            try:
                row = self.repo.register_worker(
                    worker_id=wid,
                    provider=spec["provider"],
                    capabilities=spec["capabilities"],
                    status=db_status.value if isinstance(db_status, WorkerStatus) else db_status,
                    metadata=metadata,
                )
                results.append(row)
                logger.info(f"Synced worker [{wid}] -> DB ({db_status.value}, email={email})")
            except Exception as e:
                logger.error(f"Failed to sync worker [{wid}] to PostgreSQL: {e}")

        return results

    def get_worker(self, worker_id: str) -> Optional[Worker]:
        """Fetches a worker from PostgreSQL and returns a Worker domain object."""
        try:
            row = self.repo.get_worker(worker_id)
            if not row:
                return None
            return Worker(
                id=row["id"],
                provider=row["provider"],
                capabilities=row["capabilities"],
                status=WorkerStatus(row["status"]),
                current_job_id=row.get("current_job_id"),
                metadata=row.get("metadata", {}),
                updated_at=row.get("updated_at", utc_now_iso()),
            )
        except Exception as e:
            logger.error(f"Error fetching worker [{worker_id}]: {e}")
            return None

    def list_workers(
        self,
        project_id: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Worker]:
        """Lists workers from PostgreSQL filtered by criteria."""
        try:
            rows = self.repo.list_workers()
            workers: List[Worker] = []
            for r in rows:
                meta = r.get("metadata", {})
                w_status = r["status"]
                w_role = meta.get("role")
                w_proj = meta.get("assigned_project")

                if status and w_status != status:
                    continue
                if role and w_role != role:
                    continue
                if project_id and w_proj != project_id:
                    continue

                workers.append(
                    Worker(
                        id=r["id"],
                        provider=r["provider"],
                        capabilities=r["capabilities"],
                        status=WorkerStatus(w_status),
                        current_job_id=r.get("current_job_id"),
                        metadata=meta,
                        updated_at=r.get("updated_at", utc_now_iso()),
                    )
                )
            return workers
        except Exception as e:
            logger.error(f"Error listing workers: {e}")
            return []

    def get_available_worker(
        self,
        capability: str,
        project_id: Optional[str] = "proj_whop_shortform",
        exclude_ids: Optional[List[str]] = None,
    ) -> Optional[Worker]:
        """
        Dynamically discovers and selects the best available worker for a job.
        Implements replaceable worker routing:
        1. Checks capability match
        2. Checks worker is AVAILABLE with no current job
        3. For browser-dependent capabilities (REVIEW, FLOW_GENERATE), verifies AUTHENTICATED
        4. Prioritizes dedicated project workers (W1-W5 for Whop)
        5. Falls back to flexible workers (W6), then other idle workers
        """
        exclude_set = set(exclude_ids or [])
        all_workers = self.list_workers()

        candidates: List[Tuple[int, Worker]] = []
        is_browser_job = capability.strip().upper() in ("REVIEW", "GEMINI_REVIEW", "FLOW_GENERATE", "BROWSER")

        for w in all_workers:
            if w.id in exclude_set:
                continue
            if not w.is_available():
                continue
            if not w.can_handle(capability):
                continue

            meta = w.metadata
            auth_st = meta.get("auth_status", "AUTH_REQUIRED")
            if is_browser_job and auth_st != "AUTHENTICATED":
                # Cannot run browser QA/flow if not authenticated
                continue

            # Calculate priority score
            assigned_proj = meta.get("assigned_project")
            worker_role = meta.get("role")

            if project_id and assigned_proj == project_id:
                score = 100  # Primary dedicated match (e.g. W1-W5 on Whop)
            elif worker_role == "flexible_experiments":
                score = 50   # Secondary flexible worker (W6)
            else:
                score = 10   # Fallback compatible idle worker (W7/W8)

            candidates.append((score, w))

        if not candidates:
            return None

        # Sort descending by priority score
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def acquire_worker(self, worker_id: str, job_id: str):
        """Marks a worker as BUSY in PostgreSQL and assigns current_job_id."""
        self.repo.update_worker_status(worker_id, status=WorkerStatus.BUSY.value, current_job_id=job_id)
        # Also mark browser profile busy if mapped
        worker = self.get_worker(worker_id)
        if worker and "profile_id" in worker.metadata:
            pid = worker.metadata["profile_id"]
            p = self.profile_registry.get_profile(pid)
            if p:
                p.current_status = ProfileRuntimeStatus.BUSY
                self.profile_registry.save()

    def release_worker(self, worker_id: str, success: bool = True):
        """Releases worker back to AVAILABLE status in PostgreSQL."""
        self.repo.update_worker_status(worker_id, status=WorkerStatus.AVAILABLE.value, current_job_id=None)
        worker = self.get_worker(worker_id)
        if worker and "profile_id" in worker.metadata:
            pid = worker.metadata["profile_id"]
            self.profile_registry.release_profile(pid, success=success)

    def mark_profile_authenticated(self, profile_id: str, email: Optional[str] = None):
        """
        Updates authentication state in both ProfileRegistry and PostgreSQL.
        Used after manual login wizard verifies a session.
        """
        self.profile_registry.mark_authenticated(profile_id, email=email)
        # Find matching worker
        for spec in DEFAULT_WORKER_PROFILES:
            if spec["profile_id"] == profile_id:
                wid = spec["worker_id"]
                w = self.get_worker(wid)
                meta = w.metadata if w else {}
                meta["auth_status"] = "AUTHENTICATED"
                if email:
                    meta["account_email"] = email

                self.repo.register_worker(
                    worker_id=wid,
                    provider=spec["provider"],
                    capabilities=spec["capabilities"],
                    status=WorkerStatus.AVAILABLE.value,
                    metadata=meta,
                )
                logger.info(f"Updated worker [{wid}] to AUTHENTICATED in PostgreSQL (email={email})")
                break
