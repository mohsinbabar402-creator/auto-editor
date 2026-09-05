"""
Persistent Knowledge Base & Self-Improvement Layer — Repository Engine (Phase 17)

PURPOSE:
    Provides model-independent persistence, pattern induction, confidence calculation,
    experiment tracking, and structured knowledge retrieval for AI planning.

INVARIANTS:
    - THE DATABASE IS THE SOURCE OF TRUTH; THE LLM IS A REPLACEABLE REASONING AGENT.
    - Zero credentials, OAuth secrets, or tokens stored in knowledge records.
    - Idempotency on learning event ingestion (duplicate source events ignored).
    - Mathematically grounded confidence calculations prevent one-hit wonder activation.
    - Multi-tenant / scope isolation strictly enforced.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from brain.analytics_models import AnalyticsSnapshot, PerformanceMetrics
from brain.knowledge_database import KnowledgeDatabase
from brain.knowledge_models import (
    CreativeDecision,
    ExperimentRecord,
    ExperimentStatus,
    KnowledgePattern,
    KnowledgeRetrievalContext,
    KnowledgeScope,
    LearningEvent,
    LearningEventType,
    ModelRun,
    PatternStatus,
    _now_iso,
)


def _calculate_confidence(success_count: int, failure_count: int) -> float:
    """
    Laplace smoothed Bayesian confidence with sample size dampener:
    Confidence = ((Success + 1) / (Total + 2)) * (1 - 1 / sqrt(Total + 1))
    Prevents small samples (e.g. 1 success / 1 trial) from falsely claiming 100% confidence.
    """
    total = success_count + failure_count
    if total <= 0:
        return 0.0

    raw_rate = (success_count + 1.0) / (total + 2.0)
    sample_dampener = max(0.0, 1.0 - (1.0 / math.sqrt(total + 1.0)))
    return round(raw_rate * sample_dampener, 3)


class KnowledgeRepository:
    """
    Canonical interface for model-independent persistent knowledge,
    decision tracing, pattern induction, and experiment tracking.
    """

    def __init__(self, db: Optional[KnowledgeDatabase] = None) -> None:
        self.db = db or KnowledgeDatabase()

    # ─── Model Execution Registry ─────────────────────────────────────────────

    def record_model_run(
        self,
        model_provider: str,
        model_name: str,
        model_version: str = "v1",
        prompt_version: str = "v1",
        task_type: str = "hook_selection",
        input_reference: str = "",
        output_reference: str = "",
        latency_ms: int = 0,
        token_usage: Optional[Dict[str, int]] = None,
        success: bool = True,
        run_id: str = "",
    ) -> ModelRun:
        rid = run_id or f"run_{uuid.uuid4().hex[:12]}"
        run = ModelRun(
            id=rid,
            model_provider=model_provider,
            model_name=model_name,
            model_version=model_version,
            prompt_version=prompt_version,
            task_type=task_type,
            input_reference=input_reference,
            output_reference=output_reference,
            latency_ms=latency_ms,
            token_usage=token_usage or {},
            success=success,
        )
        with self.db.transaction() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO model_runs (
                    id, model_provider, model_name, model_version, prompt_version,
                    task_type, input_reference, output_reference, latency_ms,
                    token_usage_json, success, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id, run.model_provider, run.model_name, run.model_version,
                    run.prompt_version, run.task_type, run.input_reference,
                    run.output_reference, run.latency_ms, json.dumps(run.token_usage),
                    1 if run.success else 0, run.created_at,
                )
            )
        return run

    # ─── Creative Decision Records ────────────────────────────────────────────

    def record_creative_decision(
        self,
        project_id: str,
        episode_id: str,
        clip_id: str,
        decision_type: str,
        decision_payload: Dict[str, Any],
        reasoning_summary: str,
        model_run_id: str = "",
        memory_context_ids: Optional[List[str]] = None,
        decision_id: str = "",
    ) -> CreativeDecision:
        did = decision_id or f"dec_{uuid.uuid4().hex[:12]}"
        decision = CreativeDecision(
            id=did,
            project_id=project_id,
            episode_id=episode_id,
            clip_id=clip_id,
            decision_type=decision_type,
            decision_payload=decision_payload,
            reasoning_summary=reasoning_summary,
            model_run_id=model_run_id,
            memory_context_ids=memory_context_ids or [],
        )
        with self.db.transaction() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO creative_decisions (
                    id, project_id, episode_id, clip_id, decision_type,
                    decision_payload_json, reasoning_summary, model_run_id,
                    memory_context_ids_json, version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.id, decision.project_id, decision.episode_id,
                    decision.clip_id, decision.decision_type,
                    json.dumps(decision.decision_payload), decision.reasoning_summary,
                    decision.model_run_id or None, json.dumps(decision.memory_context_ids),
                    decision.version, decision.created_at,
                )
            )
        return decision

    def get_decisions_for_clip(self, project_id: str, clip_id: str) -> List[CreativeDecision]:
        rows = self.db.execute(
            "SELECT * FROM creative_decisions WHERE project_id = ? AND clip_id = ? ORDER BY created_at ASC",
            (project_id, clip_id)
        )
        results = []
        for r in rows:
            results.append(CreativeDecision(
                id=r["id"],
                project_id=r["project_id"],
                episode_id=r["episode_id"],
                clip_id=r["clip_id"],
                decision_type=r["decision_type"],
                decision_payload=json.loads(r["decision_payload_json"]),
                reasoning_summary=r["reasoning_summary"],
                model_run_id=r["model_run_id"] or "",
                memory_context_ids=json.loads(r["memory_context_ids_json"] or "[]"),
                version=r["version"],
                created_at=r["created_at"],
            ))
        return results

    # ─── Learning Events & Ingestion ──────────────────────────────────────────

    def record_learning_event(
        self,
        event_type: str,
        source_type: str,
        source_id: str,
        project_id: str = "default",
        account_id: str = "default",
        payload: Optional[Dict[str, Any]] = None,
        confidence_weight: float = 1.0,
        event_id: str = "",
    ) -> Tuple[LearningEvent, bool]:
        """
        Idempotently records a learning event.
        Returns (LearningEvent, was_inserted: bool).
        """
        eid = event_id or f"evt_{hashlib.sha256(f'{event_type}:{source_id}:{project_id}'.encode()).hexdigest()[:16]}"

        # Check existing
        existing = self.db.execute_single("SELECT id FROM learning_events WHERE id = ?", (eid,))
        if existing:
            row = self.db.execute_single("SELECT * FROM learning_events WHERE id = ?", (eid,))
            evt = LearningEvent(
                id=row["id"],
                event_type=row["event_type"],
                source_type=row["source_type"],
                source_id=row["source_id"],
                project_id=row["project_id"],
                account_id=row["account_id"],
                payload=json.loads(row["payload_json"]),
                confidence_weight=row["confidence_weight"],
                created_at=row["created_at"],
            )
            return evt, False

        event = LearningEvent(
            id=eid,
            event_type=event_type,
            source_type=source_type,
            source_id=source_id,
            project_id=project_id,
            account_id=account_id,
            payload=payload or {},
            confidence_weight=confidence_weight,
        )

        with self.db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO learning_events (
                    id, event_type, source_type, source_id, project_id,
                    account_id, payload_json, confidence_weight, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id, event.event_type, event.source_type, event.source_id,
                    event.project_id, event.account_id, json.dumps(event.payload),
                    event.confidence_weight, event.created_at,
                )
            )

        # Trigger pattern induction
        self._induct_patterns_from_event(event)
        return event, True

    def ingest_analytics_outcome(self, snapshot: AnalyticsSnapshot, project_id: str = "default") -> List[LearningEvent]:
        """
        Translates real platform performance metrics into structured learning events.
        """
        events = []
        metrics = snapshot.metrics
        source_type = "SYNTHETIC" if metrics.is_synthetic else "PRODUCTION"

        # 1. High retention outcome (> 75% average percentage viewed or > 80% 5s retention)
        pct_viewed = metrics.average_percentage_viewed
        hook_5s = 0.0
        for pt in metrics.retention_curve:
            if pt.get("time_sec") == 5.0:
                hook_5s = pt.get("retention_pct", 0.0)

        is_high_performer = (pct_viewed >= 75.0) or (hook_5s >= 80.0)
        is_low_performer = (pct_viewed < 40.0) and (metrics.views >= 500)

        evt_type = (
            LearningEventType.HOOK_PERFORMED_WELL.value
            if is_high_performer
            else (
                LearningEventType.HOOK_PERFORMED_POORLY.value
                if is_low_performer
                else LearningEventType.ANALYTICS_RECEIVED.value
            )
        )

        evt, _ = self.record_learning_event(
            event_type=evt_type,
            source_type=source_type,
            source_id=snapshot.clip_id or snapshot.external_id,
            project_id=project_id,
            account_id=metrics.account_id,
            payload={
                "external_id": snapshot.external_id,
                "views": metrics.views,
                "average_percentage_viewed": pct_viewed,
                "hook_retention_5s": hook_5s,
                "shares": metrics.shares,
                "likes": metrics.likes,
            },
        )
        events.append(evt)
        return events

    # ─── Pattern Induction & Confidence Lifecycle ─────────────────────────────

    def _induct_patterns_from_event(self, event: LearningEvent) -> None:
        """
        Internal reactive evaluator that updates or proposes knowledge patterns.
        """
        # Look up creative decisions associated with this clip
        decisions = self.get_decisions_for_clip(event.project_id, event.source_id)
        for dec in decisions:
            hook_type = dec.decision_payload.get("hook_type")
            if not hook_type:
                continue

            pattern_id = f"pat_hook_{hook_type}_{event.project_id}"
            existing = self.get_pattern(pattern_id)

            is_success = event.event_type in (
                LearningEventType.HOOK_PERFORMED_WELL.value,
                LearningEventType.PUBLISH_SUCCESS.value,
            )
            is_failure = event.event_type in (
                LearningEventType.HOOK_PERFORMED_POORLY.value,
                LearningEventType.QA_FAILED.value,
                LearningEventType.PUBLISH_REJECTED.value,
            )

            if not is_success and not is_failure:
                continue

            if existing:
                succ = existing.success_count + (1 if is_success else 0)
                fail = existing.failure_count + (1 if is_failure else 0)
                tot = succ + fail
                conf = _calculate_confidence(succ, fail)

                # Determine updated status
                new_status = existing.status
                if fail > succ and tot >= 3:
                    new_status = PatternStatus.REJECTED.value
                elif conf >= 0.50 and tot >= 5:
                    new_status = PatternStatus.ACTIVE.value
                elif conf >= 0.35 and tot >= 3:
                    new_status = PatternStatus.VALIDATED.value
                else:
                    new_status = PatternStatus.CANDIDATE.value

                source_ids = list(set(existing.source_event_ids + [event.id]))
                self.update_pattern(
                    pattern_id=pattern_id,
                    success_count=succ,
                    failure_count=fail,
                    evidence_count=tot,
                    confidence=conf,
                    status=new_status,
                    source_event_ids=source_ids,
                )
            else:
                succ = 1 if is_success else 0
                fail = 1 if is_failure else 0
                tot = succ + fail
                conf = _calculate_confidence(succ, fail)
                self.create_pattern(
                    pattern_id=pattern_id,
                    pattern_type="hook_retention",
                    statement=f"Hooks of type '{hook_type}' drive positive engagement in project {event.project_id}.",
                    conditions={"hook_type": hook_type, "project_id": event.project_id},
                    evidence_count=tot,
                    success_count=succ,
                    failure_count=fail,
                    confidence=conf,
                    source_event_ids=[event.id],
                    status=PatternStatus.CANDIDATE.value,
                    scope=KnowledgeScope.PROJECT.value,
                    project_id=event.project_id,
                    account_id=event.account_id,
                )

    def create_pattern(
        self,
        pattern_type: str,
        statement: str,
        conditions: Dict[str, Any],
        evidence_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        confidence: float = 0.0,
        source_event_ids: Optional[List[str]] = None,
        status: str = PatternStatus.CANDIDATE.value,
        scope: str = KnowledgeScope.GLOBAL.value,
        account_id: str = "",
        project_id: str = "",
        pattern_id: str = "",
    ) -> KnowledgePattern:
        pid = pattern_id or f"pat_{uuid.uuid4().hex[:12]}"
        pattern = KnowledgePattern(
            id=pid,
            pattern_type=pattern_type,
            statement=statement,
            conditions=conditions,
            evidence_count=evidence_count,
            success_count=success_count,
            failure_count=failure_count,
            confidence=confidence,
            source_event_ids=source_event_ids or [],
            status=status,
            scope=scope,
            account_id=account_id,
            project_id=project_id,
        )
        with self.db.transaction() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO knowledge_patterns (
                    id, pattern_type, statement, conditions_json, evidence_count,
                    success_count, failure_count, confidence, source_event_ids_json,
                    version, status, scope, account_id, project_id, counterexamples_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pattern.id, pattern.pattern_type, pattern.statement,
                    json.dumps(pattern.conditions), pattern.evidence_count,
                    pattern.success_count, pattern.failure_count, pattern.confidence,
                    json.dumps(pattern.source_event_ids), pattern.version, pattern.status,
                    pattern.scope, pattern.account_id, pattern.project_id,
                    json.dumps(pattern.counterexamples), pattern.created_at, pattern.updated_at,
                )
            )
        return pattern

    def update_pattern(
        self,
        pattern_id: str,
        success_count: int,
        failure_count: int,
        evidence_count: int,
        confidence: float,
        status: str,
        source_event_ids: List[str],
    ) -> Optional[KnowledgePattern]:
        now = _now_iso()
        with self.db.transaction() as cur:
            cur.execute(
                """
                UPDATE knowledge_patterns
                SET success_count = ?, failure_count = ?, evidence_count = ?,
                    confidence = ?, status = ?, source_event_ids_json = ?,
                    version = version + 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    success_count, failure_count, evidence_count, confidence,
                    status, json.dumps(source_event_ids), now, pattern_id
                )
            )
        return self.get_pattern(pattern_id)

    def get_pattern(self, pattern_id: str) -> Optional[KnowledgePattern]:
        row = self.db.execute_single("SELECT * FROM knowledge_patterns WHERE id = ?", (pattern_id,))
        if not row:
            return None
        return KnowledgePattern(
            id=row["id"],
            pattern_type=row["pattern_type"],
            statement=row["statement"],
            conditions=json.loads(row["conditions_json"]),
            evidence_count=row["evidence_count"],
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            confidence=row["confidence"],
            source_event_ids=json.loads(row["source_event_ids_json"] or "[]"),
            version=row["version"],
            status=row["status"],
            scope=row["scope"],
            account_id=row["account_id"] or "",
            project_id=row["project_id"] or "",
            counterexamples=json.loads(row["counterexamples_json"] or "[]"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def query_knowledge(
        self,
        pattern_type: Optional[str] = None,
        scope: Optional[str] = None,
        account_id: Optional[str] = None,
        project_id: Optional[str] = None,
        min_confidence: float = 0.50,
        active_only: bool = True,
    ) -> List[KnowledgeRetrievalContext]:
        """
        Retrieves versioned knowledge context scoped to the requested tenant / project.
        Enforces tenant isolation: Account A cannot read Account B's private patterns.
        """
        query = "SELECT * FROM knowledge_patterns WHERE confidence >= ?"
        params: List[Any] = [min_confidence]

        if active_only:
            query += " AND status IN ('ACTIVE', 'VALIDATED')"

        if pattern_type:
            query += " AND pattern_type = ?"
            params.append(pattern_type)

        # Scoping rule: GLOBAL patterns are visible to all; ACCOUNT/PROJECT require matching ID
        if project_id and account_id:
            query += " AND (scope = 'GLOBAL' OR (scope = 'ACCOUNT' AND account_id = ?) OR (scope = 'PROJECT' AND project_id = ?))"
            params.extend([account_id, project_id])
        elif project_id:
            query += " AND (scope = 'GLOBAL' OR (scope = 'PROJECT' AND project_id = ?))"
            params.append(project_id)
        elif account_id:
            query += " AND (scope = 'GLOBAL' OR (scope = 'ACCOUNT' AND account_id = ?))"
            params.append(account_id)
        elif scope:
            query += " AND scope = ?"
            params.append(scope)

        query += " ORDER BY confidence DESC, evidence_count DESC"

        rows = self.db.execute(query, tuple(params))
        results = []
        for r in rows:
            results.append(KnowledgeRetrievalContext(
                pattern_id=r["id"],
                pattern_type=r["pattern_type"],
                statement=r["statement"],
                confidence=r["confidence"],
                evidence_count=r["evidence_count"],
                success_count=r["success_count"],
                failure_count=r["failure_count"],
                conditions=json.loads(r["conditions_json"]),
                counterexamples=json.loads(r["counterexamples_json"] or "[]"),
                source_references=json.loads(r["source_event_ids_json"] or "[]")[:5],
                last_updated=r["updated_at"],
            ))
        return results

    # ─── Experiment Framework ─────────────────────────────────────────────────

    def create_experiment(
        self,
        hypothesis: str,
        variant_a: Dict[str, Any],
        variant_b: Dict[str, Any],
        target_metrics: List[str],
        experiment_id: str = "",
    ) -> ExperimentRecord:
        xid = experiment_id or f"exp_{uuid.uuid4().hex[:12]}"
        exp = ExperimentRecord(
            id=xid,
            hypothesis=hypothesis,
            variant_a=variant_a,
            variant_b=variant_b,
            target_metrics=target_metrics,
        )
        with self.db.transaction() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO experiments (
                    id, hypothesis, variant_a_json, variant_b_json, target_metrics_json,
                    sample_size_a, sample_size_b, results_a_json, results_b_json,
                    status, winner, confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exp.id, exp.hypothesis, json.dumps(exp.variant_a),
                    json.dumps(exp.variant_b), json.dumps(exp.target_metrics),
                    exp.sample_size_a, exp.sample_size_b, json.dumps(exp.results_a),
                    json.dumps(exp.results_b), exp.status, exp.winner, exp.confidence,
                    exp.created_at, exp.updated_at,
                )
            )
        return exp

    def record_experiment_sample(
        self,
        experiment_id: str,
        variant: str,  # "A" or "B"
        metric_values: Dict[str, float],
    ) -> Optional[ExperimentRecord]:
        exp_row = self.db.execute_single("SELECT * FROM experiments WHERE id = ?", (experiment_id,))
        if not exp_row:
            return None

        size_a = exp_row["sample_size_a"] + (1 if variant == "A" else 0)
        size_b = exp_row["sample_size_b"] + (1 if variant == "B" else 0)
        res_a = json.loads(exp_row["results_a_json"] or "{}")
        res_b = json.loads(exp_row["results_b_json"] or "{}")

        # Update running averages
        target_dict = res_a if variant == "A" else res_b
        target_size = size_a if variant == "A" else size_b
        for k, v in metric_values.items():
            curr = target_dict.get(k, 0.0)
            target_dict[k] = round((curr * (target_size - 1) + v) / target_size, 2)

        # Evaluate significance if both have >= 5 samples
        status = ExperimentStatus.RUNNING.value
        winner = "INCONCLUSIVE"
        confidence = 0.0

        if size_a >= 5 and size_b >= 5:
            # Compare primary target metric
            target_metric = json.loads(exp_row["target_metrics_json"])[0]
            val_a = res_a.get(target_metric, 0.0)
            val_b = res_b.get(target_metric, 0.0)

            diff_pct = abs(val_a - val_b) / max(val_a, val_b, 1.0)
            if diff_pct >= 0.15:  # 15% clear margin
                status = ExperimentStatus.SUPPORTED.value
                winner = "VARIANT_A" if val_a > val_b else "VARIANT_B"
                confidence = round(min(0.95, 0.50 + (diff_pct * 0.5)), 2)
            else:
                status = ExperimentStatus.INCONCLUSIVE.value

        now = _now_iso()
        with self.db.transaction() as cur:
            cur.execute(
                """
                UPDATE experiments
                SET sample_size_a = ?, sample_size_b = ?, results_a_json = ?,
                    results_b_json = ?, status = ?, winner = ?, confidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    size_a, size_b, json.dumps(res_a), json.dumps(res_b),
                    status, winner, confidence, now, experiment_id
                )
            )

        row = self.db.execute_single("SELECT * FROM experiments WHERE id = ?", (experiment_id,))
        return ExperimentRecord(
            id=row["id"],
            hypothesis=row["hypothesis"],
            variant_a=json.loads(row["variant_a_json"]),
            variant_b=json.loads(row["variant_b_json"]),
            target_metrics=json.loads(row["target_metrics_json"]),
            sample_size_a=row["sample_size_a"],
            sample_size_b=row["sample_size_b"],
            results_a=json.loads(row["results_a_json"] or "{}"),
            results_b=json.loads(row["results_b_json"] or "{}"),
            status=row["status"],
            winner=row["winner"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ─── Portable Export & Import ─────────────────────────────────────────────

    def export_knowledge(self, export_path: Path) -> Path:
        """
        Produces a model-independent, self-contained JSON snapshot of all knowledge,
        decisions, and validated patterns (strictly zero secrets).
        """
        export_path.parent.mkdir(parents=True, exist_ok=True)
        patterns = self.db.execute("SELECT * FROM knowledge_patterns")
        decisions = self.db.execute("SELECT * FROM creative_decisions")
        events = self.db.execute("SELECT * FROM learning_events")
        experiments = self.db.execute("SELECT * FROM experiments")
        runs = self.db.execute("SELECT * FROM model_runs")

        data = {
            "schema_version": "1.0",
            "exported_at": _now_iso(),
            "model_runs": [dict(r) for r in runs],
            "creative_decisions": [dict(r) for r in decisions],
            "learning_events": [dict(r) for r in events],
            "knowledge_patterns": [dict(r) for r in patterns],
            "experiments": [dict(r) for r in experiments],
        }

        export_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return export_path

    def export_learning_dataset_jsonl(self, jsonl_path: Path) -> Path:
        """
        Produces a clean, model-independent JSONL training & retrieval dataset.
        Each line connects input/decision/reasoning to downstream performance evidence.
        (Strictly zero secrets, OAuth tokens, or private credentials).
        """
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        decisions = self.db.execute("SELECT * FROM creative_decisions")
        runs_map = {r["id"]: dict(r) for r in self.db.execute("SELECT * FROM model_runs")}

        lines = []
        for d in decisions:
            clip_id = d["clip_id"]
            proj_id = d["project_id"]
            # Find associated learning events
            events = self.db.execute(
                "SELECT * FROM learning_events WHERE source_id = ? AND project_id = ?",
                (clip_id, proj_id)
            )
            model_info = runs_map.get(d["model_run_id"], {})

            record = {
                "decision_id": d["id"],
                "project_id": proj_id,
                "episode_id": d["episode_id"],
                "clip_id": clip_id,
                "task_type": d["decision_type"],
                "decision_payload": json.loads(d["decision_payload_json"]),
                "reasoning_summary": d["reasoning_summary"],
                "model": {
                    "provider": model_info.get("model_provider", "unknown"),
                    "name": model_info.get("model_name", "unknown"),
                    "version": model_info.get("model_version", "v1"),
                },
                "outcomes": [
                    {
                        "event_type": e["event_type"],
                        "source_type": e["source_type"],
                        "payload": json.loads(e["payload_json"]),
                        "created_at": e["created_at"],
                    }
                    for e in events
                ],
                "created_at": d["created_at"],
            }
            lines.append(json.dumps(record, default=str))

        jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return jsonl_path

    def import_knowledge(self, import_path: Path) -> int:
        """
        Restores a knowledge snapshot idempotently. Returns total imported records.
        """
        if not import_path.exists():
            return 0
        raw = json.loads(import_path.read_text(encoding="utf-8"))
        count = 0

        with self.db.transaction() as cur:
            for r in raw.get("model_runs", []):
                cur.execute(
                    "INSERT OR REPLACE INTO model_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["id"], r["model_provider"], r["model_name"], r["model_version"],
                     r["prompt_version"], r["task_type"], r.get("input_reference"),
                     r.get("output_reference"), r.get("latency_ms", 0), r.get("token_usage_json"),
                     r.get("success", 1), r["created_at"])
                )
                count += 1

            for d in raw.get("creative_decisions", []):
                cur.execute(
                    "INSERT OR REPLACE INTO creative_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (d["id"], d["project_id"], d["episode_id"], d["clip_id"], d["decision_type"],
                     d["decision_payload_json"], d["reasoning_summary"], d.get("model_run_id") or None,
                     d.get("memory_context_ids_json"), d.get("version", 1), d["created_at"])
                )
                count += 1

            for p in raw.get("knowledge_patterns", []):
                cur.execute(
                    "INSERT OR REPLACE INTO knowledge_patterns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (p["id"], p["pattern_type"], p["statement"], p["conditions_json"],
                     p["evidence_count"], p["success_count"], p["failure_count"], p["confidence"],
                     p.get("source_event_ids_json"), p.get("version", 1), p["status"], p["scope"],
                     p.get("account_id"), p.get("project_id"), p.get("counterexamples_json"),
                     p["created_at"], p["updated_at"])
                )
                count += 1

        return count

    # ─── Historical Migration ─────────────────────────────────────────────────

    def migrate_from_creative_memory(self, memory_dir: Path) -> Dict[str, int]:
        """
        Migrates legacy Phase 10 JSON evidence and memory files into the canonical SQL DB.
        """
        migrated = {"evidence": 0, "memories": 0}
        if not memory_dir.exists():
            return migrated

        # Migrate evidence records
        for ev_file in memory_dir.glob("evidence_*.json"):
            try:
                data = json.loads(ev_file.read_text(encoding="utf-8"))
                self.record_learning_event(
                    event_type=data.get("outcome", "NEUTRAL"),
                    source_type=data.get("source_type", "PRODUCTION"),
                    source_id=data.get("clip_id", ""),
                    project_id=data.get("episode_id", "default"),
                    account_id=data.get("account_id", "default"),
                    payload={"observation": data.get("observation", ""), "magnitude": data.get("magnitude", 0.5)},
                    event_id=f"mig_ev_{data.get('evidence_id', uuid.uuid4().hex[:12])}",
                )
                migrated["evidence"] += 1
            except Exception:
                continue

        # Migrate memories to patterns
        for mem_file in memory_dir.glob("memory_*.json"):
            try:
                data = json.loads(mem_file.read_text(encoding="utf-8"))
                self.create_pattern(
                    pattern_type=data.get("memory_type", "hook_retention"),
                    statement=data.get("statement", ""),
                    conditions=data.get("conditions", {}),
                    evidence_count=data.get("sample_size", 0),
                    success_count=data.get("success_count", 0),
                    failure_count=data.get("failure_count", 0),
                    confidence=data.get("confidence", 0.0),
                    status=data.get("status", PatternStatus.CANDIDATE.value),
                    scope=data.get("scope", KnowledgeScope.GLOBAL.value),
                    pattern_id=f"mig_mem_{data.get('memory_id', uuid.uuid4().hex[:12])}",
                )
                migrated["memories"] += 1
            except Exception:
                continue

        return migrated
