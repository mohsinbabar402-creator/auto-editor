import pytest
import json
import uuid
from pydantic import ValidationError

from review.models import StructuredReview, ReviewProblem, ReviewVerdict, parse_and_validate_gemini_review
from db.repository import DatabaseRepository


def test_valid_structured_review_pass():
    raw_json = """
    {
      "verdict": "PASS",
      "overall_score": 9.2,
      "scene_accuracy": 9.5,
      "instruction_accuracy": 9.0,
      "character_accuracy": 9.5,
      "timing_score": 9.0,
      "visual_quality": 9.0,
      "problems": [],
      "corrections": []
    }
    """
    review = parse_and_validate_gemini_review(raw_json)
    assert review.verdict == ReviewVerdict.PASS
    assert review.overall_score == 9.2
    assert len(review.problems) == 0
    assert len(review.corrections) == 0
    assert review.is_recovered is False


def test_valid_structured_review_fail_with_corrections():
    raw_json = """
    ```json
    {
      "verdict": "FAIL",
      "overall_score": 6.8,
      "scene_accuracy": 5.0,
      "instruction_accuracy": 6.0,
      "character_accuracy": 8.0,
      "timing_score": 7.0,
      "visual_quality": 7.0,
      "problems": [
        {
          "scene": 1,
          "type": "scene_accuracy",
          "description": "Expected the creator to gesture on emphasis, but hand is static."
        }
      ],
      "corrections": [
        "Retime punch-in zoom to start 40ms earlier at word boundary.",
        "Adjust scale from 1.10x to 1.20x."
      ]
    }
    ```
    """
    review = parse_and_validate_gemini_review(raw_json)
    assert review.verdict == ReviewVerdict.FAIL
    assert review.overall_score == 6.8
    assert len(review.problems) == 1
    assert review.problems[0].scene == 1
    assert "Expected the creator to gesture" in review.problems[0].description
    assert len(review.corrections) == 2
    assert review.is_recovered is False

    # Recoverable formatting variation (trailing comma)
    raw_trailing_comma = '{"verdict": "PASS", "overall_score": 8.0, "problems": [], "corrections": [],}'
    review_tc = parse_and_validate_gemini_review(raw_trailing_comma)
    assert review_tc.verdict == ReviewVerdict.PASS
    assert review_tc.is_recovered is False

    # Recoverable freeform critique (clearly marked as recovered)
    raw_freeform = "The framing is static and social handles are clipped off. Adjust punch-in framing scale to 1.22x."
    review_ff = parse_and_validate_gemini_review(raw_freeform)
    assert review_ff.verdict == ReviewVerdict.FAIL
    assert review_ff.is_recovered is True
    assert "freeform" in review_ff.recovery_reason.lower()
    assert len(review_ff.corrections) > 0


def test_invalid_verdict_rejected():
    # Structured JSON with invalid verdict
    raw_json = '{"verdict": "MAYBE", "overall_score": 7.0, "problems": [], "corrections": []}'
    with pytest.raises(Exception):
        parse_and_validate_gemini_review(raw_json)

    # Freeform critique with explicit invalid verdict
    raw_freeform = "The video was fine overall. Verdict: MAYBE. Please review."
    with pytest.raises(Exception):
        parse_and_validate_gemini_review(raw_freeform)


def test_out_of_bounds_score_rejected():
    # Structured JSON with out-of-bounds score
    raw_json = '{"verdict": "PASS", "overall_score": 15.0, "problems": [], "corrections": []}'
    with pytest.raises(Exception):
        parse_and_validate_gemini_review(raw_json)

    # Freeform with explicit out-of-bounds score
    raw_freeform = "Overall quality was decent. Score: 14.5/10."
    with pytest.raises(Exception):
        parse_and_validate_gemini_review(raw_freeform)

    # Empty text rejection
    with pytest.raises(Exception):
        parse_and_validate_gemini_review("")



def test_database_review_persistence():
    repo = DatabaseRepository()
    proj_id = f"proj_rev_{uuid.uuid4().hex[:6]}"
    repo.create_project(proj_id, "Review Test Proj", "Niche test")
    
    camp = repo.create_campaign(f"camp_{uuid.uuid4().hex[:6]}", proj_id, "Review Campaign")
    job = repo.create_job(f"job_{uuid.uuid4().hex[:6]}", camp["id"], "PRODUCTION_EDIT", {"test": True})
    
    rev_id = f"rev_{uuid.uuid4().hex[:8]}"
    review_record = repo.record_review(
        review_id=rev_id,
        job_id=job["id"],
        video_id=None,
        attempt=1,
        reviewer_type="gemini_browser",
        verdict="FAIL",
        overall_score=6.5,
        scores={"timing": 6.0, "visual": 7.0},
        problems=[{"scene": 1, "type": "timing", "description": "Too fast"}],
        corrections=["Extend punch-in duration by 200ms"],
        raw_response="Raw Gemini response text without CoT"
    )
    assert review_record["id"] == rev_id
    assert review_record["verdict"] == "FAIL"

    # Fetch reviews for job
    fetched_reviews = repo.get_reviews_for_job(job["id"])
    assert len(fetched_reviews) == 1
    assert fetched_reviews[0]["id"] == rev_id
    assert fetched_reviews[0]["corrections"] == ["Extend punch-in duration by 200ms"]
