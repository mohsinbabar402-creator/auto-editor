import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import uuid

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from browser.profile_registry import ProfileRegistry, ProfileAuthStatus
from browser.gemini_launcher import GeminiLauncher
from review.models import StructuredReview, parse_and_validate_gemini_review

logger = logging.getLogger("whop_editor.gemini_reviewer")


class GeminiReviewError(Exception):
    """Base error for Gemini review operations."""
    pass


class GeminiAuthenticationRequiredError(GeminiReviewError):
    """Raised when authentication is missing on the profile."""
    pass


class GeminiReviewer:
    """
    Automated production reviewer that runs Gemini Web QA on rendered videos.
    Manages dynamic profile acquisition, Playwright Chrome lifecycle,
    DOM upload, policy modal agreement, prompt execution, and structured result extraction.
    """

    DEFAULT_PROMPT_TEMPLATE = (
        "Review this Whop short-form video as an independent QA editor. "
        "Watch the actual uploaded video. "
        "Check whether the visual edit is accurate to the source, whether the punch-in timing is natural, "
        "whether the framing is correct, whether anything visually incorrect or distracting was introduced, "
        "and whether the result is publishable. "
        "Return strict JSON with: verdict (PASS/FAIL), overall_score, problems, corrections."
    )

    def __init__(
        self,
        registry: Optional[ProfileRegistry] = None,
        headless: bool = False,
        timeout_ms: int = 45000,
        db_repo: Optional[Any] = None
    ):
        self.registry = registry or ProfileRegistry()
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.db_repo = db_repo

    def review_video(
        self,
        video_path: str | Path,
        profile_id: Optional[str] = None,
        scene_instructions: Optional[str] = None,
        campaign_context: Optional[str] = None,
        job_id: Optional[str] = None,
        attempt: int = 1
    ) -> Dict[str, Any]:
        """
        Executes an end-to-end hands-free video review.
        Returns dict containing verdict, overall_score, problems, corrections,
        profile_id, video_path, review_duration_seconds, and raw_response.
        """
        v_path = Path(video_path).resolve()
        if not v_path.exists():
            raise FileNotFoundError(f"Target video does not exist: {v_path}")

        # 1. Acquire eligible authenticated profile
        profile = self.registry.acquire_profile(capability="gemini", preferred_id=profile_id, lease_owner=job_id)
        if not profile:
            raise GeminiAuthenticationRequiredError(
                f"No authenticated browser profile available. Profile '{profile_id or 'flow_profile_2'}' requires authentication."
            )

        logger.info(f"Acquired profile: {profile.profile_id} (email: {profile.account_email})")

        t_start = time.time()
        raw_response = ""
        structured: Optional[StructuredReview] = None
        launch_result = "SUCCESS"
        auth_status = "AUTHENTICATED"

        with sync_playwright() as pw:
            ctx = None
            try:
                # 2. Launch persistent Chrome
                ctx, page = GeminiLauncher.launch_profile(
                    user_data_dir=profile.user_data_dir,
                    playwright_instance=pw,
                    headless=self.headless,
                    timeout_ms=self.timeout_ms
                )

                # 3. Open Gemini and verify session
                GeminiLauncher.open_gemini(page, timeout_ms=self.timeout_ms)
                is_auth, auth_info = GeminiLauncher.verify_gemini_session(page)
                if not is_auth:
                    auth_status = "AUTH_REQUIRED"
                    launch_result = "AUTH_FAILED"
                    self.registry.mark_auth_required(profile.profile_id)
                    raise GeminiAuthenticationRequiredError(
                        f"Profile '{profile.profile_id}' is not authenticated on Gemini. Status: {auth_info}"
                    )

                def dismiss_all_modals():
                    clicked = False
                    try:
                        for txt in ["Got it", "Agree", "Dismiss", "OK", "Not now", "Cancel"]:
                            btns = page.query_selector_all(f'button:has-text("{txt}"), div[role="button"]:has-text("{txt}")')
                            for b in btns:
                                if b.is_visible():
                                    logger.info(f"Dismissing modal '{txt}'...")
                                    try:
                                        b.click(force=True)
                                        page.wait_for_timeout(1000)
                                        clicked = True
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                    return clicked

                # Settle page & dismiss modals
                page.wait_for_timeout(3500)
                for _ in range(3):
                    if not dismiss_all_modals():
                        break

                # 4. Upload Video
                logger.info(f"Locating upload control for: {v_path.name} ({v_path.stat().st_size} bytes)...")

                def find_upload_button():
                    selectors = [
                        'button[aria-label*="Upload" i]',
                        'button[aria-label*="tools" i]',
                        'button[aria-label*="Add files" i]',
                        'button[aria-label*="Open tools" i]',
                        'button[aria-label*="Attach" i]',
                        'button:has(mat-icon:has-text("add"))',
                        'button:has(mat-icon:has-text("plus"))',
                    ]
                    for attempt in range(15):
                        for sel in selectors:
                            btn = page.query_selector(sel)
                            if btn and btn.is_visible():
                                return btn
                        if attempt == 3:
                            try:
                                prompt_box = page.locator('rich-textarea [contenteditable="true"], .ql-editor, [contenteditable="true"], [role="textbox"]').first
                                if prompt_box.is_visible():
                                    prompt_box.click(force=True)
                            except Exception:
                                pass
                        if attempt == 7:
                            new_chat = page.query_selector('button[aria-label*="New chat" i], a[aria-label*="New chat" i]')
                            if new_chat and new_chat.is_visible():
                                try:
                                    new_chat.click(force=True)
                                except Exception:
                                    pass
                        page.wait_for_timeout(1000)
                    return None

                up_btn = find_upload_button()
                if not up_btn:
                    ss_path = Path("whop-editor/data/analysis/gemini_upload_btn_missing.png")
                    page.screenshot(path=str(ss_path))
                    logger.warning(f"Saved diagnostic screenshot to: {ss_path}")
                    raise GeminiReviewError("Could not locate Upload & tools button in DOM.")

                logger.info(f"Found upload button: {up_btn.get_attribute('aria-label')}. Clicking...")
                up_btn.click()
                page.wait_for_timeout(1500)

                attached = False
                # 1. Primary path: Locate and click 'Upload files' menu item with Playwright file chooser
                upload_item = page.locator('button:has-text("Upload files"), [role="menuitem"]:has-text("Upload files"), [aria-label*="Upload files" i]').first
                for _ in range(4):
                    if upload_item.is_visible():
                        break
                    page.wait_for_timeout(1000)

                if not upload_item.is_visible():
                    logger.info("Upload menu item not immediately visible, re-clicking upload button...")
                    up_btn = find_upload_button()
                    if up_btn:
                        up_btn.click()
                        page.wait_for_timeout(1500)

                if upload_item.is_visible():
                    logger.info("Found 'Upload files' menu item. Attaching via file chooser...")
                    try:
                        with page.expect_file_chooser(timeout=8000) as fc_info:
                            upload_item.click()
                        fc_info.value.set_files(str(v_path))
                        attached = True
                        logger.info("Attached video via file chooser.")
                    except Exception as e:
                        logger.warning(f"File chooser wait/set_files: {e}")

                # 2. Fallback path: Direct input[type='file']
                if not attached:
                    file_inputs = page.query_selector_all('input[type="file"]')
                    logger.info(f"Checking direct input[type='file'] elements (count: {len(file_inputs)})...")
                    for fi in file_inputs:
                        try:
                            fi.set_input_files(str(v_path))
                            attached = True
                            logger.info("Attached video via direct file input.")
                            break
                        except Exception as e:
                            logger.warning(f"set_input_files failed on input: {e}")

                if not attached:
                    ss_path = Path("whop-editor/data/analysis/gemini_menu_missing.png")
                    page.screenshot(path=str(ss_path))
                    logger.warning(f"Saved upload failure screenshot to: {ss_path}")
                    raise GeminiReviewError("Failed to attach video to file inputs.")

                # Dismiss immediate policy modal if present
                page.wait_for_timeout(2000)
                for _ in range(3):
                    if dismiss_all_modals():
                        page.wait_for_timeout(1000)

                # Wait for video attachment chip
                logger.info("Waiting for video thumbnail chip to render...")
                page.wait_for_timeout(4000)

                # 5. Type review instructions
                json_instructions = (
                    "\n\nCRITICAL REVIEW INSTRUCTION:\n"
                    "You are an independent QA reviewer evaluating this short-form video.\n"
                    "Evaluate visual editing, punch-in framing, timing, and quality.\n"
                    "You MUST respond ONLY with a valid JSON block enclosed in ```json ... ``` with this exact structure:\n"
                    "{\n"
                    '  "verdict": "PASS" or "FAIL",\n'
                    '  "overall_score": 0.0 to 10.0,\n'
                    '  "scene_accuracy": 0.0 to 10.0,\n'
                    '  "timing_score": 0.0 to 10.0,\n'
                    '  "visual_quality": 0.0 to 10.0,\n'
                    '  "problems": [\n'
                    '    {"severity": "MODERATE", "description": "issue description"}\n'
                    '  ],\n'
                    '  "corrections": ["actionable correction 1", "actionable correction 2"]\n'
                    "}"
                )
                prompt_text = (scene_instructions or self.DEFAULT_PROMPT_TEMPLATE) + json_instructions
                if campaign_context:
                    prompt_text += f"\nCampaign Context: {campaign_context}"

                logger.info("Inserting review prompt instructions...")
                input_field = page.locator('rich-textarea [contenteditable="true"], .ql-editor, [contenteditable="true"]').first
                input_field.click(force=True)
                page.wait_for_timeout(500)
                page.keyboard.insert_text(prompt_text)
                page.wait_for_timeout(1500)

                # 6. Submit prompt
                logger.info("Submitting prompt to Gemini...")
                send_btn = page.locator('button[aria-label*="Send prompt" i], button[aria-label*="Send" i], button.send-button').first
                send_btn.click(force=True)
                page.wait_for_timeout(2500)

                # 7. Check and dismiss post-send 'A reminder about creating videos' [Agree] modal
                for _ in range(5):
                    if dismiss_all_modals():
                        page.wait_for_timeout(1500)
                        break
                    page.wait_for_timeout(1000)

                logger.info("Prompt submitted. Waiting for Gemini video analysis and streaming response...")

                # 8. Poll for response completion
                for tick in range(60): # Up to 3 minutes
                    page.wait_for_timeout(3000)
                    dismiss_all_modals()

                    resps = page.query_selector_all(
                        '.model-response-text, message-content, [data-message-author-role="model"], .response-content'
                    )
                    stop_btn = page.query_selector('button[aria-label*="Stop" i]')

                    if resps:
                        txt = resps[-1].inner_text().strip()
                        if len(txt) > 50 and not stop_btn and tick > 2:
                            logger.info(f"Gemini response completed at tick {tick}! ({len(txt)} chars)")
                            raw_response = txt
                            break

                    if tick % 5 == 0:
                        logger.info(f"  [tick {tick}/60] streaming={stop_btn is not None}, responses_found={len(resps)}")

                if not raw_response:
                    resps = page.query_selector_all(
                        '.model-response-text, message-content, [data-message-author-role="model"], .response-content'
                    )
                    if resps:
                        raw_response = resps[-1].inner_text().strip()
                    else:
                        raw_response = page.inner_text("body")

                if not raw_response:
                    raise GeminiReviewError("Gemini response is empty.")

                logger.info("Parsing and validating structured review...")
                structured = parse_and_validate_gemini_review(raw_response)

            except Exception as e:
                launch_result = "ERROR"
                logger.error(f"Gemini review execution error: {e}")
                raise
            finally:
                if ctx:
                    GeminiLauncher.close_context(ctx)
                self.registry.release_profile(
                    profile_id=profile.profile_id,
                    success=(launch_result == "SUCCESS"),
                    is_gemini_review=True
                )

        duration = round(time.time() - t_start, 2)

        # 9. Audit to PostgreSQL if repository provided
        review_id = f"rev_{uuid.uuid4().hex[:12]}"
        if self.db_repo and job_id:
            try:
                self.db_repo.record_review(
                    review_id=review_id,
                    job_id=job_id,
                    video_id=None,
                    attempt=attempt,
                    reviewer_type="gemini_browser",
                    verdict=structured.verdict,
                    overall_score=structured.overall_score,
                    scores={
                        "overall": structured.overall_score,
                        "scene_accuracy": structured.scene_accuracy or 0.0,
                        "timing_score": structured.timing_score or 0.0,
                        "visual_quality": structured.visual_quality or 0.0,
                        "profile_id": profile.profile_id,
                        "browser_launch_result": launch_result,
                        "auth_status": auth_status,
                        "duration_seconds": duration
                    },
                    problems=[p.model_dump() if hasattr(p, "model_dump") else (p if isinstance(p, dict) else str(p)) for p in structured.problems],
                    corrections=structured.corrections,
                    raw_response=raw_response
                )
                logger.info(f"Audit record persisted in PostgreSQL: review_id={review_id}")
            except Exception as e:
                logger.warning(f"Could not persist review to PostgreSQL: {e}")

        return {
            "review_id": review_id,
            "verdict": structured.verdict,
            "overall_score": structured.overall_score,
            "problems": [p.description if hasattr(p, "description") else str(p) for p in structured.problems],
            "corrections": structured.corrections,
            "raw_response": raw_response,
            "profile_id": profile.profile_id,
            "video_path": str(v_path),
            "review_duration_seconds": duration,
            "auth_status": auth_status
        }
