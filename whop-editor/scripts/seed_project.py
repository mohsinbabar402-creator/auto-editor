import logging
import sys
import uuid
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.repository import DatabaseRepository, DuplicateEntityError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_project")

DEFAULT_PROJECT_ID = "proj_whop_shortform"
DEFAULT_PROJECT_NAME = "Whop Short-Form Creator Education"
DEFAULT_PROJECT_NICHE = (
    "High-retention educational shorts for digital creators and founders "
    "selling software, communities, and digital products on Whop."
)


def seed_default_project() -> bool:
    repo = DatabaseRepository()
    try:
        existing = repo.get_project(DEFAULT_PROJECT_ID)
        if existing:
            logger.info(f"Project '{DEFAULT_PROJECT_ID}' already exists: {existing['name']}")
            return True

        repo.create_project(
            project_id=DEFAULT_PROJECT_ID,
            name=DEFAULT_PROJECT_NAME,
            niche_description=DEFAULT_PROJECT_NICHE
        )
        repo.log_audit(
            audit_id=f"audit_seed_{uuid.uuid4().hex[:8]}",
            action="SEED_PROJECT",
            target=DEFAULT_PROJECT_ID,
            detail=f"Seeded default project '{DEFAULT_PROJECT_NAME}'"
        )
        logger.info(f"Successfully seeded project: {DEFAULT_PROJECT_ID}")
        return True
    except DuplicateEntityError:
        logger.info(f"Project '{DEFAULT_PROJECT_ID}' already exists (handled conflict).")
        return True
    except Exception as e:
        logger.error(f"Failed to seed project: {e}")
        return False


if __name__ == "__main__":
    success = seed_default_project()
    sys.exit(0 if success else 1)
