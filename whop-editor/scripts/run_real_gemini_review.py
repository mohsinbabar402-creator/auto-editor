import json
import logging
from pathlib import Path
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from review.models import parse_and_validate_gemini_review

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("real_gemini_review")

PROFILE_DIR = Path("browser/flow_profile_2").resolve()
VIDEO_FILE = Path("whop-editor/data/output/whop_campaign_final_approved.mp4").resolve()
SCREENSHOT_DIR = Path("whop-editor/data/analysis")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

REVIEW_INSTRUCTION = (
    "Review this Whop short-form video as an independent QA editor. "
    "Watch the actual uploaded video. "
    "Check whether the visual edit is accurate to the source, whether the punch-in timing is natural, "
    "whether the framing is correct, whether anything visually incorrect or distracting was introduced, "
    "and whether the result is publishable. "
    "Return strict JSON with: verdict (PASS/FAIL), overall_score, problems, corrections."
)

logger.info(f"Target profile: {PROFILE_DIR}")
logger.info(f"Target video: {VIDEO_FILE} ({VIDEO_FILE.stat().st_size} bytes)")
assert VIDEO_FILE.exists(), f"Video file not found: {VIDEO_FILE}"

with sync_playwright() as pw:
    logger.info("Launching Chrome with authenticated profile...")
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check"
        ],
        viewport={"width": 1280, "height": 900}
    )

    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    logger.info("Navigating to https://gemini.google.com/app ...")
    page.goto("https://gemini.google.com/app", timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    def dismiss_modals():
        clicked = False
        try:
            for txt in ["Got it", "Agree", "Dismiss", "OK"]:
                btns = page.query_selector_all(f'button:has-text("{txt}")')
                for b in btns:
                    if b.is_visible():
                        logger.info(f"Dismissing modal button '{txt}'...")
                        b.click(force=True)
                        page.wait_for_timeout(1000)
                        clicked = True
        except Exception:
            pass
        return clicked

    dismiss_modals()

    # 1. Click '+' Upload & tools directly
    logger.info("Clicking '+' Upload & tools button...")
    plus_btn = page.query_selector('button[aria-label*="Upload & tools" i], button[aria-label*="Add files" i]')
    if not plus_btn:
        logger.info("Focusing prompt area to expose '+' button...")
        page.locator('rich-textarea [contenteditable="true"], .ql-editor, [contenteditable="true"]').first.click(force=True)
        page.wait_for_timeout(1000)
        plus_btn = page.query_selector('button[aria-label*="Upload & tools" i], button[aria-label*="Add files" i]')

    assert plus_btn is not None, "Could not locate Upload & tools button"
    plus_btn.click(force=True)
    page.wait_for_timeout(2000)

    # 2. Attach video file
    upload_success = False
    
    # Check if 'Upload files' menu item is visible
    upload_item = page.query_selector('[role="menuitem"]:has-text("Upload files"), button:has-text("Upload files"), .mat-mdc-menu-item:has-text("Upload files")')
    if upload_item:
        logger.info("Clicking 'Upload files' menu item with file chooser...")
        try:
            with page.expect_file_chooser(timeout=5000) as fc_info:
                upload_item.click(force=True)
            chooser = fc_info.value
            chooser.set_files(str(VIDEO_FILE))
            logger.info("File attached via file chooser!")
            upload_success = True
        except Exception as e:
            logger.warning(f"File chooser wait: {e}")

    if not upload_success:
        # Check for mounted input[type="file"]
        file_inputs = page.query_selector_all('input[type="file"]')
        logger.info(f"Direct file inputs count: {len(file_inputs)}")
        if file_inputs:
            for fi in file_inputs:
                try:
                    fi.set_input_files(str(VIDEO_FILE))
                    logger.info("Direct input[type='file'].set_input_files succeeded!")
                    upload_success = True
                    break
                except Exception as e:
                    logger.warning(f"set_input_files failed: {e}")

    assert upload_success, "FATAL: Could not attach video file."

    page.wait_for_timeout(2000)
    dismiss_modals()

    logger.info("Waiting for video thumbnail chip to render...")
    page.wait_for_timeout(5000)
    dismiss_modals()

    attached_shot = SCREENSHOT_DIR / "real_gemini_video_attached.png"
    page.screenshot(path=str(attached_shot))
    logger.info(f"Attached screenshot saved: {attached_shot}")

    # 3. Type review prompt using force=True
    logger.info("Entering QA review instruction into prompt box...")
    prompt_input = page.locator('rich-textarea [contenteditable="true"], .ql-editor, [contenteditable="true"]').first
    prompt_input.click(force=True)
    page.wait_for_timeout(500)
    page.keyboard.insert_text(REVIEW_INSTRUCTION)
    page.wait_for_timeout(1500)

    # 4. Submit prompt
    logger.info("Submitting prompt...")
    send_btn = page.locator('button[aria-label*="Send prompt" i], button[aria-label*="Send" i], button.send-button, .send-button').first
    if send_btn.is_visible():
        send_btn.click(force=True)
    else:
        page.keyboard.press("Enter")

    page.wait_for_timeout(2000)
    # Check if 'A reminder about creating videos' [Agree] appeared after sending
    if dismiss_modals():
        page.wait_for_timeout(1500)
        # Re-send if needed
        if send_btn.is_visible():
            logger.info("Re-clicking Send button after modal dismissal...")
            send_btn.click(force=True)

    logger.info("Waiting for Gemini to watch video and generate review response...")

    # 5. Poll until response is generated
    raw_response_text = ""
    for tick in range(90):
        page.wait_for_timeout(3000)
        dismiss_modals()
        
        # Check for streaming stop button
        stop_btn = page.query_selector('button[aria-label*="Stop" i]')
        
        # Check for model responses
        resps = page.query_selector_all('.model-response-text, message-content, [data-message-author-role="model"], .response-content')
        if resps:
            last_text = resps[-1].inner_text().strip()
            if last_text and not stop_btn and tick > 2:
                logger.info(f"Gemini response finalized at tick {tick}! ({len(last_text)} chars)")
                raw_response_text = last_text
                break
        
        if tick % 5 == 0:
            logger.info(f"  [tick {tick}/90] streaming={stop_btn is not None}, responses_found={len(resps)}")

    response_shot = SCREENSHOT_DIR / "real_gemini_response.png"
    page.screenshot(path=str(response_shot))
    logger.info(f"Response screenshot saved: {response_shot}")

    if not raw_response_text:
        body = page.inner_text("body")
        logger.info(f"Extracting fallback response from body...")
        raw_response_text = body

    logger.info("=" * 65)
    logger.info("RAW GEMINI REVIEW RESPONSE:")
    logger.info(raw_response_text)
    logger.info("=" * 65)

    assert raw_response_text, "Gemini returned empty response!"

    structured = parse_and_validate_gemini_review(raw_response_text)
    print("\n" + "=" * 65)
    print("STRUCTURED GEMINI VIDEO REVIEW RESULT:")
    print(f"Verdict:       {structured.verdict}")
    print(f"Overall Score: {structured.overall_score}/10")
    print(f"Scene Acc:     {structured.scene_accuracy}")
    print(f"Timing Score:  {structured.timing_score}")
    print(f"Visual Qual:   {structured.visual_quality}")
    print(f"Problems ({len(structured.problems)}):")
    for p in structured.problems:
        print(f"  - [{p.type}] Scene {p.scene}: {p.description}")
    print(f"Corrections ({len(structured.corrections)}):")
    for c in structured.corrections:
        print(f"  - {c}")
    print("=" * 65 + "\n")

    ctx.close()
    logger.info("TEST COMPLETE: Real video analyzed by Gemini!")
