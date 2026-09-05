from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("whop_editor.feedback_interpreter")


class IssueType(str, Enum):
    FRAMING = "framing"
    TIMING = "timing"
    OVERLAY = "overlay"
    PACING = "pacing"
    AUDIO = "audio"
    GENERAL = "general"


class CorrectionSource(str, Enum):
    USER_FEEDBACK = "user_feedback"
    GEMINI_REVIEW = "gemini_review"


class StoppingCondition(str, Enum):
    CONDITION_A = "Condition A: Quality gate achieved"
    CONDITION_B = "Condition B: No meaningful supported improvement remains"
    CONDITION_C = "Condition C: Current source material limits further improvement"
    CONDITION_D = "Condition D: Required capability does not exist in current approved toolchain"
    CONDITION_E = "Condition E: Resource / safety iteration limit reached"
    CONDITION_F = "Condition F: Security / untrusted injection concern"
    CONDITION_G = "Condition G: Human decision required due to material ambiguity"


class StructuredCorrectionPlan(BaseModel):
    issue_type: IssueType = IssueType.GENERAL
    probable_problem: str = "General quality adjustment"
    strategy_name: Optional[str] = None
    scale_adjustment: Optional[float] = None
    duration_ms_adjustment: Optional[int] = None
    y_offset_adjustment: Optional[float] = None
    lead_in_ms_adjustment: Optional[int] = None
    phrase_expansion: Optional[bool] = None
    target_word_override: Optional[str] = None
    safe_margin_y: Optional[int] = None
    stopping_condition: Optional[StoppingCondition] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: CorrectionSource = CorrectionSource.GEMINI_REVIEW
    raw_input: str = ""

    def to_parameters_dict(self) -> Dict[str, Any]:
        params = {}
        if self.scale_adjustment is not None:
            params["scale"] = round(self.scale_adjustment, 3)
        if self.duration_ms_adjustment is not None:
            params["duration_ms"] = self.duration_ms_adjustment
        if self.y_offset_adjustment is not None:
            params["y_offset"] = round(self.y_offset_adjustment, 2)
        if self.lead_in_ms_adjustment is not None:
            params["lead_in_ms"] = self.lead_in_ms_adjustment
        if self.phrase_expansion is not None:
            params["phrase_expansion"] = self.phrase_expansion
        if self.target_word_override is not None:
            params["target_word"] = self.target_word_override
        if self.safe_margin_y is not None:
            params["safe_margin_y"] = self.safe_margin_y
        return params


class FeedbackInterpreter:
    """
    Transforms natural language critiques and Gemini review verdicts into
    testable, bounded parameter modifications (StructuredCorrectionPlan).
    """

    # Safe physical parameter bounds for short-form punch-in zooms
    MIN_SCALE = 1.05
    MAX_SCALE = 1.35
    DEFAULT_SCALE = 1.15

    MIN_DURATION_MS = 500
    MAX_DURATION_MS = 1800
    DEFAULT_DURATION_MS = 800

    @classmethod
    def interpret_user_feedback(
        cls,
        feedback_text: str,
        current_scale: float = DEFAULT_SCALE,
        current_duration_ms: int = DEFAULT_DURATION_MS
    ) -> StructuredCorrectionPlan:
        """
        Parses freeform user critiques (e.g. 'zoom looks weird', 'too slow')
        into bounded production guidance with uncertainty estimates.
        """
        text = feedback_text.strip()
        text_lower = text.lower()

        # 1. Framing / Zoom critiques
        if any(w in text_lower for w in ["zoom", "punch", "scale", "tight", "wide", "framing", "crop", "crop closer"]):
            if any(w in text_lower for w in ["too tight", "too close", "too much", "less zoom", "weird", "unnatural"]):
                new_scale = max(cls.MIN_SCALE, current_scale - 0.05)
                return StructuredCorrectionPlan(
                    issue_type=IssueType.FRAMING,
                    probable_problem="Punch-in zoom magnitude feels unnatural or too jarring.",
                    strategy_name="scale",
                    scale_adjustment=new_scale,
                    confidence=0.7,
                    source=CorrectionSource.USER_FEEDBACK,
                    raw_input=text
                )
            elif any(w in text_lower for w in ["tighter", "closer", "more zoom", "punch in more", "not enough", "too wide"]):
                new_scale = min(cls.MAX_SCALE, current_scale + 0.08)
                return StructuredCorrectionPlan(
                    issue_type=IssueType.FRAMING,
                    probable_problem="Framing is too wide to retain talking-head focus or eliminate peripheral distractions.",
                    strategy_name="scale",
                    scale_adjustment=new_scale,
                    confidence=0.8,
                    source=CorrectionSource.USER_FEEDBACK,
                    raw_input=text
                )

        # 2. Timing / Pacing critiques
        if any(w in text_lower for w in ["slow", "held too long", "long", "quick", "fast", "timing", "pacing", "abrupt", "too short"]):
            if any(w in text_lower for w in ["too short", "too fast", "abrupt", "longer", "hold it"]):
                new_dur = min(cls.MAX_DURATION_MS, current_duration_ms + 300)
                return StructuredCorrectionPlan(
                    issue_type=IssueType.TIMING,
                    probable_problem="Punch-in window was held too briefly to emphasize key statement.",
                    strategy_name="duration_ms",
                    duration_ms_adjustment=new_dur,
                    confidence=0.75,
                    source=CorrectionSource.USER_FEEDBACK,
                    raw_input=text
                )
            elif any(w in text_lower for w in ["too long", "too slow", "drag", "quicker", "snappy"]):
                new_dur = max(cls.MIN_DURATION_MS, current_duration_ms - 250)
                return StructuredCorrectionPlan(
                    issue_type=IssueType.TIMING,
                    probable_problem="Punch-in duration is sluggish and detracts from short-form snappy pacing.",
                    strategy_name="duration_ms",
                    duration_ms_adjustment=new_dur,
                    confidence=0.75,
                    source=CorrectionSource.USER_FEEDBACK,
                    raw_input=text
                )

        # 3. Overlay / Lower third critiques
        if any(w in text_lower for w in ["cut off", "text", "overlay", "margin", "banner", "lower third", "safe zone"]):
            return StructuredCorrectionPlan(
                issue_type=IssueType.OVERLAY,
                probable_problem="Text overlay borders intersect platform UI or vertical edge safe zones.",
                strategy_name="y_offset",
                safe_margin_y=120,
                y_offset_adjustment=160.0,
                confidence=0.85,
                source=CorrectionSource.USER_FEEDBACK,
                raw_input=text
            )

        # Fallback candidate
        return StructuredCorrectionPlan(
            issue_type=IssueType.GENERAL,
            probable_problem="General feedback requires conservative adjustment.",
            strategy_name="scale",
            scale_adjustment=min(cls.MAX_SCALE, current_scale + 0.04),
            duration_ms_adjustment=current_duration_ms,
            confidence=0.4,
            source=CorrectionSource.USER_FEEDBACK,
            raw_input=text
        )

    @classmethod
    def interpret_gemini_review(
        cls,
        corrections: List[str],
        problems: List[Any] = [],
        current_scale: float = DEFAULT_SCALE,
        current_duration_ms: int = DEFAULT_DURATION_MS,
        current_y_offset: float = 0.0,
        current_lead_in_ms: int = 40,
        current_phrase_expansion: bool = False,
        ineffective_strategies: Optional[List[str]] = None
    ) -> StructuredCorrectionPlan:
        """
        Interprets Gemini's structured critique into a unified actionable plan.
        Explores diverse supported editing strategies:
        - scale (framing zoom factor)
        - duration_ms (effect duration window)
        - y_offset (bottom-anchored safe margin clearance)
        - phrase_expansion (widening zoom from single token to rhetorical phrase)
        - lead_in_timing (pre-roll offset to synchronize with initial spoken syllable)
        """
        combined_text = " ".join(corrections) + " " + " ".join(
            p.description if hasattr(p, "description") else str(p) for p in problems
        )
        combined_lower = combined_text.lower()

        new_scale = current_scale
        new_duration = current_duration_ms
        margin_y = None
        y_offset_candidate = None
        phrase_expansion_candidate = None
        lead_in_candidate = None
        issue = IssueType.GENERAL
        strategy_name = None

        problem_types = {
            (p.type if hasattr(p, "type") else p.get("type", "") if isinstance(p, dict) else "").lower()
            for p in problems
        }
        ineffective = set(ineffective_strategies or [])

        # 1. Scale extraction
        scale_match = re.search(r'scale\s*(?:to|of|at)?\s*(\d+\.\d+)x?', combined_lower)
        scale_candidate = None
        if scale_match:
            try:
                parsed_s = float(scale_match.group(1))
                scale_candidate = max(cls.MIN_SCALE, min(cls.MAX_SCALE, parsed_s))
                issue = IssueType.FRAMING
            except ValueError:
                pass
        elif any(w in combined_lower for w in ["punch in tighter", "closer", "tighten headroom", "crop tighter", "eliminate adjacent"]):
            scale_candidate = min(cls.MAX_SCALE, max(1.22, current_scale + 0.07))
            issue = IssueType.FRAMING
        elif any(w in combined_lower for w in ["too tight", "pull back", "widen"]):
            scale_candidate = max(cls.MIN_SCALE, current_scale - 0.06)
            issue = IssueType.FRAMING
        elif "framing" in problem_types or any(w in combined_lower for w in ["framing", "scale", "zoom", "punch-in framing"]):
            if current_scale < 1.25:
                scale_candidate = min(cls.MAX_SCALE, round(current_scale + 0.05, 2))
            else:
                scale_candidate = max(cls.MIN_SCALE, round(current_scale - 0.05, 2))
            issue = IssueType.FRAMING

        # 2. Timing / duration extraction
        dur_match = re.search(r'(\d{3,4})\s*ms', combined_lower)
        dur_candidate = None
        if dur_match:
            try:
                parsed_d = int(dur_match.group(1))
                dur_candidate = max(cls.MIN_DURATION_MS, min(cls.MAX_DURATION_MS, parsed_d))
                issue = IssueType.TIMING
            except ValueError:
                pass
        elif any(w in combined_lower for w in ["extend duration", "hold longer", "synchronized with speech pauses"]):
            dur_candidate = min(cls.MAX_DURATION_MS, max(1000, current_duration_ms + 250))
            issue = IssueType.TIMING
        elif any(w in combined_lower for w in ["quicker", "faster", "cut earlier", "too long"]):
            dur_candidate = max(cls.MIN_DURATION_MS, current_duration_ms - 200)
            issue = IssueType.TIMING
        elif "timing" in problem_types or any(w in combined_lower for w in ["timing", "duration", "pacing", "window"]):
            if current_duration_ms < 1200:
                dur_candidate = min(cls.MAX_DURATION_MS, current_duration_ms + 200)
            else:
                dur_candidate = max(cls.MIN_DURATION_MS, current_duration_ms - 200)
            issue = IssueType.TIMING

        # 3. Overlay / cut-off / vertical framing
        if any(w in combined_lower for w in ["cut off", "lower-third", "safe zones", "banners", "overlapping", "bottom border", "bottom edge"]):
            margin_y = 120
            if "y_offset" not in ineffective:
                if current_y_offset == 0.0:
                    y_offset_candidate = 160.0
                elif current_y_offset < 180.0:
                    y_offset_candidate = 180.0
                elif current_y_offset < 210.0:
                    y_offset_candidate = 210.0
            if issue == IssueType.GENERAL:
                issue = IssueType.OVERLAY

        # 4. Phrase expansion detection
        if any(w in combined_lower for w in ["phrasing", "emphasis phrasing", "thematic emphasis", "phrase", "key emphasis phrasing"]):
            if "phrase_expansion" not in ineffective and not current_phrase_expansion:
                phrase_expansion_candidate = True
                if issue == IssueType.GENERAL:
                    issue = IssueType.TIMING

        # 5. Lead-in timing detection
        if any(w in combined_lower for w in ["lead in", "lead-in", "syllable", "cut earlier", "early transition", "speech pauses"]):
            if "lead_in_timing" not in ineffective and current_lead_in_ms < 140:
                lead_in_candidate = 160
                if issue == IssueType.GENERAL:
                    issue = IssueType.TIMING

        # Apply strategy avoidance / filtering
        if "scale" in ineffective and scale_candidate is not None:
            logger.info("Scale adjustment marked ineffective. Diverting to alternative timing/framing strategy.")
            scale_candidate = None
            if "duration_ms" not in ineffective and dur_candidate is None:
                dur_candidate = min(cls.MAX_DURATION_MS, current_duration_ms + 250) if current_duration_ms < 1200 else max(cls.MIN_DURATION_MS, current_duration_ms - 200)
                issue = IssueType.TIMING
            elif "y_offset" not in ineffective and y_offset_candidate is None and margin_y is not None:
                y_offset_candidate = 160.0
                issue = IssueType.OVERLAY

        if "duration_ms" in ineffective and dur_candidate is not None:
            logger.info("Duration adjustment marked ineffective. Diverting to alternative framing strategy.")
            dur_candidate = None
            if "scale" not in ineffective and scale_candidate is None:
                scale_candidate = min(cls.MAX_SCALE, current_scale + 0.05) if current_scale < 1.25 else max(cls.MIN_SCALE, current_scale - 0.05)
                issue = IssueType.FRAMING
            elif "y_offset" not in ineffective and y_offset_candidate is None and margin_y is not None:
                y_offset_candidate = 160.0
                issue = IssueType.OVERLAY

        if "y_offset" in ineffective:
            y_offset_candidate = None
        if "phrase_expansion" in ineffective:
            phrase_expansion_candidate = None
        if "lead_in_timing" in ineffective:
            lead_in_candidate = None

        # Check if all primary automated strategies have already been exhausted
        if "scale" in ineffective and "duration_ms" in ineffective and ("y_offset" in ineffective or y_offset_candidate is None) and ("phrase_expansion" in ineffective or phrase_expansion_candidate is None) and ("lead_in_timing" in ineffective or lead_in_candidate is None):
            logger.warning("All relevant automated correction strategies have been tried and failed.")
            return StructuredCorrectionPlan(
                issue_type=IssueType.GENERAL,
                probable_problem="Repeated automated corrections failed to improve quality. Safe alternative strategies exhausted.",
                strategy_name="EXHAUSTED",
                scale_adjustment=None,
                duration_ms_adjustment=None,
                y_offset_adjustment=None,
                lead_in_ms_adjustment=None,
                phrase_expansion=None,
                safe_margin_y=None,
                stopping_condition=StoppingCondition.CONDITION_B,
                confidence=0.0,
                source=CorrectionSource.GEMINI_REVIEW,
                raw_input=combined_text[:300]
            )

        # Check if ALL applicable strategies are exhausted
        if (
            scale_candidate is None and
            dur_candidate is None and
            y_offset_candidate is None and
            phrase_expansion_candidate is None and
            lead_in_candidate is None and
            margin_y is None
        ):
            logger.warning("All primary and secondary automated correction strategies have been tried and failed.")
            return StructuredCorrectionPlan(
                issue_type=IssueType.GENERAL,
                probable_problem="Repeated automated corrections failed to improve quality. Safe alternative strategies exhausted.",
                strategy_name="EXHAUSTED",
                scale_adjustment=None,
                duration_ms_adjustment=None,
                y_offset_adjustment=None,
                lead_in_ms_adjustment=None,
                phrase_expansion=None,
                safe_margin_y=None,
                stopping_condition=StoppingCondition.CONDITION_B,
                confidence=0.0,
                source=CorrectionSource.GEMINI_REVIEW,
                raw_input=combined_text[:300]
            )


        # Select the active strategy
        if phrase_expansion_candidate is not None:
            strategy_name = "phrase_expansion"
        elif lead_in_candidate is not None:
            strategy_name = "lead_in_timing"
        elif y_offset_candidate is not None:
            strategy_name = "y_offset"
        elif dur_candidate is not None:
            strategy_name = "duration_ms"
        elif scale_candidate is not None:
            strategy_name = "scale"

        if scale_candidate is not None:
            new_scale = scale_candidate
        if dur_candidate is not None:
            new_duration = dur_candidate

        return StructuredCorrectionPlan(
            issue_type=issue,
            probable_problem="Gemini visual QA detected framing/timing/overlay issues on rendered output.",
            strategy_name=strategy_name,
            scale_adjustment=new_scale if new_scale != current_scale else None,
            duration_ms_adjustment=new_duration if new_duration != current_duration_ms else None,
            y_offset_adjustment=y_offset_candidate if y_offset_candidate != current_y_offset else None,
            lead_in_ms_adjustment=lead_in_candidate,
            phrase_expansion=phrase_expansion_candidate,
            safe_margin_y=margin_y,
            confidence=0.85,
            source=CorrectionSource.GEMINI_REVIEW,
            raw_input=combined_text[:300]
        )


