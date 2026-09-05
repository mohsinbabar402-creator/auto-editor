import pytest
from validation.edit_schema import validate_edit_proposal, ProposalValidationError, EditProposalModel


def test_valid_proposal():
    raw = {"word_index": 3, "scale": 1.15, "duration_ms": 600}
    validated = validate_edit_proposal(raw, transcript_word_count=10)
    assert validated.word_index == 3
    assert validated.scale == 1.15
    assert validated.duration_ms == 600


def test_valid_json_string():
    raw_str = '{"word_index": 0, "scale": 1.20, "duration_ms": 800}'
    validated = validate_edit_proposal(raw_str, transcript_word_count=5)
    assert validated.word_index == 0
    assert validated.scale == 1.20


def test_invalid_scale_too_low():
    raw = {"word_index": 1, "scale": 1.02, "duration_ms": 500} # Min scale is 1.05
    with pytest.raises(ProposalValidationError) as exc:
        validate_edit_proposal(raw, transcript_word_count=5)
    assert "scale" in str(exc.value)


def test_invalid_scale_too_high():
    raw = {"word_index": 1, "scale": 1.50, "duration_ms": 500} # Max scale is 1.30
    with pytest.raises(ProposalValidationError) as exc:
        validate_edit_proposal(raw, transcript_word_count=5)
    assert "scale" in str(exc.value)


def test_invalid_duration_too_short():
    raw = {"word_index": 1, "scale": 1.15, "duration_ms": 100} # Min duration is 200ms
    with pytest.raises(ProposalValidationError) as exc:
        validate_edit_proposal(raw, transcript_word_count=5)
    assert "duration_ms" in str(exc.value)


def test_invalid_duration_too_long():
    raw = {"word_index": 1, "scale": 1.15, "duration_ms": 4000} # Max duration is 3000ms
    with pytest.raises(ProposalValidationError) as exc:
        validate_edit_proposal(raw, transcript_word_count=5)
    assert "duration_ms" in str(exc.value)


def test_out_of_bounds_word_index():
    raw = {"word_index": 10, "scale": 1.15, "duration_ms": 500}
    with pytest.raises(ProposalValidationError) as exc:
        validate_edit_proposal(raw, transcript_word_count=10) # Valid range 0-9
    assert "out of bounds" in str(exc.value)


def test_negative_word_index():
    raw = {"word_index": -1, "scale": 1.15, "duration_ms": 500}
    with pytest.raises(ProposalValidationError) as exc:
        validate_edit_proposal(raw, transcript_word_count=10)
    assert "word_index" in str(exc.value)


def test_extraneous_fields_rejected():
    raw = {"word_index": 2, "scale": 1.15, "duration_ms": 500, "hack": "execute_code"}
    with pytest.raises(ProposalValidationError) as exc:
        validate_edit_proposal(raw, transcript_word_count=10)
    assert "extra_forbidden" in str(exc.value) or "Extra inputs are not permitted" in str(exc.value)


def test_empty_transcript_rejection():
    raw = {"word_index": 0, "scale": 1.15, "duration_ms": 500}
    with pytest.raises(ProposalValidationError) as exc:
        validate_edit_proposal(raw, transcript_word_count=0)
    assert "empty transcript" in str(exc.value)
