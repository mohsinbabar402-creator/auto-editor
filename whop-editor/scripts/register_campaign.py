import json
import logging
from pathlib import Path
import sys
import uuid

# Add whop-editor to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import check_db_connection
from db.repository import DatabaseRepository, DuplicateEntityError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("register_campaign")

CAMPAIGN_ID = "camp_whop_content_rewards_2026"
PROJECT_ID = "proj_whop_shortform"
CAMPAIGN_NAME = "Whop Creator Content Rewards Campaign (2026)"

# Sanitized configuration strictly marking unknown fields as UNKNOWN / AWAITING USER INPUT
CAMPAIGN_CONFIG = {
    "campaign_name": "Whop Creator Content Rewards Campaign (2026)",
    "campaign_goals": (
        "Produce high-retention educational short-form videos highlighting "
        "creator monetization, software community growth, and digital product distribution on Whop."
    ),
    "target_audience": "SaaS founders, digital product creators, and online community builders",
    "allowed_platforms": ["YouTube Shorts", "TikTok", "Instagram Reels"],
    "eligible_source_material": [
        "whop-editor/data/input/justin_clouted_whop_12s.mp4",
        "projects/07_whop_clipping/raw/the_cap_table_clouted_source.mp4"
    ],
    "required_hashtags": "UNKNOWN / AWAITING USER INPUT",
    "required_mentions": "UNKNOWN / AWAITING USER INPUT",
    "call_to_action": "UNKNOWN / AWAITING USER INPUT",
    "sound_music_rules": "UNKNOWN / AWAITING USER INPUT",
    "reward_structure": "UNKNOWN / AWAITING USER INPUT",
    "submission_method": "UNKNOWN / AWAITING USER INPUT",
    "deadlines_validity_window": "UNKNOWN / AWAITING USER INPUT",
    "prohibited_topics": "UNKNOWN / AWAITING USER INPUT",
    "sanitized": True,
    "compliance_status": "AWAITING_USER_BRIEF_CONFIRMATION",
    "security_note": "External campaign text ingested strictly as passive metadata; instruction execution disabled."
}


def register_new_whop_campaign():
    if not check_db_connection():
        logger.error("PostgreSQL is not reachable.")
        return False

    repo = DatabaseRepository()

    # Ensure parent project exists
    if not repo.get_project(PROJECT_ID):
        repo.create_project(
            project_id=PROJECT_ID,
            name="Whop Short-Form Creator Education",
            niche_description="Educational video shorts for creator communities and SaaS founders."
        )
        logger.info(f"Created parent project: {PROJECT_ID}")

    existing = repo.get_campaign(CAMPAIGN_ID)
    if existing:
        logger.info(f"Campaign '{CAMPAIGN_ID}' already registered in PostgreSQL.")
        print(f">> Existing Campaign Verified: {existing['name']}")
        return True

    repo.create_campaign(
        campaign_id=CAMPAIGN_ID,
        project_id=PROJECT_ID,
        name=CAMPAIGN_NAME,
        status="active",
        config=CAMPAIGN_CONFIG
    )

    repo.log_audit(
        audit_id=f"audit_camp_{uuid.uuid4().hex[:8]}",
        action="REGISTER_CAMPAIGN",
        target=CAMPAIGN_ID,
        detail=f"Registered isolated campaign '{CAMPAIGN_NAME}' under project '{PROJECT_ID}' with sanitized config."
    )

    logger.info(f"Successfully registered campaign '{CAMPAIGN_ID}' in PostgreSQL.")
    print(f">> Campaign Registered: {CAMPAIGN_NAME} (ID: {CAMPAIGN_ID})")
    return True


if __name__ == "__main__":
    success = register_new_whop_campaign()
    sys.exit(0 if success else 1)
