import json
import logging
from typing import Any, Dict
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import settings

logger = logging.getLogger("whop_editor.validation")


class ProposalValidationError(Exception):
    """Raised when an AI edit proposal violates schema or boundary constraints."""
    pass


class EditProposalModel(BaseModel):
    """
    Pydantic schema enforcing exact types, bounds, and forbidding extraneous fields.
    """
    model_config = ConfigDict(extra="forbid", strict=True)

    word_index: int = Field(
        ...,
        description="0-based index of the target word in the transcript",
        ge=0
    )
    scale: float = Field(
        ...,
        description="Punch-in zoom scale factor",
        ge=settings.MIN_SCALE,
        le=settings.MAX_SCALE
    )
    duration_ms: int = Field(
        ...,
        description="Duration of the punch-in effect in milliseconds",
        ge=settings.MIN_DURATION_MS,
        le=settings.MAX_DURATION_MS
    )
    y_offset: float = Field(
        default=0.0,
        description="Vertical crop offset in pixels to preserve lower-third overlays (positive) or headroom (negative)",
        ge=-500.0,
        le=500.0
    )



def validate_edit_proposal(
    raw_proposal: Any,
    transcript_word_count: int
) -> EditProposalModel:
    """
    Strictly validates raw AI proposal against schema and transcript boundaries.
    Rejects any non-dict, unexpected fields, out-of-bound indexes, or invalid values.
    """
    if transcript_word_count <= 0:
        raise ProposalValidationError("Cannot validate proposal against an empty transcript (word count <= 0).")

    # If raw input is a JSON string, parse it first
    data: Dict[str, Any]
    if isinstance(raw_proposal, str):
        try:
            data = json.loads(raw_proposal)
        except Exception as e:
            raise ProposalValidationError(f"Raw proposal string is not valid JSON: {e}") from e
    elif isinstance(raw_proposal, dict):
        data = raw_proposal
    else:
        raise ProposalValidationError(f"Expected dict or JSON string for edit proposal, got {type(raw_proposal).__name__}")

    try:
        validated = EditProposalModel.model_validate(data)
    except ValidationError as e:
        logger.error(f"Proposal schema validation failed: {e}")
        error_details = "; ".join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
        raise ProposalValidationError(f"Invalid edit proposal schema: {error_details}") from e

    # Check that word_index exists in the transcript
    if validated.word_index >= transcript_word_count:
        raise ProposalValidationError(
            f"word_index {validated.word_index} is out of bounds for transcript containing {transcript_word_count} words (valid range: 0 to {transcript_word_count - 1})."
        )

    logger.info(
        f"Proposal validated: word_index={validated.word_index}, "
        f"scale={validated.scale}x, duration={validated.duration_ms}ms"
    )
    return validated
