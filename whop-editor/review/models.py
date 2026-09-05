from dataclasses import dataclass, field
from enum import Enum
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator, ValidationError


class ReviewError(Exception):
    """Base exception for review parsing and validation."""
    pass


class ReviewValidationError(ReviewError, ValueError):
    """Raised when review data violates semantic constraints (invalid verdict, out-of-bounds score)."""
    pass


class ReviewParseError(ReviewError, ValueError):
    """Raised when review text cannot be parsed or recovered."""
    pass


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class ReviewProblem(BaseModel):
    scene: Optional[int] = None
    type: str = "general"
    description: str

    @field_validator("description")
    @classmethod
    def non_empty_desc(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Problem description cannot be empty.")
        return v.strip()


class StructuredReview(BaseModel):
    verdict: str
    overall_score: float = Field(ge=0.0, le=10.0)
    scene_accuracy: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    instruction_accuracy: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    character_accuracy: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    timing_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    visual_quality: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    problems: List[ReviewProblem] = Field(default_factory=list)
    corrections: List[str] = Field(default_factory=list)
    is_recovered: bool = False
    recovery_reason: Optional[str] = None

    @field_validator("problems", mode="before")
    @classmethod
    def validate_problems(cls, v: Any) -> Any:
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, str):
                    res.append({"description": item})
                else:
                    res.append(item)
            return res
        return v

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, v: str) -> str:
        v_upper = v.strip().upper()
        if v_upper not in (ReviewVerdict.PASS.value, ReviewVerdict.FAIL.value, ReviewVerdict.NEEDS_HUMAN_REVIEW.value):
            raise ValueError(f"Invalid verdict '{v}'. Must be PASS, FAIL, or NEEDS_HUMAN_REVIEW.")
        return v_upper

    @field_validator("corrections")
    @classmethod
    def validate_corrections(cls, v: List[str]) -> List[str]:
        return [c.strip() for c in v if c and c.strip()]


def extract_json_payload(raw_text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Extracts and parses JSON from raw text.
    Handles markdown code fences (```json ... ``` or ``` ... ```) and minor syntax quirks.
    Returns (data_dict, raw_json_str) if successful, or (None, None).
    """
    if not raw_text or not raw_text.strip():
        return None, None

    text = raw_text.strip()
    # 1. Extract from markdown code fences if present
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # 2. Locate outermost curly braces
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None, None

    candidate = text[start:end+1].strip()

    # 3. Direct JSON parse attempt
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data, candidate
    except json.JSONDecodeError:
        pass

    # 4. Clean minor formatting quirks (trailing commas before } or ])
    cleaned = re.sub(r",\s*([\]}])", r"\1", candidate)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data, cleaned
    except json.JSONDecodeError:
        pass

    return None, None


def recover_freeform_review(raw_text: str) -> StructuredReview:
    """
    Recovers structured review from freeform text/markdown when no JSON is present.
    Explicitly marks the review with is_recovered=True.
    Rejects empty text or text with explicitly invalid semantic values.
    """
    if not raw_text or not raw_text.strip():
        raise ReviewParseError("Cannot recover review from empty text.")

    text = raw_text.strip()
    raw_lower = text.lower()

    # If the text explicitly states an invalid verdict (e.g. "verdict: maybe" or "verdict: unknown")
    verdict_match = re.search(r'\bverdict\s*[:=-]\s*([a-zA-Z_]+)', raw_lower)
    if verdict_match:
        v_cand = verdict_match.group(1).upper()
        if v_cand not in (ReviewVerdict.PASS.value, ReviewVerdict.FAIL.value, ReviewVerdict.NEEDS_HUMAN_REVIEW.value):
            raise ReviewValidationError(f"Invalid explicit verdict '{v_cand}' in freeform response.")

    # If the text explicitly states an out-of-bounds score (e.g. "score: 15" or "12/10")
    score_match = re.search(r'(?:score|rating)\s*[:=-]?\s*(\d+(?:\.\d+)?)\s*(?:/\s*10)?', raw_lower)
    if score_match:
        parsed_s = None
        try:
            parsed_s = float(score_match.group(1))
        except (ValueError, TypeError):
            pass

        if parsed_s is not None and (parsed_s > 10.0 or parsed_s < 0.0):
            raise ReviewValidationError(f"Explicit score {parsed_s} in freeform response is out of bounds [0.0, 10.0].")

    is_pass = "pass" in raw_lower and "fail" not in raw_lower
    verdict = ReviewVerdict.PASS if is_pass else ReviewVerdict.FAIL
    score = 8.0 if is_pass else 4.5

    # Extract lines with suggestions or bullet points
    corrections = []
    problems = []
    for line in text.splitlines():
        line_clean = line.strip(" -*#•\t")
        if not line_clean:
            continue
        if any(k in line_clean.lower() for k in ["scale", "zoom", "punch", "crop", "framing", "duration", "timing", "overlay", "margin"]):
            corrections.append(line_clean)
            problems.append(ReviewProblem(type="framing", description=line_clean))

    if not corrections and not is_pass:
        corrections = ["Adjust punch-in framing scale and verify alignment."]
        problems = [ReviewProblem(type="framing", description="Visual framing critique from reviewer.")]

    return StructuredReview(
        verdict=verdict,
        overall_score=score,
        scene_accuracy=score,
        timing_score=score,
        visual_quality=score,
        problems=problems,
        corrections=corrections,
        is_recovered=True,
        recovery_reason="Extracted from freeform text (no valid JSON found)"
    )


def parse_and_validate_gemini_review(raw_text: str, allow_recovery: bool = True) -> StructuredReview:
    """
    Parses and strictly validates a Gemini review response.
    
    1. Attempts to extract and clean JSON payload from markdown fences or raw text.
    2. If JSON is found, strictly validates against StructuredReview schema.
       Semantic violations (e.g. invalid verdict, score out of bounds) raise ReviewValidationError.
    3. If NO JSON is found and allow_recovery is True, extracts structured critique from
       freeform text, clearly marking is_recovered=True.
    4. If allow_recovery is False and no JSON is found, raises ReviewParseError.
    """
    if not raw_text or not raw_text.strip():
        raise ReviewParseError("Review text cannot be empty.")

    data, _ = extract_json_payload(raw_text)

    if data is not None:
        try:
            review = StructuredReview(**data)
            review.is_recovered = False
            return review
        except (ValidationError, ValueError) as e:
            # Model emitted structured JSON, but semantic constraints were violated
            raise ReviewValidationError(f"Review schema validation failed: {e}") from e

    # No JSON payload could be extracted
    if allow_recovery:
        return recover_freeform_review(raw_text)
    
    raise ReviewParseError("No valid JSON structure found in response and recovery is disabled.")

