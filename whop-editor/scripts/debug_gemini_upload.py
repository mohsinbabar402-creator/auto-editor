import io
import json
import logging
from pathlib import Path
import sys
import time

# Reconfigure stdout for UTF-8 in Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

# Project imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from review.models import parse_and_validate_gemini_review

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("debug_gemini_upload")

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
    logger.info("Launching visible Chrome window...")
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
    page.wait_for_timeout(5000)

    curr_url = page.url
    logger.info(f"Current URL: {curr_url}")

    initial_shot = SCREENSHOT_DIR / "gemini_debug_initial.png"
    page.screenshot(path=str(initial_shot))
    logger.info(f"Initial screenshot saved: {initial_shot}")

    # Verify if user is logged in
    user_avatar = page.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
    account_label = user_avatar.get_attribute("aria-label") if user_avatar else None
    logger.info(f"Account Avatar Detected: {account_label}")

    body_text = page.inner_text("body")
    needs_signin = "Sign in" in body_text and ("Sign in to try" in body_text or "Sign in with Google" in body_text)
    logger.info(f"Sign-in required text on page: {needs_signin}")

    # If prompt area needs focus to expand
    input_box = page.query_selector(
        'rich-textarea [contenteditable="true"], .ql-editor, [contenteditable="true"], textarea, rich-textarea'
    )
    if input_box:
        logger.info("Clicking chat input to expand toolbar...")
        input_box.click()
        page.wait_for_timeout(1000)

    # Locate the upload / tools button
    upload_selectors = [
        'button[aria-label*="Upload & tools" i]',
        'button[aria-label*="Upload" i]',
        'button[aria-label*="tools" i]',
        'button[aria-label*="Add files" i]',
        'button[aria-label*="add" i]',
        '.input-area button:first-child',
    ]

    upload_btn = None
    matched_selector = None
    for sel in upload_selectors:
        btn = page.query_selector(sel)
        if btn and btn.is_visible():
            upload_btn = btn
            matched_selector = sel
            break

    if not upload_btn:
        # Fallback: scan all buttons
        buttons = page.query_selector_all("button, [role='button']")
        for b in buttons:
            aria = (b.get_attribute("aria-label") or "").lower()
            if any(k in aria for k in ["upload", "tool", "add", "attachment", "file"]):
                if b.is_visible():
                    upload_btn = b
                    matched_selector = f"button[aria-label='{b.get_attribute('aria-label')}']"
                    break

    if not upload_btn:
        logger.error("FATAL: Could not locate upload button in DOM.")
        sys.exit(1)

    logger.info(f"Matched upload button: selector='{matched_selector}', aria='{upload_btn.get_attribute('aria-label')}'")

    # Click upload button to open menu
    upload_btn.click()
    page.wait_for_timeout(1500)

    menu_shot = SCREENSHOT_DIR / "gemini_debug_menu.png"
    page.screenshot(path=str(menu_shot))
    logger.info(f"Menu screenshot saved: {menu_shot}")

    # Inspect menu items
    menu_items = page.query_selector_all('[role="menuitem"], .mat-mdc-menu-item, [role="menu"] button, .menu-item')
    logger.info(f"Menu items count: {len(menu_items)}")
    upload_file_option = None
    for idx, mi in enumerate(menu_items):
        txt = (mi.inner_text() or "").strip().replace("\n", " ")
        aria = (mi.get_attribute("aria-label") or "").strip()
        disabled = mi.get_attribute("disabled") is not None or mi.get_attribute("aria-disabled") == "true"
        logger.info(f"  menu_item #{idx}: text='{txt}', aria='{aria}', disabled={disabled}")
        if ("upload files" in txt.lower() or "upload" in txt.lower()) and not disabled:
            upload_file_option = mi

    # Attach video file
    upload_success = False
    if upload_file_option:
        logger.info(f"Clicking active 'Upload files' option...")
        try:
            with page.expect_file_chooser(timeout=8000) as fc_info:
                upload_file_option.click()
            chooser = fc_info.value
            chooser.set_files(str(VIDEO_FILE))
            logger.info("File successfully set via Playwright file chooser!")
            upload_success = True
        except Exception as e:
            logger.warning(f"File chooser interaction failed: {e}")

    if not upload_success:
        # Check for mounted input[type="file"]
        file_inputs = page.query_selector_all('input[type="file"]')
        logger.info(f"Direct input[type='file'] elements available: {len(file_inputs)}")
        for fi in file_inputs:
            try:
                fi.set_input_files(str(VIDEO_FILE))
                logger.info("Direct input[type='file'].set_input_files succeeded!")
                upload_success = True
                break
            except Exception as e:
                logger.warning(f"Failed to set file on input: {e}")

    if not upload_success:
        logger.error("FATAL: Failed to attach video file.")
        ctx.close()
        sys.exit(1)

    logger.info("Waiting 8 seconds for video attachment chip to render in UI...")
    page.wait_for_timeout(8000)

    attached_shot = SCREENSHOT_DIR / "gemini_debug_attached.png"
    page.screenshot(path=str(attached_shot))
    logger.info(f"Attachment screenshot saved: {attached_shot}")

    # Confirm video attachment is visible
    attachment_elements = page.query_selector_all(
        '[aria-label*="video" i], [aria-label*="attachment" i], [aria-label*="file" i], '
        '.attachment-card, .file-preview, [data-test-id*="attachment"]'
    )
    logger.info(f"Detected attachment UI elements: {len(attachment_elements)}")

    # Enter review instructions into prompt box without removing attachment
    logger.info("Entering review prompt text...")
    prompt_el = page.query_selector(
        'rich-textarea [contenteditable="true"], .ql-editor, [contenteditable="true"], textarea'
    )
    if not prompt_el:
        prompt_el = page.query_selector('rich-textarea')

    assert prompt_el is not None, "Prompt input element not found!"
    prompt_el.click()
    page.wait_for_timeout(500)
    page.keyboard.insert_text(REVIEW_INSTRUCTION)
    page.wait_for_timeout(1500)

    # Click send button
    send_btn = page.query_selector(
        'button[aria-label*="Send prompt" i], button[aria-label*="Send" i], button.send-button'
    )
    if send_btn and send_btn.is_enabled():
        logger.info("Clicking Send button...")
        send_btn.click()
    else:
        logger.info("Pressing Enter to submit prompt...")
        page.keyboard.press("Enter")

    logger.info("Submitted prompt with video attachment to Gemini! Waiting for analysis...")

    # Wait for Gemini response to generate (watching for streaming and completion)
    page.wait_for_timeout(8000)
    for tick in range(45):
        stop_btn = page.query_selector('button[aria-label*="Stop" i]')
        if not stop_btn:
            logger.info(f"Stop button absent (tick {tick}). Response finalized.")
            break
        logger.info(f"Gemini analyzing video and generating response... (tick {tick})")
        time.sleep(2)

    page.wait_for_timeout(4000)
    response_shot = SCREENSHOT_DIR / "gemini_debug_response.png"
    page.screenshot(path=str(response_shot))
    logger.info(f"Response screenshot saved: {response_shot}")

    # Extract Gemini response text
    response_elements = page.query_selector_all(
        '.model-response-text, message-content, [data-message-author-role="model"], .response-content, model-response'
    )
    logger.info(f"Response elements found: {len(response_elements)}")

    raw_response_text = ""
    if response_elements:
        raw_response_text = response_elements[-1].inner_text().strip()
    else:
        body = page.inner_text("body")
        logger.info(f"Fallback page body text: {body[-600:]}")
        raw_response_text = body

    logger.info("=" * 65)
    logger.info("RAW GEMINI RESPONSE TEXT:")
    logger.info(raw_response_text)
    logger.info("=" * 65)

    assert raw_response_text, "Gemini response text is empty!"

    # Parse and validate structured review
    structured = parse_and_validate_gemini_review(raw_response_text)
    print("\n" + "=" * 65)
    print("STRUCTURED GEMINI REVIEW RESULT:")
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
    logger.info("CHECKPOINT VERIFIED: Gemini received video and returned structured review!")
