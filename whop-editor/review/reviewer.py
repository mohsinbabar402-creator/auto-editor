from abc import ABC, abstractmethod
import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional

from review.models import StructuredReview, parse_and_validate_gemini_review

logger = logging.getLogger("whop_editor.review")


class ReviewError(Exception):
    """Base review error."""
    pass


class GeminiAuthenticationRequiredError(ReviewError):
    """Raised when the dedicated Chrome profile is not authenticated with Gemini."""
    pass


class BaseVideoReviewer(ABC):
    """Abstract interface for reviewing rendered videos."""

    @abstractmethod
    def review_video(
        self,
        video_path: str | Path,
        scene_instructions: str,
        campaign_context: Optional[str] = None,
        job_id: Optional[str] = None,
        **kwargs
    ) -> StructuredReview:
        pass


class GeminiBrowserReviewer(BaseVideoReviewer):
    """
    Automates an authenticated Chrome profile to upload and review videos on Gemini Web.
    """

    def __init__(
        self,
        profile_dir: Optional[Path] = None,
        profile_id: Optional[str] = None,
        headless: bool = False,
        timeout_ms: int = 60000,
        db_repo: Optional[Any] = None
    ):
        from browser.gemini_reviewer import GeminiReviewer
        from browser.profile_registry import ProfileRegistry
        self.registry = ProfileRegistry()
        self.profile_id = profile_id or (profile_dir.name if profile_dir else "flow_profile_2")
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.reviewer = GeminiReviewer(
            registry=self.registry,
            headless=headless,
            timeout_ms=timeout_ms,
            db_repo=db_repo
        )

    def review_video(
        self,
        video_path: str | Path,
        scene_instructions: str,
        campaign_context: Optional[str] = None,
        job_id: Optional[str] = None,
        **kwargs
    ) -> StructuredReview:
        res = self.reviewer.review_video(
            video_path=video_path,
            profile_id=self.profile_id,
            scene_instructions=scene_instructions,
            campaign_context=campaign_context,
            job_id=job_id,
            **kwargs
        )
        return parse_and_validate_gemini_review(res["raw_response"])


class MockVideoReviewer(BaseVideoReviewer):
    """Deterministic reviewer for testing and offline development."""

    def __init__(self, should_pass: bool = True, custom_review: Optional[StructuredReview] = None):
        self.should_pass = should_pass
        self.custom_review = custom_review
        self.call_count = 0

    def review_video(
        self,
        video_path: str | Path,
        scene_instructions: str,
        campaign_context: Optional[str] = None,
        job_id: Optional[str] = None,
        **kwargs
    ) -> StructuredReview:
        self.call_count += 1
        if self.custom_review:
            return self.custom_review

        if self.should_pass:
            return StructuredReview(
                verdict="PASS",
                overall_score=10.0,
                scene_accuracy=10.0,
                instruction_accuracy=10.0,
                character_accuracy=9.0,
                timing_score=8.0,
                visual_quality=8.5,
                problems=[],
                corrections=[]
            )
        else:
            return StructuredReview(
                verdict="FAIL",
                overall_score=5.5,
                scene_accuracy=5.0,
                instruction_accuracy=6.0,
                character_accuracy=8.0,
                timing_score=5.0,
                visual_quality=7.0,
                problems=[
                    {
                        "scene": 1,
                        "type": "timing",
                        "description": "Punch-in zoom scale 1.15x held too briefly for conversational emphasis."
                    }
                ],
                corrections=[
                    "Increase zoom duration to 1100ms or adjust scale to 1.20x."
                ]
            )
