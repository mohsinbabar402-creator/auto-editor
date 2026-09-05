"""
Batch Production Orchestrator — Core Engine (Phase 11)

PURPOSE:
    Turn the existing Brain subsystems (source_analyzer, clip_discovery,
    context_engine, hook_engine, edit_planner, qa_engine, repair_engine,
    creative_memory) into a reliable, stateful, resumable batch production
    pipeline.

WHAT THIS FILE DOES NOT DO:
    - Clip-selection intelligence  -> brain/pipeline.py (run_creative_pipeline)
    - Rendering logic              -> RendererInterface implementations
    - QA logic                     -> brain/qa_engine.py (run_qa)
    - Repair logic                 -> brain/repair_engine.py (run_repair_cycle)
    - Memory learning logic        -> brain/creative_memory.py (CreativeMemory)

WHAT THIS FILE DOES:
    - Sequencing
    - State persistence
    - Crash recovery / resumability
    - Idempotency (stage outputs not re-computed if valid checkpoint exists)
    - Bounded retries with failure classification
    - Batch management and isolation (one clip fail does not kill the batch)
    - Concurrency control (semaphore-based, configurable limits)
    - Resource locking (per-job file locks)
    - Structured event logging
    - Progress reporting
    - Dry-run isolation (never writes to production memory in DRY_RUN mode)
    - Abstract interface boundaries for future Renderer, Publisher, Analytics

PHASE 9.5 INVARIANT PRESERVED:
    Only QA can declare a video valid. The orchestrator does NOT approve
    a clip based on render exit code, file existence, or score improvement.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import traceback
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from brain.orchestrator_models import (
    CANCELLABLE_STATES,
    RETRY_POLICIES,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    BatchJob,
    BatchResult,
    ExecutionMode,
    FailureClass,
    IdempotencyError,
    JobEvent,
    JobState,
    OrchestratorError,
    ProductionJob,
    ProductionResult,
    StateTransitionError,
    StageCheckpoint,
)


# ─── Utilities ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed(start: float) -> float:
    return round(time.monotonic() - start, 3)


def _sha256_short(*parts: str) -> str:
    """Deterministic short hash for idempotency keys."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _serialize(obj: Any) -> Any:
    """Recursively serialise dataclasses, enums, Paths to JSON-safe types."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if hasattr(obj, "value"):       # Enum
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    return obj


# ─── Abstract Interfaces ──────────────────────────────────────────────────────

@dataclass
class RenderRequest:
    """Structured input to a renderer. Decoupled from FFmpeg specifics."""
    job_id: str
    clip_id: str
    edit_plan: Any              # brain.models.EditPlan
    source_video_path: Path
    srt_path: Optional[Path]
    output_path: Path
    work_dir: Path


@dataclass
class RenderResult:
    """Structured output from a renderer."""
    success: bool
    output_path: Path
    duration_sec: float = 0.0
    renderer_name: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class RendererInterface(ABC):
    """
    Abstract renderer contract.
    The orchestrator interacts ONLY through this interface.
    Current implementation: FFmpegPodcastRenderer.
    Future: CapCutRenderer, OtherRenderer.
    """
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def render(self, request: RenderRequest) -> RenderResult:
        ...


from brain.publishing_models import PublisherInterface


class AnalyticsProviderInterface(ABC):
    """
    Abstract analytics contract.
    Phase 11 exposes the interface boundary only.
    Implementations belong to a later phase.
    DO NOT fabricate analytics.
    """
    @abstractmethod
    def fetch_performance(self, clip_id: str, account_id: str) -> Optional[Dict[str, Any]]:
        """Return None if no data available. Never fabricate."""
        ...


# ─── Persistence Layer ────────────────────────────────────────────────────────

class JobStore:
    """
    JSON-backed persistent store for production jobs.
    Atomic writes (write-to-temp, then rename) prevent partial/corrupted state.
    Thread-safe via per-job lock.
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = store_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._meta_lock = threading.Lock()

    def _job_path(self, job_id: str) -> Path:
        return self._dir / f"job_{job_id}.json"

    def _batch_path(self, batch_id: str) -> Path:
        return self._dir / f"batch_{batch_id}.json"

    def _lock_for(self, job_id: str) -> threading.Lock:
        with self._meta_lock:
            if job_id not in self._locks:
                self._locks[job_id] = threading.Lock()
            return self._locks[job_id]

    # ── Job CRUD ──────────────────────────────────────────────────────────────

    def save_job(self, job: ProductionJob) -> None:
        job.updated_at = _now_iso()
        path = self._job_path(job.job_id)
        tmp = path.with_suffix(".tmp")
        with self._lock_for(job.job_id):
            tmp.write_text(json.dumps(asdict(job), indent=2, default=str),
                           encoding="utf-8")
            os.replace(str(tmp), str(path))

    def load_job(self, job_id: str) -> Optional[ProductionJob]:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        with self._lock_for(job_id):
            data = json.loads(path.read_text(encoding="utf-8"))
        return ProductionJob(**data)

    def all_job_ids(self) -> List[str]:
        return [p.stem.replace("job_", "", 1)
                for p in self._dir.glob("job_*.json")]

    def all_jobs(self) -> List[ProductionJob]:
        return [j for j in (self.load_job(jid) for jid in self.all_job_ids())
                if j is not None]

    # ── Batch CRUD ────────────────────────────────────────────────────────────

    def save_batch(self, batch: BatchJob) -> None:
        batch.updated_at = _now_iso()
        path = self._batch_path(batch.batch_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(batch), indent=2, default=str),
                       encoding="utf-8")
        os.replace(str(tmp), str(path))

    def load_batch(self, batch_id: str) -> Optional[BatchJob]:
        path = self._batch_path(batch_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return BatchJob(**data)

    # ── Idempotency Keys ──────────────────────────────────────────────────────

    def has_valid_checkpoint(self, job_id: str, stage: str, idempotency_key: str) -> bool:
        """Return True if a completed checkpoint exists for stage+key."""
        job = self.load_job(job_id)
        if not job:
            return False
        ckpt = job.checkpoints.get(stage)
        if not ckpt:
            return False
        return ckpt.get("idempotency_key") == idempotency_key

    def get_checkpoint(self, job_id: str, stage: str) -> Optional[Dict[str, Any]]:
        job = self.load_job(job_id)
        if not job:
            return None
        return job.checkpoints.get(stage)


# ─── State Machine ─────────────────────────────────────────────────────────────

class StateMachine:
    """
    Validates and applies state transitions.
    All transitions go through here — no direct mutation allowed.
    """

    @staticmethod
    def transition(job: ProductionJob, new_state: JobState,
                   event_msg: str = "", attempt: int = 0) -> None:
        """
        Validate and apply a state transition.
        Raises StateTransitionError for invalid transitions.
        """
        current = JobState(job.state)
        allowed = VALID_TRANSITIONS.get(current, [])
        if new_state not in allowed:
            raise StateTransitionError(
                f"Invalid transition {current.value} -> {new_state.value} for job {job.job_id}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        prev = job.state
        job.state = new_state.value
        now = _now_iso()
        job.updated_at = now

        if new_state in TERMINAL_STATES:
            job.completed_at = now
        if new_state == JobState.INGESTING and not job.started_at:
            job.started_at = now

        # Append structured event
        event = {
            "timestamp": now,
            "job_id": job.job_id,
            "episode_id": job.episode_id,
            "clip_id": job.clip_id,
            "stage": new_state.value,
            "previous_state": prev,
            "new_state": new_state.value,
            "event": event_msg or f"Transitioned {prev} -> {new_state.value}",
            "attempt": attempt,
            "duration_sec": 0.0,
            "result": "",
            "error": "",
        }
        job.events.append(event)

    @staticmethod
    def can_cancel(job: ProductionJob) -> bool:
        return JobState(job.state) in CANCELLABLE_STATES

    @staticmethod
    def is_terminal(job: ProductionJob) -> bool:
        return JobState(job.state) in TERMINAL_STATES


# ─── Main Orchestrator ─────────────────────────────────────────────────────────

class BatchProductionOrchestrator:
    """
    Coordinates Brain subsystems into a reliable, resumable production pipeline.

    This class owns:
        - Sequencing
        - State management and persistence
        - Retry logic with failure classification
        - Idempotency (checkpoints prevent duplicate stage execution)
        - Batch coordination
        - Concurrency control (semaphore-based)
        - Structured event logging
        - Dry-run isolation

    This class does NOT own:
        - Clip intelligence (brain/pipeline.py)
        - Rendering logic (RendererInterface implementation)
        - QA logic (brain/qa_engine.py)
        - Repair logic (brain/repair_engine.py)
        - Memory learning (brain/creative_memory.py)

    QA IS THE SOLE AUTHORITY for clip validity.
    A clip is never declared valid solely because rendering completed.
    """

    def __init__(
        self,
        store_dir: Path,
        renderer: RendererInterface,
        memory_store_path: Optional[Path] = None,
        publisher: Optional[PublisherInterface] = None,
        analytics: Optional[AnalyticsProviderInterface] = None,
        qa_fn: Optional[Callable] = None,
        repair_fn: Optional[Callable] = None,
        creative_pipeline_fn: Optional[Callable] = None,
        source_analyzer_fn: Optional[Callable] = None,
        max_concurrent_jobs: int = 3,
        max_concurrent_renders: int = 1,
        max_concurrent_analysis: int = 2,
    ) -> None:
        self.store = JobStore(store_dir)
        self.renderer = renderer
        self.publisher = publisher
        self.analytics = analytics
        self._memory_store_path = memory_store_path

        # Inject subsystems (default to real implementations)
        if qa_fn is None:
            from brain.qa_engine import run_qa
            qa_fn = run_qa
        self._run_qa = qa_fn

        if repair_fn is None:
            from brain.repair_engine import run_repair_cycle
            repair_fn = run_repair_cycle
        self._run_repair = repair_fn

        if creative_pipeline_fn is None:
            from brain.pipeline import run_creative_pipeline
            creative_pipeline_fn = run_creative_pipeline
        self._run_creative_pipeline = creative_pipeline_fn

        if source_analyzer_fn is None:
            from brain.source_analyzer import analyze_source
            source_analyzer_fn = analyze_source
        self._run_source_analyzer = source_analyzer_fn

        # Concurrency control
        self._job_sem = threading.Semaphore(max_concurrent_jobs)
        self._render_sem = threading.Semaphore(max_concurrent_renders)
        self._analysis_sem = threading.Semaphore(max_concurrent_analysis)

        # Global cancel flag
        self._shutdown = threading.Event()

    # ── Memory Access ─────────────────────────────────────────────────────────

    def _get_memory(self, job: ProductionJob) -> Optional[Any]:
        """Return a CreativeMemory instance or None if not configured."""
        if not self._memory_store_path:
            return None
        try:
            from brain.creative_memory import CreativeMemory
            return CreativeMemory(store_path=self._memory_store_path)
        except Exception:
            return None

    def _is_production_mode(self, job: ProductionJob) -> bool:
        return job.execution_mode == ExecutionMode.PRODUCTION

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, job: ProductionJob, msg: str, attempt: int = 0) -> None:
        """Write a structured log entry to the job event list."""
        event = {
            "timestamp": _now_iso(),
            "job_id": job.job_id,
            "episode_id": job.episode_id,
            "clip_id": job.clip_id,
            "stage": job.state,
            "event": msg,
            "attempt": attempt,
        }
        job.events.append(event)
        print(f"[ORCH][{job.job_id[:8]}][{job.state}] {msg}")

    # ── State Transitions (with persistence) ──────────────────────────────────

    def _transition(self, job: ProductionJob, new_state: JobState,
                    msg: str = "", attempt: int = 0) -> None:
        StateMachine.transition(job, new_state, msg, attempt)
        self.store.save_job(job)

    # ── Idempotency ───────────────────────────────────────────────────────────

    def _make_idem_key(self, *parts: str) -> str:
        return _sha256_short(*parts)

    def _checkpoint(self, job: ProductionJob, stage: str,
                    idem_key: str, artifact: str = "",
                    metadata: Optional[Dict] = None) -> None:
        """Persist a completed stage checkpoint. Survives restarts."""
        job.checkpoints[stage] = {
            "stage": stage,
            "completed_at": _now_iso(),
            "idempotency_key": idem_key,
            "output_artifact": artifact,
            "metadata": metadata or {},
        }
        self.store.save_job(job)

    def _has_checkpoint(self, job: ProductionJob, stage: str, idem_key: str) -> bool:
        ckpt = job.checkpoints.get(stage, {})
        return ckpt.get("idempotency_key") == idem_key

    # ── Failure Handling ──────────────────────────────────────────────────────

    def _fail(self, job: ProductionJob, failure_class: str,
              message: str, stage: str = "") -> None:
        job.failure_class = failure_class
        job.failure_message = message
        job.failure_stage = stage or job.state
        self._log(job, f"FAILURE [{failure_class}]: {message}")
        self._transition(job, JobState.FAILED,
                         f"Failed at {job.failure_stage}: {message}")

    def _reject(self, job: ProductionJob, reason: str) -> None:
        job.failure_message = reason
        job.failure_stage = job.state
        self._log(job, f"REJECTED: {reason}")
        self._transition(job, JobState.REJECTED, reason)

    def _escalate(self, job: ProductionJob, reason: str,
                  escalation_data: Optional[Dict] = None) -> None:
        job.escalation = escalation_data or {}
        job.escalation["reason"] = reason
        self._log(job, f"ESCALATED: {reason}")
        self._transition(job, JobState.REPAIR_ESCALATED, reason)

    # ── Retry Logic ───────────────────────────────────────────────────────────

    def _with_retry(
        self,
        job: ProductionJob,
        stage_name: str,
        fn: Callable,
        failure_class: str = FailureClass.TRANSIENT,
        max_attempts: Optional[int] = None,
        backoff_sec: Optional[float] = None,
    ) -> Any:
        """
        Execute fn with bounded retry. Never retries indefinitely.
        Returns result on success. Raises OrchestratorError on exhaustion.
        """
        policy = RETRY_POLICIES.get(failure_class, RETRY_POLICIES[FailureClass.PERMANENT])
        attempts = max_attempts if max_attempts is not None else policy["max_attempts"]
        backoff = backoff_sec if backoff_sec is not None else policy.get("backoff_sec", 0)
        retryable = policy.get("retryable", False)

        if stage_name not in job.stage_attempts:
            job.stage_attempts[stage_name] = 0

        for attempt in range(1, attempts + 1):
            job.stage_attempts[stage_name] = attempt
            job.total_attempts += 1
            try:
                result = fn()
                return result
            except OrchestratorError:
                raise
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                self._log(job, f"[{stage_name}] Attempt {attempt}/{attempts} failed: {error_msg}", attempt)

                if not retryable or attempt >= attempts:
                    raise OrchestratorError(
                        f"Stage '{stage_name}' exhausted {attempts} attempt(s): {error_msg}"
                    ) from exc

                time.sleep(backoff)

        raise OrchestratorError(f"Stage '{stage_name}' exhausted all retries")

    # ── Pipeline Stages ───────────────────────────────────────────────────────

    def _stage_ingest(self, job: ProductionJob) -> None:
        """
        INGESTING: Validate source inputs exist and are readable.
        Does NOT parse the SRT — just confirms the source artefacts are present.
        """
        self._transition(job, JobState.INGESTING, "Ingestion started")

        idem_key = self._make_idem_key(job.srt_path, job.source_video_path)
        if self._has_checkpoint(job, "INGESTED", idem_key):
            self._log(job, "INGEST: Valid checkpoint found, skipping")
            self._transition(job, JobState.INGESTED, "Ingestion skipped (checkpoint)")
            return

        def _ingest():
            srt = Path(job.srt_path)
            if job.execution_mode != ExecutionMode.DRY_RUN:
                if not srt.exists():
                    raise OrchestratorError(f"SRT file not found: {srt}")
                if job.source_video_path and not Path(job.source_video_path).exists():
                    raise OrchestratorError(f"Source video not found: {job.source_video_path}")
            return {"srt_validated": True, "source_validated": bool(job.source_video_path)}

        result = self._with_retry(job, "ingest", _ingest,
                                  failure_class=FailureClass.INVALID_INPUT,
                                  max_attempts=1)
        job.artifacts["srt_path"] = job.srt_path
        self._checkpoint(job, "INGESTED", idem_key, artifact=job.srt_path, metadata=result)
        self._transition(job, JobState.INGESTED, "Ingestion complete")

    def _stage_analyze(self, job: ProductionJob) -> None:
        """
        ANALYZING: Run source_analyzer to parse SRT → dialogue → topics.
        Results persisted in checkpoint. Idempotent.
        """
        self._transition(job, JobState.ANALYZING, "Analysis started")

        idem_key = self._make_idem_key(job.srt_path, job.title, "ANALYZE")
        if self._has_checkpoint(job, "ANALYZED", idem_key):
            self._log(job, "ANALYZE: Valid checkpoint found, skipping")
            self._transition(job, JobState.ANALYZED, "Analysis skipped (checkpoint)")
            return

        def _analyze():
            if job.execution_mode == ExecutionMode.DRY_RUN:
                return {"simulated": True, "dialogue_segments": 50,
                        "speakers": ["Host"], "duration_min": 45.0}
            analysis = self._run_source_analyzer(
                srt_path=Path(job.srt_path),
                title=job.title,
                url=job.source_url,
                source_id=job.episode_id,
            )
            return {
                "dialogue_segments": len(analysis.dialogue_segments),
                "speakers": list(analysis.speakers),
                "duration_min": round(analysis.total_duration_sec / 60, 2),
            }

        with self._analysis_sem:
            result = self._with_retry(job, "analyze", _analyze,
                                      failure_class=FailureClass.TRANSIENT)
        self._checkpoint(job, "ANALYZED", idem_key, metadata=result)
        self._transition(job, JobState.ANALYZED, "Analysis complete")

    def _stage_discover(self, job: ProductionJob) -> Dict[str, Any]:
        """
        DISCOVERING: Run the full creative pipeline (source_analyzer →
        clip_discovery → context_engine → hook_engine → edit_planner).
        Returns the selected CreativeDecisionRecord for this job's clip_id.
        """
        self._transition(job, JobState.DISCOVERING, "Discovery started")

        idem_key = self._make_idem_key(job.srt_path, job.title, job.clip_id, "DISCOVER")
        if self._has_checkpoint(job, "DISCOVERED", idem_key):
            self._log(job, "DISCOVER: Valid checkpoint found, loading")
            ckpt = job.checkpoints["DISCOVERED"]
            self._transition(job, JobState.DISCOVERED, "Discovery skipped (checkpoint)")
            return ckpt.get("metadata", {})

        def _discover():
            if job.execution_mode == ExecutionMode.DRY_RUN:
                return {"simulated": True, "candidates": 5, "selected": 1}
            records = self._run_creative_pipeline(
                srt_path=Path(job.srt_path),
                title=job.title,
                url=job.source_url,
                source_id=job.episode_id,
                top_n=10,
                min_score=4.0,
            )
            return {
                "record_count": len(records),
                "candidate_ids": [r.candidate.candidate_id for r in records],
            }

        with self._analysis_sem:
            result = self._with_retry(job, "discover", _discover,
                                      failure_class=FailureClass.TRANSIENT)

        if not result.get("simulated") and result.get("record_count", 0) == 0:
            self._reject(job, "Discovery found no viable candidates above threshold")
            return result

        self._checkpoint(job, "DISCOVERED", idem_key, metadata=result)
        self._transition(job, JobState.DISCOVERED, "Discovery complete")
        return result

    def _stage_plan(self, job: ProductionJob, edit_plan: Any) -> None:
        """
        PLANNING: Consult Creative Memory → confirm EditPlan.
        Memory is consulted as advisory context (not authoritative).
        """
        self._transition(job, JobState.PLANNING, "Planning started")

        plan_hash = _sha256_short(
            str(getattr(edit_plan, "candidate_id", "")),
            str(getattr(edit_plan, "target_duration_sec", "")),
            str(getattr(edit_plan, "ending_strategy", "")),
        )
        idem_key = self._make_idem_key(job.clip_id, plan_hash, "PLAN")

        if self._has_checkpoint(job, "PLANNED", idem_key):
            self._log(job, "PLAN: Valid checkpoint found, skipping")
            self._transition(job, JobState.PLANNED, "Planning skipped (checkpoint)")
            return

        # Query Creative Memory (advisory only — never overrides EditPlan)
        memory_evidence: List[str] = []
        memory = self._get_memory(job)
        if memory and edit_plan is not None:
            try:
                is_valid_training = self._is_production_mode(job)
                retrieved = memory.retrieve_for_edit_plan(
                    edit_plan,
                    show_id=job.show_id,
                    record_influence=is_valid_training,
                )
                memory_evidence = [r.memory.memory_id for r in retrieved]
                self._log(job, f"PLAN: Memory consulted — {len(memory_evidence)} relevant memories")
            except Exception as e:
                self._log(job, f"PLAN: Memory query failed (non-critical): {e}")

        job.artifacts["edit_plan_candidate_id"] = getattr(edit_plan, "candidate_id", "")
        self._checkpoint(job, "PLANNED", idem_key,
                         metadata={"memory_consulted": memory_evidence,
                                   "edit_plan_id": getattr(edit_plan, "candidate_id", "")})
        self._transition(job, JobState.PLANNED, "Planning complete")

    def _stage_render(self, job: ProductionJob, edit_plan: Any,
                      output_dir: Path) -> Path:
        """
        RENDERING: Delegate to RendererInterface.
        Output is an artifact path. Success requires QA — not just file existence.
        """
        self._transition(job, JobState.RENDERING, "Rendering started")

        output_path = output_dir / f"{job.clip_id}_render.mp4"
        render_hash = _sha256_short(
            job.clip_id,
            str(getattr(edit_plan, "target_duration_sec", "")),
            str(getattr(edit_plan, "body_start_sec", "")),
            str(getattr(edit_plan, "body_end_sec", "")),
        )
        idem_key = self._make_idem_key(job.clip_id, render_hash, "RENDER")

        if self._has_checkpoint(job, "RENDERED", idem_key):
            ckpt = job.checkpoints["RENDERED"]
            cached_path = Path(ckpt.get("output_artifact", ""))
            if cached_path.exists():
                self._log(job, f"RENDER: Valid checkpoint found — reusing {cached_path.name}")
                job.artifacts["render_output"] = str(cached_path)
                self._transition(job, JobState.RENDERED, "Rendering skipped (checkpoint)")
                return cached_path
            else:
                self._log(job, "RENDER: Checkpoint artifact missing — re-rendering")

        def _render():
            if job.execution_mode == ExecutionMode.DRY_RUN:
                # Create a minimal placeholder (0-byte) for dry-run — not a valid video
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.touch()
                return RenderResult(
                    success=True, output_path=output_path,
                    renderer_name="DRY_RUN", duration_sec=0.0
                )

            req = RenderRequest(
                job_id=job.job_id,
                clip_id=job.clip_id,
                edit_plan=edit_plan,
                source_video_path=Path(job.source_video_path),
                srt_path=Path(job.srt_path) if job.srt_path else None,
                output_path=output_path,
                work_dir=output_dir / "work",
            )
            with self._render_sem:
                result = self.renderer.render(req)

            if not result.success:
                raise OrchestratorError(f"Renderer {self.renderer.name} failed: {result.error}")
            return result

        result = self._with_retry(job, "render", _render,
                                  failure_class=FailureClass.TRANSIENT, max_attempts=2)
        render_path = result.output_path if hasattr(result, "output_path") else output_path
        job.artifacts["render_output"] = str(render_path)
        self._checkpoint(job, "RENDERED", idem_key, artifact=str(render_path),
                         metadata={"renderer": getattr(result, "renderer_name", "unknown"),
                                   "duration_sec": getattr(result, "duration_sec", 0.0)})
        self._transition(job, JobState.RENDERED, "Rendering complete")
        return render_path

    def _stage_qa(self, job: ProductionJob, render_path: Path,
                  edit_plan: Any, srt_path: Optional[Path] = None) -> Any:
        """
        QA_PENDING: Run the adversarial QA engine.
        The QA engine is the SOLE AUTHORITY for clip validity.
        Render exit code, file existence, score improvement — none of these
        determine validity. Only QA does.
        """
        self._transition(job, JobState.QA_PENDING, "QA started")

        if job.execution_mode == ExecutionMode.DRY_RUN:
            self._log(job, "QA: DRY_RUN — simulating APPROVED")
            fake_qa = _make_simulated_qa_result(edit_plan, passed=True, score=95.0)
            self._transition(job, JobState.APPROVED, "QA simulated — APPROVED")
            job.artifacts["qa_report"] = "simulated"
            return fake_qa

        def _qa():
            return self._run_qa(render_path, edit_plan, srt_path)

        qa_result = self._with_retry(job, "qa", _qa, failure_class=FailureClass.TRANSIENT)
        job.artifacts["qa_report"] = json.dumps(
            _serialize_qa(qa_result), default=str)

        if qa_result.recommended_action == "approve":
            self._log(job, f"QA: APPROVED — score {qa_result.score:.1f}/100")
            self._transition(job, JobState.APPROVED, f"QA approved: {qa_result.score:.1f}/100")
        else:
            hard_fail_summary = "; ".join(qa_result.hard_fails[:3])
            self._log(job, f"QA: FAILED — {hard_fail_summary}")
            self._transition(job, JobState.QA_FAILED,
                             f"QA failed: {hard_fail_summary}")

        return qa_result

    def _stage_repair(self, job: ProductionJob, render_path: Path,
                      edit_plan: Any, qa_result: Any,
                      work_dir: Path, srt_path: Optional[Path] = None) -> tuple:
        """
        REPAIRING: Delegate to repair engine (Phase 9.5).
        The repair engine's own safety invariants are preserved here.
        The orchestrator does not alter repair decisions.
        """
        self._transition(job, JobState.REPAIRING, "Repair started")

        if job.execution_mode == ExecutionMode.DRY_RUN:
            self._log(job, "REPAIR: DRY_RUN — simulating approval")
            fake_qa = _make_simulated_qa_result(edit_plan, passed=True, score=92.0)
            self._transition(job, JobState.FINAL_QA, "Repair simulated")
            self._transition(job, JobState.APPROVED, "Final QA simulated — APPROVED")
            return render_path, fake_qa, {"outcome": "APPROVED", "simulated": True}

        repair_dir = work_dir / "repair"
        repair_dir.mkdir(parents=True, exist_ok=True)
        audit_log = repair_dir / f"repair_audit_{job.clip_id}.json"

        def _repair():
            return self._run_repair(
                video_path=render_path,
                edit_plan=edit_plan,
                qa_result=qa_result,
                srt_path=srt_path,
                work_dir=repair_dir,
                audit_log_path=audit_log,
                re_qa_fn=self._run_qa,
            )

        repair_result = self._with_retry(job, "repair", _repair,
                                         failure_class=FailureClass.TRANSIENT, max_attempts=1)

        outcome = repair_result.get("outcome", "REJECTED")
        final_video = repair_result.get("final_video_path", render_path)
        final_qa = repair_result.get("final_qa_result", qa_result)

        job.artifacts["repair_output"] = str(final_video)
        job.artifacts["repair_audit"] = str(audit_log)

        # Store repair summary
        repair_summary = {
            "outcome": outcome,
            "attempts": repair_result.get("attempts", 0),
            "source_rerender_issues": repair_result.get("audit", {}).get(
                "source_rerender_required_for", []
            ),
        }

        if outcome == "APPROVED":
            self._transition(job, JobState.FINAL_QA, f"Repair complete: {outcome}")
            self._log(job, f"REPAIR: APPROVED — score {final_qa.score:.1f}/100")
            self._transition(job, JobState.APPROVED, "Final QA approved after repair")
        elif outcome == "SOURCE_RERENDER_REQUIRED":
            self._escalate(job, "SOURCE_RERENDER_REQUIRED",
                           escalation_data=repair_summary)
            self._transition(job, JobState.REJECTED,
                             "Escalated: source re-render required")
        else:
            self._transition(job, JobState.FINAL_QA, f"Repair complete: {outcome}")
            self._reject(job, f"Final QA rejected after repair: {outcome}")

        return final_video, final_qa, repair_summary

    def _stage_output(self, job: ProductionJob, final_video: Path) -> None:
        """
        OUTPUT_READY: Hand off to publisher interface boundary.
        The publisher is optional. If not configured, job completes without publishing.
        """
        self._transition(job, JobState.OUTPUT_READY, "Output ready")
        job.artifacts["final_output"] = str(final_video)

        if self.publisher and job.execution_mode == ExecutionMode.PRODUCTION:
            try:
                pub_result = self.publisher.publish(
                    final_video,
                    {"clip_id": job.clip_id, "account_id": job.account_id,
                     "platform": job.platform}
                )
                self._log(job, f"OUTPUT: Published via {self.publisher.__class__.__name__}")
                job.artifacts["publish_result"] = json.dumps(pub_result, default=str)
            except Exception as e:
                self._log(job, f"OUTPUT: Publisher error (non-fatal): {e}")

    def _stage_memory_update(self, job: ProductionJob, edit_plan: Any,
                             qa_result: Any) -> List[str]:
        """
        MEMORY_PENDING → COMPLETED: Write production evidence to Creative Memory.
        Dry-run and test modes are quarantined (is_valid_training=False).
        Performance data is never fabricated.
        """
        self._transition(job, JobState.MEMORY_PENDING, "Memory update started")
        evidence_ids: List[str] = []

        memory = self._get_memory(job)
        if memory is None:
            self._log(job, "MEMORY: No memory store configured, skipping")
            return evidence_ids

        is_production = self._is_production_mode(job)
        is_valid = is_production  # TEST/DRY_RUN/BENCHMARK are never valid training data

        try:
            if job.execution_mode != ExecutionMode.DRY_RUN:
                # Record editorial decision
                ev_ids = memory.record_editorial_decision(
                    edit_plan=edit_plan,
                    reasoning=f"Orchestrated production job {job.job_id}",
                    show_id=job.show_id,
                    account_id=job.account_id,
                    platform=job.platform,
                    is_valid_training=is_valid,
                )
                evidence_ids.extend(ev_ids or [])

                # Record QA outcome
                memory.record_qa_outcome(
                    clip_id=job.clip_id,
                    qa_result=qa_result,
                    edit_plan=edit_plan,
                    is_valid_training=is_valid,
                )

                # Query analytics (never fabricate)
                if self.analytics and is_production:
                    try:
                        perf_data = self.analytics.fetch_performance(
                            job.clip_id, job.account_id
                        )
                        if perf_data:  # Only update if data actually exists
                            memory.record_performance(
                                clip_id=job.clip_id,
                                performance_data=perf_data,
                                account_id=job.account_id,
                            )
                    except Exception as e:
                        self._log(job, f"MEMORY: Analytics fetch failed (non-critical): {e}")

            self._log(job, f"MEMORY: Updated with {len(evidence_ids)} evidence IDs")

        except Exception as e:
            # Memory update failure is logged but must not block completion
            self._log(job, f"MEMORY: Update failed (non-critical): {e}")

        return evidence_ids

    # ── Job Execution ─────────────────────────────────────────────────────────

    def _execute_job(self, job: ProductionJob, edit_plan: Any,
                     output_dir: Path) -> ProductionResult:
        """
        Run a single production job through the full state machine.
        Resumable: skips already-completed stages via checkpoints.
        """
        start = time.monotonic()
        stages_completed: List[str] = []
        memory_evidence: List[str] = []
        final_qa = None
        final_video = None
        repair_summary = None
        srt = Path(job.srt_path) if job.srt_path else None

        try:
            # ─ INGEST (idempotent) ────────────────────────────────────────────
            if not StateMachine.is_terminal(job) and JobState(job.state) == JobState.QUEUED:
                self._stage_ingest(job)
                stages_completed.append("INGESTED")

            # ─ ANALYZE (idempotent) ───────────────────────────────────────────
            if not StateMachine.is_terminal(job) and JobState(job.state) == JobState.INGESTED:
                self._stage_analyze(job)
                stages_completed.append("ANALYZED")

            # ─ DISCOVER (idempotent) ──────────────────────────────────────────
            if not StateMachine.is_terminal(job) and JobState(job.state) == JobState.ANALYZED:
                self._stage_discover(job)
                stages_completed.append("DISCOVERED")

            # ─ PLAN (idempotent) ──────────────────────────────────────────────
            if not StateMachine.is_terminal(job) and JobState(job.state) == JobState.DISCOVERED:
                self._stage_plan(job, edit_plan)
                stages_completed.append("PLANNED")

            # ─ RENDER (idempotent) ────────────────────────────────────────────
            render_path = None
            if not StateMachine.is_terminal(job) and JobState(job.state) == JobState.PLANNED:
                if job.cancellation_requested:
                    self._transition(job, JobState.CANCELLED, "Cancelled before render")
                else:
                    render_path = self._stage_render(job, edit_plan, output_dir)
                    stages_completed.append("RENDERED")

            # Load render path from checkpoint if resuming after crash
            if render_path is None and not StateMachine.is_terminal(job):
                ckpt = job.checkpoints.get("RENDERED", {})
                if ckpt.get("output_artifact"):
                    render_path = Path(ckpt["output_artifact"])

            # ─ QA ─────────────────────────────────────────────────────────────
            if (not StateMachine.is_terminal(job)
                    and JobState(job.state) in (JobState.RENDERED, JobState.QA_PENDING)
                    and render_path is not None):
                final_qa = self._stage_qa(job, render_path, edit_plan, srt)
                stages_completed.append("QA_COMPLETE")

            # ─ REPAIR ─────────────────────────────────────────────────────────
            if (not StateMachine.is_terminal(job)
                    and JobState(job.state) in (JobState.QA_FAILED, JobState.REPAIRING)
                    and render_path is not None and final_qa is not None):
                final_video, final_qa, repair_summary = self._stage_repair(
                    job, render_path, edit_plan, final_qa, output_dir, srt
                )
                stages_completed.append("REPAIR_COMPLETE")

            # ─ OUTPUT ─────────────────────────────────────────────────────────
            if (not StateMachine.is_terminal(job)
                    and JobState(job.state) == JobState.APPROVED):
                approved_video = final_video or render_path or Path("")
                self._stage_output(job, approved_video)
                final_video = approved_video
                stages_completed.append("OUTPUT_READY")

            # ─ MEMORY UPDATE ──────────────────────────────────────────────────
            if (not StateMachine.is_terminal(job)
                    and JobState(job.state) == JobState.OUTPUT_READY
                    and final_qa is not None and edit_plan is not None):
                memory_evidence = self._stage_memory_update(job, edit_plan, final_qa)
                stages_completed.append("MEMORY_UPDATED")
                self._transition(job, JobState.COMPLETED, "Production complete")

            elif not StateMachine.is_terminal(job):
                # Something left it in a non-terminal state — fail safely
                self._fail(job, FailureClass.INTERNAL_ERROR,
                           f"Unexpected terminal state: {job.state}", job.state)

        except StateTransitionError as e:
            self._fail(job, FailureClass.INTERNAL_ERROR, str(e))
        except OrchestratorError as e:
            self._fail(job, FailureClass.PERMANENT, str(e))
        except Exception as e:
            tb = traceback.format_exc()
            self._fail(job, FailureClass.INTERNAL_ERROR, f"{type(e).__name__}: {e}\n{tb[:500]}")

        # Final save
        self.store.save_job(job)

        return ProductionResult(
            job_id=job.job_id,
            clip_id=job.clip_id,
            status=job.state,
            final_artifact=str(final_video) if final_video else "",
            qa_result=_serialize_qa(final_qa) if final_qa else None,
            repair_summary=repair_summary,
            escalation=job.escalation if job.escalation else None,
            duration_sec=_elapsed(start),
            stages_completed=stages_completed,
            memory_updates=memory_evidence,
            errors=[e for e in [job.failure_message] if e],
            execution_mode=job.execution_mode,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def submit_job(
        self,
        episode_id: str,
        clip_id: str,
        account_id: str,
        platform: str = "youtube_shorts",
        srt_path: str = "",
        source_video_path: str = "",
        title: str = "",
        source_url: str = "",
        show_id: str = "",
        execution_mode: str = ExecutionMode.PRODUCTION,
        batch_id: Optional[str] = None,
        format: str = "ambient_blur_9_16",
    ) -> str:
        """
        Queue a new production job. Returns job_id.
        Idempotent: if a job with the same clip_id already exists in a terminal
        successful state, the existing job_id is returned.
        """
        # Check for existing successful job for this clip_id (idempotency)
        for existing in self.store.all_jobs():
            if (existing.clip_id == clip_id
                    and existing.episode_id == episode_id
                    and existing.state == JobState.COMPLETED):
                self._log(existing, "SUBMIT: Duplicate submission — returning existing COMPLETED job")
                return existing.job_id

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = ProductionJob(
            job_id=job_id,
            episode_id=episode_id,
            clip_id=clip_id,
            account_id=account_id,
            platform=platform,
            format=format,
            execution_mode=execution_mode,
            srt_path=srt_path,
            source_video_path=source_video_path,
            title=title,
            source_url=source_url,
            show_id=show_id,
            state=JobState.QUEUED,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self.store.save_job(job)
        if batch_id:
            batch = self.store.load_batch(batch_id)
            if batch and job_id not in batch.job_ids:
                batch.job_ids.append(job_id)
                batch.total += 1
                batch.queued += 1
                self.store.save_batch(batch)
        return job_id

    def run_job(
        self,
        job_id: str,
        edit_plan: Any,
        output_dir: Path,
    ) -> ProductionResult:
        """
        Execute a single production job (blocking).
        Resumable: if job already has valid checkpoints, stages are skipped.
        """
        job = self.store.load_job(job_id)
        if job is None:
            raise OrchestratorError(f"Job {job_id} not found")

        if StateMachine.is_terminal(job):
            self._log(job, f"RUN: Job already terminal ({job.state}), returning cached result")
            return ProductionResult(
                job_id=job.job_id, clip_id=job.clip_id, status=job.state,
                final_artifact=job.artifacts.get("final_output", ""),
                stages_completed=list(job.checkpoints.keys()),
            )

        with self._job_sem:
            return self._execute_job(job, edit_plan, output_dir)

    def cancel_job(self, job_id: str) -> bool:
        """
        Request cooperative cancellation. Returns True if cancellation was accepted.
        Already-completed stages are preserved.
        QUEUED jobs are immediately cancelled.
        """
        job = self.store.load_job(job_id)
        if job is None:
            return False
        if StateMachine.is_terminal(job):
            return False

        if JobState(job.state) == JobState.QUEUED:
            self._transition(job, JobState.CANCELLED, "Cancelled from QUEUED state")
            self.store.save_job(job)
            return True

        if StateMachine.can_cancel(job):
            job.cancellation_requested = True
            self.store.save_job(job)
            return True

        return False

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Query current job status. Returns structured dict or None."""
        job = self.store.load_job(job_id)
        if job is None:
            return None
        stages_done = list(job.checkpoints.keys())
        total_stages = 10  # Approximate pipeline depth
        return {
            "job_id": job.job_id,
            "clip_id": job.clip_id,
            "stage": job.state,
            "progress": f"{len(stages_done)}/{total_stages} stages",
            "status": "TERMINAL" if StateMachine.is_terminal(job) else "RUNNING",
            "started_at": job.started_at,
            "updated_at": job.updated_at,
            "failure_class": job.failure_class,
            "failure_message": job.failure_message,
            "artifacts": job.artifacts,
            "escalation": job.escalation,
        }

    def submit_batch(
        self,
        account_id: str,
        platform: str = "youtube_shorts",
        execution_mode: str = ExecutionMode.PRODUCTION,
        description: str = "",
    ) -> str:
        """Create a new batch container. Returns batch_id."""
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        batch = BatchJob(
            batch_id=batch_id,
            account_id=account_id,
            platform=platform,
            execution_mode=execution_mode,
            description=description,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self.store.save_batch(batch)
        return batch_id

    def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Compute live batch progress by reading current job states."""
        batch = self.store.load_batch(batch_id)
        if batch is None:
            return None

        counts = {s.value: 0 for s in JobState}
        for jid in batch.job_ids:
            job = self.store.load_job(jid)
            if job:
                counts[job.state] = counts.get(job.state, 0) + 1

        return {
            "batch_id": batch_id,
            "total": len(batch.job_ids),
            "queued": counts.get(JobState.QUEUED, 0),
            "running": sum(counts.get(s.value, 0) for s in [
                JobState.INGESTING, JobState.ANALYZING, JobState.DISCOVERING,
                JobState.PLANNING, JobState.RENDERING, JobState.QA_PENDING,
                JobState.REPAIRING, JobState.FINAL_QA, JobState.OUTPUT_READY,
            ]),
            "completed": counts.get(JobState.COMPLETED, 0),
            "failed": counts.get(JobState.FAILED, 0),
            "rejected": counts.get(JobState.REJECTED, 0),
            "escalated": counts.get(JobState.REPAIR_ESCALATED, 0),
            "cancelled": counts.get(JobState.CANCELLED, 0),
        }

    def run_batch(
        self,
        batch_id: str,
        job_edit_plans: Dict[str, Any],   # job_id -> EditPlan
        output_dir: Path,
        max_workers: Optional[int] = None,
    ) -> BatchResult:
        """
        Execute all jobs in a batch.
        A single job failure does not stop the batch.
        Each job runs independently with its own error boundary.
        """
        batch = self.store.load_batch(batch_id)
        if batch is None:
            raise OrchestratorError(f"Batch {batch_id} not found")

        start = time.monotonic()
        results: List[ProductionResult] = []

        if max_workers and max_workers > 1:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {}
                for jid in batch.job_ids:
                    ep = job_edit_plans.get(jid)
                    if ep is None:
                        continue
                    if self._shutdown.is_set():
                        break
                    f = pool.submit(self.run_job, jid, ep, output_dir)
                    futures[f] = jid
                for f in concurrent.futures.as_completed(futures):
                    try:
                        results.append(f.result())
                    except Exception as e:
                        jid = futures[f]
                        results.append(ProductionResult(
                            job_id=jid, clip_id=jid, status=JobState.FAILED,
                            errors=[str(e)]
                        ))
        else:
            for jid in batch.job_ids:
                ep = job_edit_plans.get(jid)
                if ep is None:
                    continue
                if self._shutdown.is_set():
                    break
                try:
                    results.append(self.run_job(jid, ep, output_dir))
                except Exception as e:
                    results.append(ProductionResult(
                        job_id=jid, clip_id=jid, status=JobState.FAILED,
                        errors=[str(e)]
                    ))

        # Tally results
        br = BatchResult(
            batch_id=batch_id,
            total=len(results),
            completed=sum(1 for r in results if r.status == JobState.COMPLETED),
            failed=sum(1 for r in results if r.status == JobState.FAILED),
            rejected=sum(1 for r in results if r.status == JobState.REJECTED),
            escalated=sum(1 for r in results if r.status == JobState.REPAIR_ESCALATED),
            cancelled=sum(1 for r in results if r.status == JobState.CANCELLED),
            duration_sec=_elapsed(start),
            job_results=results,
        )

        # Persist final batch state
        batch.completed = br.completed
        batch.failed = br.failed
        batch.rejected = br.rejected
        batch.escalated = br.escalated
        batch.cancelled = br.cancelled
        batch.completed_at = _now_iso()
        self.store.save_batch(batch)

        return br

    def shutdown(self) -> None:
        """Signal all running batch loops to stop after completing current jobs."""
        self._shutdown.set()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _serialize_qa(qa_result: Any) -> Optional[Dict[str, Any]]:
    """Convert QAResult to a JSON-serialisable dict."""
    if qa_result is None:
        return None
    try:
        from dataclasses import asdict
        return asdict(qa_result)
    except Exception:
        return {"passed": getattr(qa_result, "passed", False),
                "score": getattr(qa_result, "score", 0.0),
                "hard_fails": getattr(qa_result, "hard_fails", []),
                "recommended_action": getattr(qa_result, "recommended_action", "reject")}


def _make_simulated_qa_result(edit_plan: Any, passed: bool, score: float) -> Any:
    """Create a minimal simulated QAResult for dry-run and testing."""
    from brain.models import QAResult
    return QAResult(
        render_id=getattr(edit_plan, "candidate_id", "simulated"),
        passed=passed,
        score=score,
        hard_fails=[] if passed else ["Simulated failure"],
        warnings=[],
        checks_run=[],
        recommended_action="approve" if passed else "reject",
        confidence=1.0,
    )
