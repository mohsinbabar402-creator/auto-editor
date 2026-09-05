"""
Persistent Browser Automation Worker for Google Flow / Veo
Uses Playwright with a dedicated, isolated persistent browser profile.
Operates entirely inside the browser DOM without taking over desktop mouse or keyboard.

Updated for the new Google Flow project-based UI (2026):
  Flow Home -> New Project -> Chat Prompt -> Generate -> Download
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from playwright.sync_api import sync_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config

FLOW_URL = "https://labs.google/fx/tools/flow"


def get_browser_context(playwright_instance, profile_dir: Path, headless: bool = False) -> BrowserContext:
    """Launches Chrome with persistent context using the real Chrome channel.
    Allows full DPAPI cookie decryption and bypasses Google bot-detection blocks."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized"
    ]
    
    context = playwright_instance.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        channel="chrome",
        headless=headless,
        args=launch_args,
        viewport={"width": 1280, "height": 900},
        accept_downloads=True
    )
        
    return context


def run_first_time_setup(profile_dir: Optional[Path] = None):
    """
    First-run interactive setup:
    Pre-syncs existing Google sessions from your real Chrome profile,
    then launches Google Flow to confirm authentication and credits.
    """
    target_profile = profile_dir or config.BROWSER_PROFILE_DIR
    target_profile.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(" GOOGLE FLOW BROWSER PROFILE SETUP")
    print("=" * 60)

    # Automatically clone active Chrome cookies/session into target profile
    try:
        from sync_all_chrome_profiles_to_flow import sync_all
        print("\n[0/3] Auto-syncing active Google session from your Chrome...")
        sync_all()
    except Exception as e:
        print(f"[Notice] Auto-sync: {e}")

    print(f"\n[1/3] Launching dedicated browser profile at:")
    print(f"      {target_profile}")
    print("\n[2/3] Opening Google Flow...")
    print("      - Your Google session is pre-authenticated directly from Chrome.")
    print("      - Confirm you can see your Google Flow studio / credits.")

    with sync_playwright() as p:
        context = get_browser_context(p, target_profile, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        
        try:
            page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[Notice] Page navigation: {e}")

        print("\n" + "-" * 60)
        input("Press ENTER when you have successfully logged in and are on Google Flow...")
        print("-" * 60)

        context.close()

    print("\n[3/3] Setup complete!")
    print(f"      Authenticated browser profile saved to: {target_profile}")
    print("      Future pipeline runs will automatically reuse this session.")
    print("=" * 60 + "\n")


def check_authentication(page: Page) -> bool:
    """Verifies whether the current page session is authenticated in Google Flow."""
    try:
        if "accounts.google.com" in page.url:
            return False
        # Check for PRO badge or user avatar - indicates logged in
        pro_btn = page.locator('button:has-text("PRO")').first
        if pro_btn.is_visible(timeout=3000):
            return True
        return True
    except Exception:
        return True


def navigate_to_project_editor(page: Page) -> bool:
    """
    Navigates from Flow home to a project editor where the prompt input is available.
    Flow UI: Home -> Click 'New project' -> Wait for editor to load
    """
    print("[Browser] Navigating to Google Flow...", flush=True)
    page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    
    # Check if we're already in a project (URL contains /project/)
    if "/project/" in page.url:
        print("[Browser] Already in a project editor.", flush=True)
        return True
    
    # Click "New project" button
    print("[Browser] Creating new project...", flush=True)
    new_proj_btn = page.locator('button:has-text("New project"), a:has-text("New project")').first
    try:
        new_proj_btn.click(timeout=10000)
    except Exception as e:
        print(f"[Browser] Could not find 'New project' button: {e}", flush=True)
        return False
    
    # Wait for the project editor to fully load (the "Loading..." screen)
    print("[Browser] Waiting for project editor to load...", flush=True)
    
    # Wait up to 30 seconds for the editor to appear
    for i in range(30):
        page.wait_for_timeout(1000)
        # Check if the chat prompt input has appeared
        chat_input = page.locator('[contenteditable="true"]').first
        try:
            if chat_input.is_visible(timeout=1000):
                print(f"[Browser] Project editor loaded! URL: {page.url}", flush=True)
                return True
        except:
            pass
        # Also check for "What do you want to create" text
        try:
            placeholder = page.locator('text="What do you want to create"')
            if placeholder.is_visible(timeout=500):
                print(f"[Browser] Project editor loaded! URL: {page.url}", flush=True)
                return True
        except:
            pass
    
    print("[Browser] Project editor did not load in time.", flush=True)
    return False


def find_chat_input(page: Page):
    """Finds the chat prompt input in the Flow project editor.
    This is the 'What do you want to create?' contenteditable div at the bottom."""
    
    # Try contenteditable div first (the chat input)
    try:
        # Look for visible contenteditable elements
        editables = page.locator('[contenteditable="true"]').all()
        for el in editables:
            try:
                if el.is_visible(timeout=1000):
                    return el
            except:
                continue
    except:
        pass
    
    # Try textarea fallback
    try:
        ta = page.locator('textarea').first
        if ta.is_visible(timeout=2000):
            return ta
    except:
        pass
    
    return None


def find_send_button(page: Page):
    """Finds the send/submit button in the chat interface.
    It's the arrow button (->)  next to the prompt input."""
    
    # The send button is typically the last button near the input area
    selectors = [
        'button[aria-label*="Send" i]',
        'button[aria-label*="Submit" i]',
        'button:has-text("arrow_forward")',  # Material icon name
        'button:has-text("send")',
    ]
    
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                return btn
        except:
            continue
    
    # Fallback: find the last visible button near the bottom of the chat panel
    # The send button is at the bottom-right of the chat panel
    try:
        # Look for arrow icon button
        btns = page.locator('button').all()
        for btn in reversed(btns):
            try:
                if btn.is_visible():
                    text = btn.inner_text().strip().lower()
                    if text in ['arrow_forward', 'send', '']:
                        bbox = btn.bounding_box()
                        if bbox and bbox['y'] > 700:  # Near bottom of page
                            return btn
            except:
                continue
    except:
        pass
    
    return None


def generate_single_scene(
    page: Page,
    scene_info: Dict[str, Any],
    clips_dir: Path,
    max_wait_sec: int = 300,
    retry_count: int = 3
) -> bool:
    """
    Automates the generation and download of a single scene in the Flow project editor:
    1. Types prompt into the chat input
    2. Clicks send/submit
    3. Waits for video to render
    4. Downloads and validates the MP4 file
    """
    sc_num = scene_info.get("scene_number", 1)
    sc_name = scene_info.get("scene_name", f"Scene {sc_num}")
    prompt_text = scene_info.get("veo_prompt", "")
    target_filename = scene_info.get("target_filename", f"scene_{sc_num:02d}.mp4")
    target_path = clips_dir / target_filename
    temp_download_path = clips_dir / f".temp_{target_filename}"

    print(f"\n[{'='*50}]", flush=True)
    print(f"[Scene {sc_num}] {sc_name}", flush=True)
    print(f"   Target: {target_filename}", flush=True)
    print(f"[{'='*50}]", flush=True)

    # Prepend instruction to generate video specifically
    video_prompt = f"Generate a cinematic video: {prompt_text}"

    for attempt in range(1, retry_count + 1):
        try:
            if attempt > 1:
                print(f"[Scene {sc_num}] Retry {attempt}/{retry_count}...", flush=True)
                page.wait_for_timeout(3000)

            # 1. Find the chat input
            input_el = find_chat_input(page)
            if not input_el:
                print(f"[Scene {sc_num}] Could not find chat input field.", flush=True)
                # Try taking a screenshot for debugging
                page.screenshot(path=str(clips_dir.parent / f"debug_scene{sc_num}_attempt{attempt}.png"))
                continue

            # 2. Enter prompt into chat
            print(f"[Scene {sc_num}] Entering prompt into chat...", flush=True)
            input_el.click()
            page.wait_for_timeout(300)
            
            # Clear any existing text first
            input_el.press("Control+a")
            page.wait_for_timeout(100)
            
            # Type the prompt (using keyboard to handle contenteditable)
            page.keyboard.type(video_prompt, delay=10)
            page.wait_for_timeout(500)

            # 3. Submit the prompt
            send_btn = find_send_button(page)
            if send_btn:
                print(f"[Scene {sc_num}] Clicking send button...", flush=True)
                send_btn.click()
            else:
                print(f"[Scene {sc_num}] Pressing Enter to submit...", flush=True)
                page.keyboard.press("Enter")

            # 4. Wait for generation to complete
            print(f"[Scene {sc_num}] Waiting for video generation...", flush=True)
            start_time = time.time()
            generation_finished = False
            approved_already = False
            video_el = None
            download_btn = None

            while (time.time() - start_time) < max_wait_sec:
                page.wait_for_timeout(3000)
                elapsed = int(time.time() - start_time)

                # Check for and click credit approval/confirmation buttons (ONCE per scene)
                if not approved_already:
                    approve_targets = [
                        'text="Approve, do not ask again"',
                        'text="Approve"',
                        'button:has-text("Approve, do not ask again")',
                        'button:has-text("Approve")',
                        '[role="button"]:has-text("Approve")',
                        'div:has-text("Approve, do not ask again")',
                        'div:has-text("Approve")',
                    ]
                    for sel in approve_targets:
                        try:
                            loc = page.locator(sel)
                            if loc.count() > 0:
                                target_btn = loc.last
                                if target_btn.is_visible(timeout=500):
                                    print(f"[Scene {sc_num}] Credit confirmation detected. Clicking '{sel}'...", flush=True)
                                    target_btn.click(force=True)
                                    approved_already = True
                                    page.wait_for_timeout(2000)
                                    break
                        except:
                            pass

                # If video card is visible, click it to open the player / reveal download button
                if elapsed >= 30:
                    card_selectors = [
                        'button[aria-label*="Play" i]',
                        'button:has-text("play_arrow")',
                        'div:has(> img[src*="googleusercontent"])',
                        'img[src*="googleusercontent"]',
                    ]
                    for sel in card_selectors:
                        try:
                            loc = page.locator(sel)
                            if loc.count() > 0:
                                loc.first.click(force=True)
                                page.wait_for_timeout(1000)
                                break
                        except:
                            pass

                # Check for download button (on page, modal, or action bar)
                dl_selectors = [
                    'button:has-text("Download")',
                    'a:has-text("Download")',
                    '[aria-label*="Download" i]',
                    'a[download]',
                    'button[title*="Download" i]',
                    'button:has-text("download")',
                    'button:has-text("file_download")',
                    '[data-tooltip*="Download" i]',
                ]
                for sel in dl_selectors:
                    try:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            for btn in loc.all():
                                if btn.is_visible(timeout=500):
                                    download_btn = btn
                                    generation_finished = True
                                    break
                        if generation_finished:
                            break
                    except:
                        pass

                if generation_finished:
                    break

                # Check for video element with valid src
                try:
                    vids = page.locator('video').all()
                    for vid in vids:
                        try:
                            if vid.is_visible(timeout=1000):
                                src = vid.get_attribute("src")
                                if src and len(src) > 10:
                                    video_el = vid
                                    generation_finished = True
                                    break
                        except:
                            pass
                except:
                    pass

                if generation_finished:
                    break

                if elapsed % 15 == 0:
                    print(f"   Generating... ({elapsed}s elapsed)", flush=True)
                    page.screenshot(path=str(clips_dir.parent / f"progress_scene{sc_num}_{elapsed}s.png"))

            if not generation_finished:
                print(f"[Scene {sc_num}] Timed out after {max_wait_sec}s.", flush=True)
                page.screenshot(path=str(clips_dir.parent / f"timeout_scene{sc_num}.png"))
                continue

            print(f"[Scene {sc_num}] Generation complete! Downloading...", flush=True)

            # 5. Handle Download
            if temp_download_path.exists():
                temp_download_path.unlink()

            download_success = False

            # Try clicking download button
            if download_btn:
                try:
                    with page.expect_download(timeout=30000) as download_info:
                        download_btn.click()
                    download = download_info.value
                    download.save_as(str(temp_download_path))
                    download_success = True
                except Exception as dl_err:
                    print(f"[Scene {sc_num}] Download button failed: {dl_err}", flush=True)

            # Fallback: stream capture from video src
            if not download_success and video_el:
                try:
                    src_url = video_el.get_attribute("src")
                    if src_url and src_url.startswith("http"):
                        import requests
                        cookies = page.context.cookies()
                        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                        headers = {"Cookie": cookie_str}
                        res = requests.get(src_url, headers=headers, stream=True, timeout=60)
                        with open(temp_download_path, "wb") as f:
                            for chunk in res.iter_content(chunk_size=16384):
                                f.write(chunk)
                        download_success = True
                    elif src_url and src_url.startswith("blob:"):
                        # For blob URLs, try right-click save or JavaScript extraction
                        print(f"[Scene {sc_num}] Video uses blob URL, attempting JS extraction...", flush=True)
                        # Try to find a direct download link in nearby elements
                        nearby_links = page.locator('a[href*=".mp4"], a[download]').all()
                        for link in nearby_links:
                            try:
                                href = link.get_attribute("href")
                                if href and href.startswith("http"):
                                    res = requests.get(href, stream=True, timeout=60)
                                    with open(temp_download_path, "wb") as f:
                                        for chunk in res.iter_content(chunk_size=16384):
                                            f.write(chunk)
                                    download_success = True
                                    break
                            except:
                                pass
                except Exception as stream_err:
                    print(f"[Scene {sc_num}] Stream capture failed: {stream_err}", flush=True)

            # 6. Verify and Rename
            if temp_download_path.exists():
                file_size = temp_download_path.stat().st_size
                if file_size > 50000:  # Valid MP4 (>50KB)
                    if target_path.exists():
                        target_path.unlink()
                    temp_download_path.rename(target_path)
                    print(f"[Scene {sc_num}] SUCCESS: {target_filename} ({file_size // 1024} KB)", flush=True)

                    # Return back to canvas editor by clicking "Done"
                    try:
                        done_btn = page.locator('button:has-text("Done"), button:has-text("Back to projects"), button:has-text("arrow_back")').first
                        if done_btn.is_visible(timeout=1000):
                            done_btn.click(force=True)
                            page.wait_for_timeout(2000)
                    except:
                        pass

                    return True
                else:
                    print(f"[Scene {sc_num}] File too small ({file_size} bytes). Discarding.", flush=True)
                    temp_download_path.unlink(missing_ok=True)
            else:
                print(f"[Scene {sc_num}] File not found after download.", flush=True)

        except Exception as err:
            print(f"[Scene {sc_num}] Error: {err}", flush=True)
            page.wait_for_timeout(2000)

    print(f"[Scene {sc_num}] FAILED after {retry_count} attempts.", flush=True)
    return False


def load_flow_state(state_file: Path) -> Dict[str, Any]:
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"completed_scenes": [], "failed_scenes": [], "current_scene": 1}


def save_flow_state(state_file: Path, state_data: Dict[str, Any]):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)


def generate_all_flow_clips(
    prompts_path: Path,
    clips_dir: Path,
    browser_profile_dir: Optional[Path] = None,
    headless: bool = False,
    timeout_sec: int = 300
) -> Dict[str, Any]:
    """
    Main entry point for Google Flow browser clip generation:
    1. Loads Stage 2 prompt JSON
    2. Opens dedicated browser profile
    3. Creates a new Flow project
    4. Iterates through missing/pending scenes
    5. Saves all validated clips to clips/scene_XX.mp4
    """
    if not prompts_path.exists():
        raise FileNotFoundError(f"Prompts file not found: {prompts_path}")

    with open(prompts_path, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    clips_dir.mkdir(parents=True, exist_ok=True)
    target_profile = browser_profile_dir or config.BROWSER_PROFILE_DIR
    state_file = clips_dir.parent / "flow_state.json"
    state = load_flow_state(state_file)

    print("\n" + "=" * 60, flush=True)
    print("GOOGLE FLOW PERSISTENT BROWSER WORKER", flush=True)
    print("=" * 60, flush=True)
    print(f"  Profile: {target_profile}", flush=True)
    print(f"  Scenes: {len(prompts)}", flush=True)
    print(f"  Clips Dir: {clips_dir}", flush=True)

    # Check for existing completed clips (Resume check)
    completed = []
    pending = []

    for pr in prompts:
        sc_num = pr["scene_number"]
        t_file = clips_dir / pr["target_filename"]
        if t_file.exists() and t_file.stat().st_size > 500000:
            completed.append(sc_num)
            print(f"  [OK] Scene {sc_num} exists ({t_file.stat().st_size // 1024} KB) -> Skip", flush=True)
        else:
            pending.append(pr)

    state["completed_scenes"] = completed
    save_flow_state(state_file, state)

    if not pending:
        print("\nAll scenes already generated!", flush=True)
        print("=" * 60 + "\n", flush=True)
        return {"success": True, "completed": completed, "failed": []}

    print(f"\n[Browser] Launching browser ({len(pending)} scenes pending)...", flush=True)

    with sync_playwright() as p:
        context = get_browser_context(p, target_profile, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()

        # Navigate to Flow and open project editor
        if not navigate_to_project_editor(page):
            print("[Browser] FATAL: Could not open project editor.", flush=True)
            page.screenshot(path=str(clips_dir.parent / "fatal_no_editor.png"))
            context.close()
            return {"success": False, "completed": completed, "failed": [pr["scene_number"] for pr in pending]}

        # Check authentication
        if not check_authentication(page):
            print("\n" + "!" * 60, flush=True)
            print("AUTHENTICATION REQUIRED", flush=True)
            print("Run: python browser_setup.py (or the OPEN_FLOW_BROWSER.bat)", flush=True)
            print("!" * 60, flush=True)
            context.close()
            return {"success": False, "completed": completed, "failed": [pr["scene_number"] for pr in pending]}

        # Process pending scenes
        failed = []
        for prompt_info in pending:
            sc_num = prompt_info["scene_number"]
            state["current_scene"] = sc_num
            save_flow_state(state_file, state)

            success = generate_single_scene(
                page=page,
                scene_info=prompt_info,
                clips_dir=clips_dir,
                max_wait_sec=timeout_sec
            )

            if success:
                if sc_num not in completed:
                    completed.append(sc_num)
                state["completed_scenes"] = completed
                save_flow_state(state_file, state)
            else:
                failed.append(sc_num)
                state["failed_scenes"] = failed
                save_flow_state(state_file, state)

        context.close()

    print("\n" + "=" * 60, flush=True)
    print("BATCH SUMMARY", flush=True)
    print(f"  Completed: {len(completed)}/{len(prompts)} scenes", flush=True)
    if failed:
        print(f"  Failed: {failed}", flush=True)
    print("=" * 60 + "\n", flush=True)

    return {
        "success": len(failed) == 0,
        "completed": completed,
        "failed": failed
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google Flow Persistent Browser Automation")
    parser.add_argument("--setup", action="store_true", help="Launch interactive one-time Google login setup")
    parser.add_argument("--project", default="earth_stops_rotating", help="Project name")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    args = parser.parse_args()

    if args.setup:
        run_first_time_setup()
    else:
        proj_dir = config.PROJECTS_DIR / args.project
        prompts_file = proj_dir / "google_flow_prompts.json"
        clips_folder = proj_dir / "clips"
        generate_all_flow_clips(
            prompts_path=prompts_file,
            clips_dir=clips_folder,
            headless=args.headless
        )
