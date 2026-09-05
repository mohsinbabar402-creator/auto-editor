import logging
from pathlib import Path
from typing import Optional, Tuple
from playwright.sync_api import BrowserContext, Page, sync_playwright

logger = logging.getLogger("whop_editor.gemini_launcher")


class GeminiLauncher:
    """
    Centralized, reusable browser launcher for Gemini automation.
    Uses normal Chrome with persistent user-data directories and Playwright.
    Zero stealth hacks, zero private APIs, zero credentials stored.
    """

    DEFAULT_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check"
    ]

    @classmethod
    def launch_profile(
        cls,
        user_data_dir: str | Path,
        playwright_instance,
        headless: bool = False,
        timeout_ms: int = 45000
    ) -> Tuple[BrowserContext, Page]:
        p_dir = Path(user_data_dir).resolve()
        p_dir.mkdir(parents=True, exist_ok=True)

        for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            f = p_dir / lk
            if f.exists():
                try:
                    f.unlink()
                except Exception:
                    pass

        logger.info(f"Launching Chrome persistent context from: {p_dir} (headless={headless})")

        ctx = playwright_instance.chromium.launch_persistent_context(
            user_data_dir=str(p_dir),
            channel="chrome",
            headless=headless,
            args=cls.DEFAULT_ARGS,
            viewport={"width": 1280, "height": 900}
        )

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(timeout_ms)
        return ctx, page

    @classmethod
    def open_gemini(cls, page: Page, timeout_ms: int = 45000) -> Page:
        logger.info("Navigating to https://gemini.google.com/app ...")
        last_err = None
        for attempt in range(1, 4):
            try:
                page.goto("https://gemini.google.com/app", timeout=timeout_ms, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                return page
            except Exception as e:
                last_err = e
                logger.warning(f"Navigating to Gemini attempt {attempt} failed ({e}). Retrying in 2s...")
                page.wait_for_timeout(2000)
        raise last_err

    @classmethod
    def verify_gemini_session(cls, page: Page) -> Tuple[bool, Optional[str]]:
        """
        Validates if the active browser session on Gemini is authenticated.
        Returns (True, user_identifier) if authenticated.
        Returns (False, "AUTH_REQUIRED") if signed out or sign-in prompt is visible.
        """
        try:
            body_text = page.inner_text("body")
            has_signin = "Sign in" in body_text and ("Sign in with Google" in body_text or "Sign in to try" in body_text or "Sign in to save activity" in body_text)
            
            avatar = page.query_selector('a[aria-label*="Google Account" i], button[aria-label*="Google Account" i]')
            if avatar:
                aria = (avatar.get_attribute("aria-label") or "").strip()
                # Ensure it is not an external help link
                if "Help Center" not in aria and not has_signin:
                    return True, aria

            if has_signin or not avatar:
                return False, "AUTH_REQUIRED"

            return True, "Authenticated User"
        except Exception as e:
            logger.warning(f"Error checking Gemini session: {e}")
            return False, "AUTH_REQUIRED"

    @classmethod
    def close_context(cls, context: BrowserContext):
        if context:
            try:
                for p in context.pages:
                    try:
                        p.close()
                    except Exception:
                        pass
                context.close()
                logger.info("Closed Chrome persistent context cleanly.")
            except Exception as e:
                logger.warning(f"Error during context close: {e}")
