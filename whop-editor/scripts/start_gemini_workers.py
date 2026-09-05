import logging
from pathlib import Path
import sys

# Windows UTF-8 console output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from browser.profile_registry import ProfileRegistry, ProfileAuthStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("start_gemini_workers")


def discover_and_report_profiles():
    registry = ProfileRegistry()
    profiles = registry.get_all_profiles()

    print("=" * 70)
    print(" GEMINI PRODUCTION WORKER PROFILE REGISTRY")
    print("=" * 70)
    print(f"{'Profile ID':<16} | {'Auth Status':<15} | {'Runtime':<8} | {'Account Email':<26}")
    print("-" * 70)

    auth_count = 0
    for p in profiles:
        status_badge = f"[{p.auth_status.value}]"
        if p.auth_status == ProfileAuthStatus.AUTHENTICATED:
            auth_count += 1
            mark = "🟢"
        else:
            mark = "⚪"

        email = p.account_email or "Not set"
        print(f"{mark} {p.profile_id:<14} | {status_badge:<15} | {p.current_status.value:<8} | {email:<26}")

    print("=" * 70)
    print(f"Summary: {auth_count}/{len(profiles)} profiles ready for automatic production review.")
    if auth_count > 0:
        print(f"Production will automatically route review jobs to available authenticated profiles.")
    else:
        print("WARNING: No profiles currently authenticated.")
    print("=" * 70 + "\n")

    return profiles


if __name__ == "__main__":
    discover_and_report_profiles()
