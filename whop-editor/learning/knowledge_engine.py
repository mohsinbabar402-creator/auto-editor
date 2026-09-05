from enum import Enum
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger("whop_editor.knowledge_engine")


class KnowledgeStatus(str, Enum):
    OBSERVATION = "observation"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    CANONICAL = "canonical"


class KnowledgeEngine:
    """
    Self-improving Knowledge & Evidence Engine.
    Tracks editing hypotheses, updates confidence based on Gemini reviews
    and human approvals, and promotes validated principles into canonical production knowledge.
    """

    DEFAULT_FALLBACK_PARAMS = {
        "scale": 1.18,
        "duration_ms": 850,
        "target_word": "differential",
        "safe_margin_y": 100
    }

    def __init__(self, repo):
        self.repo = repo

    def get_validated_parameters(
        self,
        project_id: str,
        action_type: str = "PUNCH_IN_PARAMS",
        min_confidence: float = 0.6
    ) -> Dict[str, Any]:
        """
        Retrieves highest-confidence approved editing parameters scoped to the project/niche.
        Falls back to baseline parameters if no validated knowledge exists yet.
        """
        try:
            records = self.repo.list_knowledge(
                project_id=project_id,
                action_type=action_type,
                min_confidence=min_confidence
            )
            for r in records:
                if r.get("status") in [KnowledgeStatus.VALIDATED.value, KnowledgeStatus.CANONICAL.value]:
                    params = json.loads(r.get("parameters_json", "{}"))
                    if params:
                        logger.info(
                            f"Retrieved {r['status'].upper()} editing parameters from Knowledge [{r['id']}]: "
                            f"confidence={r['confidence']:.2f}, sample_size={r['sample_size']}"
                        )
                        return params
        except Exception as e:
            logger.warning(f"Could not fetch validated knowledge: {e}")

        logger.info(f"Using default baseline parameters for action '{action_type}'")
        return self.DEFAULT_FALLBACK_PARAMS.copy()

    def record_edit_outcome(
        self,
        project_id: str,
        video_id: Optional[str],
        event_type: str,
        action_type: str,
        parameters: Dict[str, Any],
        approved: bool,
        score: float,
        outcome_note: str,
        correction_applied: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Closes the learning loop:
        1. Finds or creates a knowledge candidate for the editing parameters.
        2. Adjusts Bayesian confidence and sample size based on approval/rejection.
        3. Evaluates lifecycle promotion (CANDIDATE -> VALIDATED -> CANONICAL).
        4. Records persistent evidence linked to the video and knowledge candidate.
        """
        params_str = json.dumps(parameters, sort_keys=True)
        knowledge_record = None

        # 1. Search for existing knowledge matching this project and parameters
        try:
            existing = self.repo.list_knowledge(project_id=project_id, action_type=action_type)
            for k in existing:
                try:
                    k_params = json.loads(k.get("parameters_json", "{}"))
                    if k_params == parameters:
                        knowledge_record = k
                        break
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Error searching existing knowledge: {e}")

        # 2. Create or Update Knowledge candidate
        if not knowledge_record:
            k_id = f"know_{uuid.uuid4().hex[:10]}"
            initial_confidence = 0.5 if approved else 0.25
            try:
                knowledge_record = self.repo.create_knowledge_candidate(
                    knowledge_id=k_id,
                    project_id=project_id,
                    event_type=event_type,
                    action_type=action_type,
                    parameters_json=params_str,
                    confidence=initial_confidence,
                    sample_size=1
                )
                logger.info(f"Created new Knowledge Candidate [{k_id}] with initial confidence={initial_confidence:.2f}")
            except Exception as e:
                logger.error(f"Failed to create knowledge record: {e}")
                return {}
        else:
            k_id = knowledge_record["id"]
            current_conf = float(knowledge_record.get("confidence", 0.3))
            current_samples = int(knowledge_record.get("sample_size", 0)) + 1

            if approved:
                # Positive reinforcement
                new_conf = min(0.98, current_conf + 0.15)
            else:
                # Negative feedback
                new_conf = max(0.10, current_conf - 0.12)

            # Evaluate promotion
            new_status = knowledge_record.get("status", KnowledgeStatus.CANDIDATE.value)
            if current_samples >= 2 and new_conf >= 0.65:
                new_status = KnowledgeStatus.VALIDATED.value
            if current_samples >= 4 and new_conf >= 0.85:
                new_status = KnowledgeStatus.CANONICAL.value
            if not approved and new_conf < 0.35:
                new_status = KnowledgeStatus.OBSERVATION.value

            try:
                knowledge_record = self.repo.update_knowledge(
                    knowledge_id=k_id,
                    status=new_status,
                    confidence=new_conf,
                    sample_size=current_samples,
                    parameters_json=params_str
                )
                logger.info(
                    f"Updated Knowledge [{k_id}]: status={new_status}, "
                    f"confidence={new_conf:.2f}, sample_size={current_samples}"
                )
            except Exception as e:
                logger.warning(f"Failed to update knowledge [{k_id}]: {e}")

        # 3. Record Evidence Link
        ev_id = f"evid_{uuid.uuid4().hex[:10]}"
        try:
            self.repo.record_evidence(
                evidence_id=ev_id,
                knowledge_id=k_id,
                video_id=video_id,
                outcome_note=outcome_note,
                metric_value=score
            )
            logger.info(f"Recorded Evidence [{ev_id}] linked to Knowledge [{k_id}]")
        except Exception as e:
            logger.warning(f"Could not record evidence [{ev_id}]: {e}")

        # 4. Log audit trail
        try:
            self.repo.log_audit(
                audit_id=f"audit_learn_{uuid.uuid4().hex[:8]}",
                action="KNOWLEDGE_UPDATE",
                target=k_id,
                detail=f"Approved={approved} | Score={score:.1f} | Note={outcome_note[:100]}"
            )
        except Exception:
            pass

        return knowledge_record or {}
